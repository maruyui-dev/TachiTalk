"""Remove only artifacts belonging to durably committed installation jobs.

Called under InstallLock. The small job survives interruption; no scan guesses
whether an older, unmarked transaction or a user-selected archive is disposable.
"""
import json
from pathlib import Path
import re
import stat
import logging

from app.updates.install import target
from app.updates.manifest import atomic_json, MAX_MANIFEST

JOB = 'cleanup.json'
PROFILES = ('user_data', '_qt_runtime_tmp')


def cleanup_updater_copies(root, data, started_at):
    """On the next app start, retire older helper copies after their UI exits.

    New copies are excluded by creation time, so this cannot race a new handoff.
    Windows keeps an active EXE protected; never terminate it to obtain deletion.
    """
    root, data = Path(root).resolve(), Path(data).absolute()
    if data not in [root / profile for profile in PROFILES]:
        return 0
    removed = 0
    try:
        directory = target(root, (data / 'updates/updaters').relative_to(root).as_posix())
        if not directory.is_dir():
            return 0
        for item in directory.iterdir():
            if not re.fullmatch('[0-9a-f]{32}\\.exe', item.name):
                continue
            try:
                item = target(root, item.relative_to(root).as_posix())
                info = item.stat()
                if not item.is_file() or getattr(info, 'st_birthtime', info.st_ctime) >= started_at:
                    continue
                item.unlink()
                removed += 1
            except (OSError, ValueError):
                continue  # Still running, or not one of our ordinary cached copies.
    except (OSError, ValueError):
        return removed
    if removed:
        logging.getLogger('tachitalk').info('已清理已退出更新器的临时副本：%d 个', removed)
    return removed


def managed_cache(root, archive, payload):
    """An offline ZIP outside our exact per-hash cache is always user-owned."""
    archive = Path(archive).absolute()
    for profile in PROFILES:
        expected = Path(root) / profile / 'updates/downloads' / payload['archive']['sha256'] / 'package.zip'
        if archive == expected:
            return {'profile': profile, 'sha256': payload['archive']['sha256'],
                    'parts': len(payload['parts'])}
    return None


def transaction_path(root, transaction):
    root, transaction = Path(root).resolve(), Path(transaction).absolute()
    if transaction.parent != root / '.tachitalk-transactions':
        raise ValueError('清理事务目录超出范围')
    return target(root, transaction.relative_to(root).as_posix())


def mark_committed(root, transaction, cache=None, preserve=None):
    """Persist after the committed journal, before removing the pending marker."""
    root = Path(root).resolve()
    transaction = transaction_path(root, transaction)
    name = (transaction / JOB).relative_to(root).as_posix()
    target(root, name + '.new')
    atomic_json(target(root, name), {'schema': 1, 'state': 'committed', 'cache': cache,
                                    'preserve': preserve or []})


def _jobs(root):
    directory = target(root, '.tachitalk-transactions')
    if not directory.exists():
        return
    for transaction in directory.iterdir():
        marker = transaction / JOB
        if not marker.exists():
            continue
        try:
            transaction_path(root, transaction)
            marker = target(root, marker.relative_to(root).as_posix())
            if marker.stat().st_size > MAX_MANIFEST:
                raise ValueError('清理任务记录过大')
            job = json.loads(marker.read_text(encoding='utf-8'))
            if job.get('schema') != 1 or job.get('state') != 'committed':
                raise ValueError('不是已提交的清理任务')
            yield transaction, job, None
        except (OSError, ValueError, TypeError, AttributeError) as error:
            yield transaction, None, error


def needs_cleanup(root):
    """Resume crashes once; a reported IO failure must not cause restart loops."""
    try:
        return any(job is not None and not job.get('blocked') for _, job, _ in _jobs(Path(root).resolve()))
    except (OSError, ValueError):
        return False  # Optional housekeeping must not prevent a usable app from starting.


def _tree(path, root, report, scanned):
    files, directories = [], []
    if not path.exists():
        return files, directories
    for item in path.iterdir():
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
            raise ValueError('清理材料中含链接或目录联接：' + str(item))
        if stat.S_ISDIR(info.st_mode):
            nested_files, nested_dirs = _tree(item, root, report, scanned)
            files.extend(nested_files)
            directories.extend(nested_dirs)
        elif stat.S_ISREG(info.st_mode):
            files.append((item, info.st_size))
            scanned[0] += 1
            report('cleanup', scanned[0], None, current=item.relative_to(root).as_posix())
        else:
            raise ValueError('清理材料包含非普通文件：' + str(item))
    directories.append(path)
    return files, directories


def _plan(root, transaction, job, report):
    files, directories, scanned = [], [], [0]
    preserve = set(job.get('preserve', []))
    for area in ('stage', 'backup'):
        path = target(root, (transaction / area).relative_to(root).as_posix())
        area_files, area_dirs = _tree(path, root, report, scanned)
        if area == 'backup':
            area_files = [(p, size) for p, size in area_files if p.relative_to(path).as_posix() not in preserve]
        files.extend(area_files)
        directories.extend(area_dirs)
    cache = job.get('cache')
    if cache is not None:
        if (not isinstance(cache, dict) or cache.get('profile') not in PROFILES
                or not isinstance(cache.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', cache['sha256'])
                or type(cache.get('parts')) is not int or not 0 <= cache['parts'] <= 100000):
            raise ValueError('清理下载任务路径不合法')
        directory = target(root, f"{cache['profile']}/updates/downloads/{cache['sha256']}")
        # Only downloader-owned names. Preserve any unrelated file in this cache.
        names = [f'{i:04d}.bin' + suffix for i in range(cache['parts'])
                 for suffix in ('', '.part', '.state.json')]
        names += ['package.zip.new', 'package.zip', 'manifest.json', 'source-lock.json']
        for name in names:
            path = target(root, (directory / name).relative_to(root).as_posix())
            if path.exists():
                if not path.is_file():
                    raise ValueError('下载材料不是普通文件：' + str(path))
                files.append((path, path.stat().st_size))
        directories.append(directory)
    return files, directories


def cleanup_committed(root, progress=None):
    root = Path(root).resolve()
    report = progress or (lambda *a, **k: None)
    result = {'complete': True, 'removed_files': 0, 'removed_bytes': 0, 'errors': [], 'preserved': []}
    if (root / '.tachitalk-pending.json').exists():
        result.update(complete=False, errors=['仍有待处理安装事务，未清理'])
        return result
    try:
        jobs = list(_jobs(root))
    except (OSError, ValueError) as error:
        result.update(complete=False, errors=[str(error)])
        return result
    for transaction, job, invalid in jobs:
        try:
            if invalid:
                raise ValueError(str(invalid))
            report('cleanup')
            files, directories = _plan(root, transaction, job, report)
            report('cleanup', 0, len(files))
            for index, (path, size) in enumerate(files):
                path.unlink()
                result['removed_files'] += 1
                result['removed_bytes'] += size
                report('cleanup', index + 1, len(files), current=path.relative_to(root).as_posix())
            for directory in directories:
                if directory.exists():
                    if any(directory.iterdir()):
                        result['preserved'].append(str(directory))
                    else:
                        directory.rmdir()
            (transaction / JOB).unlink()
            if not any(transaction.iterdir()):
                transaction.rmdir()
        except (OSError, ValueError, TypeError) as error:
            result['complete'] = False
            result['errors'].append(f'{transaction}: {type(error).__name__}: {error}')
            if job is not None:
                job['blocked'] = True
                try:
                    atomic_json(target(root, (transaction / JOB).relative_to(root).as_posix()), job)
                except OSError:
                    pass
    return result
