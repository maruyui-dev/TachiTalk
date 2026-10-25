"""Small throttled progress snapshots; never used as a recovery journal."""
import json
import os
from pathlib import Path
from threading import Event, RLock, Thread
import time
import uuid


class InstallProgress:
    def __init__(self, result, root):
        self.path = Path(result).with_name('install-progress.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.state = dict(transaction=uuid.uuid4().hex, pid=os.getpid(), root=str(root),
                          started_at=now, phase_started_at=now, progress_at=now,
                          heartbeat_at=now, status='running', phase='starting',
                          completed=None, total=None, unit='files', current='',
                          log=str(self.path.with_name('install-progress.log')))
        self.lock = RLock()
        self.stop = Event()
        self.last_write = self.last_log = 0
        self.thread = Thread(target=self._heartbeat, daemon=True)

    def __enter__(self):
        self.report('starting')
        self.thread.start()
        return self

    def _log(self):
        with Path(self.state['log']).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(self.state, ensure_ascii=False) + '\n')
        self.last_log = time.monotonic()

    def _write(self, force=False):
        if not force and time.monotonic() - self.last_write < .5:
            return
        # Telemetry needs atomic visibility, not a durable fsync for every refresh.
        # The separate install journal retains its original fsync/recovery rules.
        temporary = self.path.with_suffix('.json.new')
        try:
            temporary.write_text(json.dumps(self.state, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.path)
            self.last_write = time.monotonic()
        except OSError as error:
            self.state['telemetry_error'] = f'{type(error).__name__}: {error}'

    def report(self, phase, completed=None, total=None, unit='files', current='', **extra):
        with self.lock:
            now = time.time()
            changed = phase != self.state['phase']
            if changed:
                try:
                    self._log()  # End of preceding stage, including elapsed time/counters.
                except OSError:
                    pass
                self.state['phase_started_at'] = now
            files_changed = 'files_done' in extra and extra['files_done'] != self.state.get('files_done')
            if changed or files_changed or completed is not None and completed != self.state['completed']:
                self.state['progress_at'] = now
            self.state.update(phase=phase, completed=completed, total=total, unit=unit,
                              current=current, heartbeat_at=now, **extra)
            self._write(force=changed)
            if changed or time.monotonic() - self.last_log >= 10:
                try:
                    self._log()
                except OSError as error:
                    self.state['telemetry_error'] = str(error)

    def _heartbeat(self):
        while not self.stop.wait(2):
            with self.lock:
                self.state['heartbeat_at'] = time.time()
                self._write(force=True)

    def finish(self, status, message, **extra):
        with self.lock:
            self.state.update(status=status, message=message, finished_at=time.time(), **extra)
            self._write(force=True)
            try:
                self._log()
            except OSError:
                pass

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=3)


def process_alive(pid):
    if not pid:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied does not prove death.
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
