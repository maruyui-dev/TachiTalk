"""File transactions with write-ahead recovery. No remote shell commands."""
from contextlib import AbstractContextManager, nullcontext
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid
import zipfile

from app.updates.manifest import allowed_path, atomic_json, canonical, filesystem_path, safe_path, sha256, validate


def version_path(component):
    return {'main': 'release-version.json', 'voice': 'services/gpt_sovits/component-version.json',
            'training': 'services/gpt_sovits/training/component-version.json'}[component]


def local_version(root, component='main'):
    record = filesystem_path(root) / version_path(component)
    if record.exists():
        return json.loads(record.read_text(encoding='utf-8'))['version']
    # Old onedir installations and the stable source baseline have no version record.
    return '0.2.0' if component == 'main' else 'legacy-v2ProPlus-cu128'


def target(root, name):
    safe_path(name)
    root = Path(root).resolve()
    path = root.joinpath(*name.split('/'))
    for part in (path, *path.parents):
        if part == root:
            break
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
            raise ValueError('安装目录中不允许链接或目录联接')
    # safe_path excludes absolute paths and '..'; every ancestor below the
    # canonical root was just checked for reparse points. Resolving the full
    # deep runtime path again repeats the same filesystem traversal per file.
    if not path.is_relative_to(root):
        raise ValueError('文件超出安装目录')
    return path


class InstallBusyError(RuntimeError):
    """Another process owns this installation; its transaction must be left alone."""


class InstallLock(AbstractContextManager):
    def __init__(self, root):
        self.path = Path(root) / '.tachitalk-update.lock'
        self.stream = None

    def __enter__(self):
        try:
            self.stream = self.path.open('a+b')
        except OSError as error:
            if getattr(error, 'winerror', None) in (32, 33):
                raise InstallBusyError('已有安装或更新进程正在运行') from error
            raise
        locking = False
        try:
            if os.name == 'nt':
                import msvcrt
                # Reading the locked first byte itself fails on Windows. Its
                # length can be checked without touching another owner's byte.
                if os.fstat(self.stream.fileno()).st_size == 0:
                    self.stream.write(b'0')
                    self.stream.flush()
                self.stream.seek(0)
                locking = True
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                locking = True
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            if locking and (error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
                            or getattr(error, 'winerror', None) in (32, 33)):
                raise InstallBusyError('已有安装或更新进程正在运行') from error
            raise
        return self

    def __exit__(self, *args):
        self.stream.close()  # OS releases the lock, including on process death.


def recover(root, progress=None):
    """Call under InstallLock, before launching application or another transaction."""
    root = filesystem_path(root)
    pending = root / '.tachitalk-pending.json'
    report = progress or (lambda *a, **k: None)
    if not pending.exists():
        return
    report('recovery')
    journal = json.loads(pending.read_text(encoding='utf-8'))
    backup = target(root, journal['backup'])
    if not journal['backup'].startswith('.tachitalk-transactions/'):
        raise ValueError('无效备份目录')
    if journal['state'] != 'committed':
        total = len(journal['operations'])
        for index, item in enumerate(reversed(journal['operations'])):
            report('recovery', index, total, current=item['path'])
            if item['path'] != version_path(journal['component']):
                allowed_path(journal['component'], item['path'])
            path = target(root, item['path'])
            if item['existed']:
                saved = target(backup, item['path'])
                if not saved.is_file() or sha256(saved) != item['sha256']:
                    raise ValueError('备份缺失或损坏，请保留事务目录并手动恢复')
                # An occupied file that was never replaced is already the correct original.
                # Skipping it lets earlier successful replacements roll back while that lock remains.
                if not path.is_file() or sha256(path) != item['sha256']:
                    replace_file(saved, path)
            else:
                path.unlink(missing_ok=True)
            report('recovery', index + 1, total, current=item['path'])
    else:
        from app.updates.cleanup import mark_committed
        mark_committed(root, backup.parent, journal.get('cleanup_cache'), journal.get('cleanup_preserve'))
    pending.unlink()


