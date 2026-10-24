"""Independent updater. Frozen as a separate onefile EXE; never updates itself in place."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.updates.manifest import load_signed, atomic_json
from app.updates.install import apply_archive, InstallLock, InstallBusyError, recover, uninstall_voice


def wait_parent(pid, timeout=90):
    if not pid or pid == os.getpid():
        raise ValueError('无效的主程序进程号')
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return  # Parent already exited.
            raise OSError('无法确认主程序是否关闭，拒绝覆盖')
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise TimeoutError('主程序尚未关闭，更新已取消')
        finally:
            kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(.1)
        raise TimeoutError('主程序尚未关闭')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--manifest')
    parser.add_argument('--archive')
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--result', required=True)
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--uninstall-voice', action='store_true')
    args = parser.parse_args(argv)
    # Trusted keys come from this updater's immutable build, never the downloaded job.
    bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    root = Path(args.root).resolve()
    ok = False
    parent_exited = not args.parent_pid
    try:
        if not (root / 'TachiTalk.exe').is_file() and not (root / 'main.py').is_file():
            raise ValueError('所选目录不是TachiTalk安装目录')
        keys = json.loads((bundled / 'packaging/release_keys.json').read_text(encoding='utf-8'))
        if not args.recover and not args.uninstall_voice:
            _, payload = load_signed(args.manifest, keys)
        if args.parent_pid:
            wait_parent(args.parent_pid)
            parent_exited = True
        if args.uninstall_voice:
            uninstall_voice(root)
        elif args.recover:
            with InstallLock(root):
                recover(root)
        else:
            apply_archive(root, args.archive, payload)
        ok = True
        atomic_json(args.result, {'ok': True, 'root': str(root)})
    except InstallBusyError:
        # The original updater owns both the files and its result. In particular
        # a racing startup recovery must not report that live transaction failed.
        return 2
    except Exception as error:
        atomic_json(args.result, {'ok': False, 'root': str(root), 'error': f'{type(error).__name__}: {error}'})
    # Attempt restart even after a rolled-back failure. An unresolved journal is handled at startup.
    if args.restart and parent_exited and not (root / '.tachitalk-pending.json').exists():
        command = [str(root / 'TachiTalk.exe')] if (root / 'TachiTalk.exe').is_file() else [sys.executable, str(root / 'main.py')]
        subprocess.Popen(command, cwd=root)
    elif args.restart and parent_exited and os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None, '恢复未完成，请查看 updates/install-result.json 并保留事务备份。', 'TachiTalk 更新恢复', 0x10)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
