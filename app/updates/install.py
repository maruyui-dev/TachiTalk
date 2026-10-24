"""File transactions with write-ahead recovery. No remote shell commands."""
from contextlib import AbstractContextManager
import errno
import json
import os
from pathlib import Path
import shutil
import stat
import uuid
import zipfile

from app.updates.manifest import allowed_path, atomic_json, safe_path, sha256, validate


def version_path(component):
    return 'release-version.json' if component == 'main' else 'services/gpt_sovits/component-version.json'


def local_version(root, component='main'):
    record = Path(root) / version_path(component)
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
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('安装目录中不允许链接或目录联接')
    if not path.resolve().is_relative_to(root):
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


def recover(root):
    """Call under InstallLock, before launching application or another transaction."""
    root = Path(root)
    pending = root / '.tachitalk-pending.json'
    if not pending.exists():
        return
    journal = json.loads(pending.read_text(encoding='utf-8'))
    backup = target(root, journal['backup'])
    if not journal['backup'].startswith('.tachitalk-transactions/'):
        raise ValueError('无效备份目录')
    if journal['state'] != 'committed':
        for item in reversed(journal['operations']):
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
    pending.unlink()


def replace_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.tachitalk-new')
    shutil.copyfile(source, temporary)
    with temporary.open('r+b') as stream:
        os.fsync(stream.fileno())
    shutil.copystat(source, temporary)
    temporary.replace(destination)


def disk_required(payload, root):
    size = sum(file['size'] for file in payload['files'])
    backup = sum(path.stat().st_size for name in [r['path'] for r in payload['files']] + payload.get('delete', [])
                 if (path := target(root, name)).is_file())
    return size * 2 + backup + 32 * 1024 * 1024


def check_space(payload, root):
    required, free = disk_required(payload, root), shutil.disk_usage(root).free
    if free < required:
        raise ValueError(f'安装空间不足：需要 {required} 字节，可用 {free} 字节')
    return required, free


def apply_archive(root, archive, payload, *, fault=None):
    """Only use a payload returned by signature verification at an external boundary."""
    validate(payload)
    root, archive = Path(root).resolve(), Path(archive)
    with InstallLock(root):
        recover(root)
        if payload['component'] == 'main' and local_version(root) != payload['base_version']:
            raise ValueError('补丁不适用于当前主程序版本')
        if payload['component'] == 'voice':
            from app.updates.manifest import version_tuple
            if version_tuple(local_version(root)) < version_tuple(payload.get('min_main_version', '1.3.0')):
                raise ValueError('请先升级主程序后安装此语音组件')
            if payload.get('base_version', '*') != '*' and local_version(root, 'voice') != payload['base_version']:
                raise ValueError('语音补丁不适用于当前语音版本')
        if (archive.stat().st_size != payload['archive']['size'] or sha256(archive) != payload['archive']['sha256']):
            raise ValueError('更新包完整性校验失败')
        check_space(payload, root)
        transaction = root / '.tachitalk-transactions' / uuid.uuid4().hex
        stage, backup = transaction / 'stage', transaction / 'backup'
        # Reject pre-existing reparse points even in the transaction parent.
        target(root, transaction.relative_to(root).as_posix())
        stage.mkdir(parents=True)
        backup.mkdir()
        records = {record['path']: record for record in payload['files']}
        with zipfile.ZipFile(archive) as zipped:
            infos = zipped.infolist()
            if len(infos) != len(records) or {i.filename for i in infos} != set(records):
                raise ValueError('压缩包内容与签名文件清单不一致')
            for info in infos:
                record = records[info.filename]
                mode = info.external_attr >> 16
                if info.is_dir() or stat.S_ISLNK(mode) or info.file_size != record['size']:
                    raise ValueError('压缩包文件类型或大小不合法')
                output = target(stage, info.filename)
                output.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(info) as source, output.open('xb') as destination:
                    copied = 0
                    while block := source.read(1024 * 1024):
                        copied += len(block)
                        if copied > record['size']:
                            raise ValueError('解压文件超过签名大小')
                        destination.write(block)
                if copied != record['size'] or sha256(output) != record['sha256']:
                    raise ValueError('解压文件哈希不匹配')
        record_name = version_path(payload['component'])
        owned = {}
        existing_record = target(root, record_name)
        if existing_record.is_file():
            prior = json.loads(existing_record.read_text(encoding='utf-8'))
            owned.update({r['path']: r for r in prior.get('files', [])})
        for name in payload.get('delete', []):
            owned.pop(name, None)
        owned.update(records)
        atomic_json(target(stage, record_name), {'version': payload['version'], 'files': list(owned.values())})
        operations = [*records, *payload.get('delete', []), record_name]
        journal = {'component': payload['component'], 'state': 'applying',
                   'backup': backup.relative_to(root).as_posix(), 'operations': []}
        pending = root / '.tachitalk-pending.json'
        try:
            for index, name in enumerate(operations):
                destination = target(root, name)
                existed = destination.exists()
                if existed and not destination.is_file():
                    raise ValueError('目标不是普通文件，拒绝替换')
                digest = ''
                if existed:
                    saved = target(backup, name)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(destination, saved)
                    with saved.open('r+b') as stream:
                        os.fsync(stream.fileno())
                    shutil.copystat(destination, saved)
                    digest = sha256(saved)
                journal['operations'].append({'path': name, 'existed': existed, 'sha256': digest})
            # The complete backup plan is durable before the first replacement. Rewriting this
            # growing JSON for each of ~40k runtime files would otherwise cause quadratic I/O.
            atomic_json(pending, journal)
            for index, name in enumerate(operations):
                destination = target(root, name)
                if name in payload.get('delete', []):
                    destination.unlink(missing_ok=True)
                else:
                    replace_file(target(stage, name), destination)
                if fault:
                    fault(index, name)
            journal['state'] = 'committed'
            atomic_json(pending, journal)
            pending.unlink()
        except BaseException:
            recover(root)
            raise
        return transaction


def uninstall_voice(root):
    """Remove only recorded, unchanged managed files. Legacy installations are never guessed."""
    root = Path(root).resolve()
    with InstallLock(root):
        recover(root)
        record_name = version_path('voice')
        record = target(root, record_name)
        if not record.is_file():
            raise ValueError('旧版或外部语音没有托管清单，不能自动卸载；请保留或手动管理该目录')
        owned = json.loads(record.read_text(encoding='utf-8')).get('files', [])
        if not owned:
            raise ValueError('没有已记录的可卸载语音文件')
        remove, preserved = [], []
        for item in owned:
            allowed_path('voice', item['path'])
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
        journal = {'component': 'voice', 'state': 'applying', 'backup': backup.relative_to(root).as_posix(), 'operations': []}
        pending = root / '.tachitalk-pending.json'
        try:
            for name in [*remove, record_name]:
                path, saved = target(root, name), target(backup, name)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, saved)
                with saved.open('r+b') as stream:
                    os.fsync(stream.fileno())
                shutil.copystat(path, saved)
                journal['operations'].append({'path': name, 'existed': True, 'sha256': sha256(saved)})
            atomic_json(pending, journal)
            for name in [*remove, record_name]:
                path = target(root, name)
                path.unlink()
            journal['state'] = 'committed'
            atomic_json(pending, journal)
            pending.unlink()
        except BaseException:
            recover(root)
            raise
        return preserved