def replace_file(source, destination):
    source, destination = filesystem_path(source), filesystem_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.tachitalk-new')
    shutil.copyfile(source, temporary)
    with temporary.open('r+b') as stream:
        os.fsync(stream.fileno())
    shutil.copystat(source, temporary)
    temporary.replace(destination)


def disk_required(payload, root):
    root = filesystem_path(root)
    size = sum(file['size'] for file in payload['files'])
    backup = sum(path.stat().st_size for name in [r['path'] for r in payload['files']] + payload.get('delete', [])
                 if (path := target(root, name)).is_file())
    return size + backup + 32 * 1024 * 1024


def check_space(payload, root):
    required, free = disk_required(payload, root), shutil.disk_usage(root).free
    if free < required:
        raise ValueError(f'安装空间不足：需要 {required} 字节，可用 {free} 字节')
    return required, free


def _backup_file(source, saved, *, allow_link, progress):
    saved.parent.mkdir(parents=True, exist_ok=True)
    if allow_link:
        try:
            os.link(source, saved)
        except OSError:
            pass  # FAT/exFAT, permission or sharing constraints: use the durable copy path.
        else:
            return sha256(saved, progress)
    digest = hashlib.sha256()
    copied = 0
    with source.open('rb') as src, saved.open('xb') as destination:
        while block := src.read(1024 * 1024):
            destination.write(block)
            digest.update(block)
            copied += len(block)
            progress(copied)
        destination.flush()
        os.fsync(destination.fileno())
    shutil.copystat(source, saved)
    return digest.hexdigest()


