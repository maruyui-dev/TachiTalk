"""Independent updater. Frozen as a separate onefile EXE; never updates itself in place."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from contextlib import ExitStack

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.updates.manifest import load_signed, atomic_json
from app.updates.install import apply_archive, InstallLock, InstallBusyError, recover, uninstall_voice, uninstall_component
from app.updates.progress import InstallProgress
from app.updates.cleanup import cleanup_committed


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
    parser.add_argument('--uninstall-training', action='store_true')
    parser.add_argument('--show-progress', action='store_true')
    parser.add_argument('--observe', action='store_true', help='只读查看已有安装，不启动安装或恢复')
    args = parser.parse_args(argv)
    if args.observe:
        from app.updates.progress_window import show_progress
        return show_progress(args.result)
    if args.show_progress:
        from app.updates.progress_window import show_progress
        return show_progress(args.result, lambda: execute(args))
    return execute(args)


def execute(args):
    root = Path(args.root).resolve()
    try:
        # Own the installation before publishing anything: competing observers or
        # recovery attempts must never overwrite the active owner's telemetry/result.
        with ExitStack() as stack:
            with InstallLock(root):
                progress = stack.enter_context(InstallProgress(args.result, root))
                outcome = run_install(args, root, progress)
            # Release the OS lock before starting the app. Otherwise its startup
            # check can mistake this just-finished updater for an active install.
            return complete_install(args, root, progress, outcome)
    except InstallBusyError:
        return 2


def run_install(args, root, progress):
    bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    ok = False
    parent_exited = not args.parent_pid
    error_text = ''
    cleanup = None
    try:
        if not (root / 'TachiTalk.exe').is_file() and not (root / 'main.py').is_file():
            raise ValueError('所选目录不是TachiTalk安装目录')
        if args.parent_pid:
            progress.report('waiting')
            wait_parent(args.parent_pid)
            parent_exited = True
        if getattr(args, 'uninstall_training', False):
            uninstall_component(root, 'training', progress.report, lock_held=True)
        elif args.uninstall_voice:
            uninstall_voice(root, progress.report, lock_held=True)
        elif args.recover:
            progress.report('recovery')
            recover(root, progress.report)
        else:
            progress.report('prepare')
            # Only immutable bundled public keys; never a key from the install job.
            keys = json.loads((bundled / 'packaging/release_keys.json').read_text(encoding='utf-8'))
            _, payload = load_signed(args.manifest, keys)
            apply_archive(root, args.archive, payload, progress=progress.report, lock_held=True)
        ok = True
    except Exception as error:
        error_text = f'{type(error).__name__}: {error}'
    unresolved = (root / '.tachitalk-pending.json').exists()
    if ok and not unresolved:
        cleanup = cleanup_committed(root, progress.report)
        if not cleanup['complete']:
            progress.report('cleanup', message='安装已成功，部分材料未能清理；详见诊断信息', cleanup=cleanup)
    result = {'ok': ok, 'root': str(root), 'transaction': progress.state['transaction'],
              'started_at': progress.state['started_at'], 'finished_at': time.time(),
              'log': progress.state['log']}
    if error_text:
        result['error'] = error_text
    if cleanup is not None:
        result['cleanup'] = cleanup
    atomic_json(args.result, result)
    return ok, parent_exited, unresolved, error_text, cleanup


def complete_install(args, root, progress, outcome):
    ok, parent_exited, unresolved, error_text, cleanup = outcome
    restarted = False
    if args.restart and parent_exited and not unresolved:
        # Restarting the restored application is not a successful installation.
        # Keep the failed work phase/file/counters available in its diagnostics.
        if ok:
            progress.report('restart')
        command = [str(root / 'TachiTalk.exe')] if (root / 'TachiTalk.exe').is_file() else [sys.executable, str(root / 'main.py')]
        try:
            subprocess.Popen(command, cwd=root)
            restarted = True
        except OSError as error:
            progress.finish('restart_failed', f'自动启动失败：{error}。请手动打开主程序。')
            return 1
    elif args.restart and parent_exited and os.name == 'nt' and not args.show_progress:
        ctypes.windll.user32.MessageBoxW(None, '恢复未完成，请查看 updates/install-result.json 并保留事务备份。', 'TachiTalk 更新恢复', 0x10)
    status = 'succeeded' if ok else 'recovery_failed' if unresolved else 'failed'
    message = ('安装成功，已启动主程序' if restarted else '安装成功') if ok else error_text
    if ok and cleanup is not None:
        if cleanup['complete']:
            message += '；不必要的安装材料已清理'
        else:
            status = 'cleanup_pending'
            message += '；部分材料清理失败，请查看诊断信息和日志'
    progress.finish(status, message, restarted=restarted, cleanup=cleanup)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