def apply_archive(root, archive, payload, *, fault=None, progress=None, lock_held=False):
    """Authenticate input, retain rollback data, then stream each file into place."""
    validate(payload)
    original_root = Path(root).resolve()
    root, archive = filesystem_path(original_root), filesystem_path(archive)
    report = progress or (lambda *a, **k: None)
    with nullcontext() if lock_held else InstallLock(root):
        recover(root, progress)
        report('prepare')
        if payload['component'] == 'main' and local_version(root) != payload['base_version']:
            raise ValueError('补丁不适用于当前主程序版本')
        if payload['component'] in ('voice', 'training'):
            from app.updates.manifest import version_tuple
            if version_tuple(local_version(root)) < version_tuple(payload.get('min_main_version', '1.3.0')):
                raise ValueError('请先升级主程序后安装此语音组件')
            if payload.get('base_version', '*') != '*' and local_version(root, payload['component']) != payload['base_version']:
                raise ValueError('语音补丁不适用于当前语音版本')
        if payload['component'] == 'training':
            from app.paths import voice_location
            base = voice_location(root, root / 'user_data')
            if not (base / 'services/gpt_sovits/runtime/python.exe').is_file():
                raise ValueError('请先安装 v2ProPlus 推理资源包，再安装训练扩展')
        archive_size = payload['archive']['size']
        if archive.stat().st_size != archive_size:
            raise ValueError('更新包完整性校验失败')
        records = {record['path']: record for record in payload['files']}
        record_name = version_path(payload['component'])
        prior_owned = {}
        existing_record = target(root, record_name)
        if existing_record.is_file():
            prior = json.loads(existing_record.read_text(encoding='utf-8'))
            prior_owned.update({r['path']: r for r in prior.get('files', [])})
        owned = dict(prior_owned)
        for name in payload.get('delete', []):
            owned.pop(name, None)
        owned.update(records)
        record_data = canonical({'version': payload['version'], 'files': list(owned.values())})
        operations = [*records, *payload.get('delete', []), record_name]
        plan, backup_bytes = [], 0
        for index, name in enumerate(operations):
            destination = target(root, name)
            existed = destination.exists()
            if existed and not destination.is_file():
                raise ValueError('目标不是普通文件，拒绝替换')
            size = destination.stat().st_size if existed else 0
            backup_bytes += size
            plan.append((name, destination, existed, size))
            # Before examining existing files, the preparation byte total is unknown.
            report('prepare', index + 1, None, current=name)
        required = sum(r['size'] for r in records.values()) + len(record_data) + backup_bytes + 32 * 1024**2
        if shutil.disk_usage(root).free < required:
            raise ValueError(f'安装空间不足：需要 {required} 字节')
        prepare_total = archive_size + backup_bytes
        report('prepare', 0, prepare_total, unit='bytes', current=archive.name)
        if sha256(archive, lambda n: report('prepare', n, prepare_total, unit='bytes', current=archive.name)) != payload['archive']['sha256']:
            raise ValueError('更新包完整性校验失败')
        transaction = root / '.tachitalk-transactions' / uuid.uuid4().hex
        stage, backup = transaction / 'stage', transaction / 'backup'
        target(root, transaction.relative_to(root).as_posix())
        stage.mkdir(parents=True)
        backup.mkdir()
        from app.updates.cleanup import managed_cache, mark_committed
        journal = {'component': payload['component'], 'state': 'applying',
                   'backup': backup.relative_to(root).as_posix(), 'operations': [],
                   'cleanup_cache': managed_cache(root, archive, payload), 'cleanup_preserve': []}
        pending = root / '.tachitalk-pending.json'
        with zipfile.ZipFile(archive) as zipped:
            infos = zipped.infolist()
            if len(infos) != len(records) or {i.filename for i in infos} != set(records):
                raise ValueError('压缩包内容与签名文件清单不一致')
            for info in infos:
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.file_size != records[info.filename]['size']:
                    raise ValueError('压缩包文件类型或大小不合法')
            prepared = archive_size
            for name, destination, existed, size in plan:
                digest = ''
                if existed:
                    saved = target(backup, name)
                    sensitive = name.lower().startswith(('assets/audio/tts_reference/',
                        'services/gpt_sovits/gpt_weights', 'services/gpt_sovits/sovits_weights',
                        'services/gpt_sovits/training/gpt_sovits/pretrained_models/',
                        'services/gpt_sovits/training/models/'))
                    digest = _backup_file(destination, saved, allow_link=not sensitive,
                        progress=lambda n, base=prepared, name=name: report('prepare', base + n,
                            prepare_total, unit='bytes', current=name))
                    if sensitive and prior_owned.get(name, {}).get('sha256') != digest:
                        journal['cleanup_preserve'].append(name)
                prepared += size
                journal['operations'].append({'path': name, 'existed': existed, 'sha256': digest})
                report('prepare', prepared, prepare_total, unit='bytes', current=name)
            # Complete, durable recovery plan BEFORE the first final file changes.
            atomic_json(pending, journal)
            installed_bytes = installed_files = 0
            total_bytes = sum(r['size'] for r in records.values()) + len(record_data)
            indices = {name: index for index, name in enumerate(operations)}
            report('install', 0, total_bytes, unit='bytes', files_done=0, files_total=len(operations))
            try:
                for info in infos:
                    record = records[info.filename]
                    output = target(stage, info.filename)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with zipped.open(info) as source, output.open('xb') as destination:
                        copied = 0
                        while block := source.read(1024 * 1024):
                            copied += len(block)
                            if copied > record['size']:
                                raise ValueError('解压文件超过签名大小')
                            destination.write(block)
                            digest.update(block)
                            installed_bytes += len(block)
                            report('install', installed_bytes, total_bytes, unit='bytes', current=info.filename,
                                   files_done=installed_files, files_total=len(operations))
                        if copied != record['size'] or digest.hexdigest() != record['sha256']:
                            raise ValueError('解压文件大小或哈希不匹配')
                        destination.flush()
                        os.fsync(destination.fileno())
                    destination = target(root, info.filename)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    output.replace(destination)  # Same volume: no second whole-file copy.
                    installed_files += 1
                    if fault:
                        fault(indices[info.filename], info.filename)
                    report('install', installed_bytes, total_bytes, unit='bytes', current=info.filename,
                           files_done=installed_files, files_total=len(operations))
                for name in payload.get('delete', []):
                    target(root, name).unlink(missing_ok=True)
                    installed_files += 1
                    if fault:
                        fault(indices[name], name)
                    report('install', installed_bytes, total_bytes, unit='bytes', current=name,
                           files_done=installed_files, files_total=len(operations))
                output = target(stage, record_name)
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open('xb') as stream:
                    stream.write(record_data)
                    stream.flush()
                    os.fsync(stream.fileno())
                destination = target(root, record_name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                output.replace(destination)
                if fault:
                    fault(indices[record_name], record_name)
                installed_bytes += len(record_data)
                report('install', installed_bytes, total_bytes, unit='bytes', current=record_name,
                       files_done=len(operations), files_total=len(operations))
                journal['state'] = 'committed'
                atomic_json(pending, journal)
                mark_committed(root, transaction, journal['cleanup_cache'], journal['cleanup_preserve'])
                pending.unlink()
            except BaseException:
                recover(root, progress)
                raise
        return original_root / transaction.relative_to(root)


def uninstall_voice(root, progress=None, lock_held=False):
    return uninstall_component(root, 'voice', progress, lock_held)


def uninstall_component(root, component, progress=None, lock_held=False):
    """Remove only recorded, unchanged managed files. Legacy installations are never guessed."""
    if component not in ('voice', 'training'):
        raise ValueError('不能卸载此组件')
    root = filesystem_path(Path(root).resolve())
    report = progress or (lambda *a, **k: None)
    with nullcontext() if lock_held else InstallLock(root):
        recover(root, progress)
        record_name = version_path(component)
        record = target(root, record_name)
        if not record.is_file():
            raise ValueError('旧版或外部语音没有托管清单，不能自动卸载；请保留或手动管理该目录')
        owned = json.loads(record.read_text(encoding='utf-8')).get('files', [])
        if not owned:
            raise ValueError('没有已记录的可卸载语音文件')
        remove, preserved = [], []
        for index, item in enumerate(owned):
            report('verify', index, len(owned), current=item['path'])
            allowed_path(component, item['path'])
            path = target(root, item['path'])
            if path.is_file() and sha256(path) == item['sha256']:
                remove.append(item['path'])
            elif path.exists():
                preserved.append(item['path'])
        backup = root / '.tachitalk-transactions' / uuid.uuid4().hex / 'backup'
        target(root, backup.relative_to(root).as_posix())
        backup.mkdir(parents=True)
        if shutil.disk_usage(root).free < sum(target(root, n).stat().st_size for n in [*remove, record_name]) + 32 * 1024**2:
            raise ValueError('卸载备份磁盘空间不足')
        journal = {'component': component, 'state': 'applying', 'backup': backup.relative_to(root).as_posix(), 'operations': []}
        pending = root / '.tachitalk-pending.json'
        try:
            for index, name in enumerate([*remove, record_name]):
                report('backup', index, len(remove) + 1, current=name)
                path, saved = target(root, name), target(backup, name)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, saved)
                with saved.open('r+b') as stream:
                    os.fsync(stream.fileno())
                shutil.copystat(path, saved)
                journal['operations'].append({'path': name, 'existed': True, 'sha256': sha256(saved)})
            atomic_json(pending, journal)
            for index, name in enumerate([*remove, record_name]):
                report('uninstall', index, len(remove) + 1, current=name)
                path = target(root, name)
                path.unlink()
                report('uninstall', index + 1, len(remove) + 1, current=name)
            report('commit')
            journal['state'] = 'committed'
            atomic_json(pending, journal)
            from app.updates.cleanup import mark_committed
            mark_committed(root, backup.parent, None, [])
            pending.unlink()
        except BaseException:
            recover(root, progress)
            raise
        return preserved
