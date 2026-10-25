"""Active installs must not be mistaken for abandoned recovery journals.

All files are tiny temporary fixtures. The only real child process owns a lock
on that temporary installation and exits through its own stdin release signal.
No desktop installation, running updater, download cache, or voice model is used.
"""
from contextlib import contextmanager, redirect_stdout
import errno
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from app import bootstrap
from app.updates.install import InstallLock
from scripts import update_entry


PROJECT = Path(__file__).resolve().parents[1]


class ActiveInstallStartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='tachitalk-active-install-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.root = self.directory / 'fixture installation'
        self.root.mkdir()
        (self.root / 'TachiTalk.exe').write_bytes(b'fixture - never executed')
        self.data = self.directory / 'isolated profile'
        self.result = self.data / 'updates/install-result.json'
        self.result.parent.mkdir(parents=True)
        self.result.write_bytes(b'{"ok":true,"owner":"original installation result"}')
        self.pending = self.root / '.tachitalk-pending.json'
        self.backup = self.root / '.tachitalk-transactions/fixture-backup'
        self.backup.mkdir(parents=True)
        self.partial = self.root / 'services/gpt_sovits/fixture.txt'
        self.partial.parent.mkdir(parents=True)
        self.partial.write_bytes(b'new partial payload')
        journal = {'component': 'voice', 'state': 'applying',
                   'backup': '.tachitalk-transactions/fixture-backup',
                   'operations': [{'path': 'services/gpt_sovits/fixture.txt',
                                   'existed': False}]}
        self.pending.write_text(json.dumps(journal), encoding='utf-8')
        self.pending_bytes = self.pending.read_bytes()
        self.result_bytes = self.result.read_bytes()

    @contextmanager
    def external_owner(self):
        """Hold the actual OS lock in an isolated, explicitly owned process."""
        ready = self.directory / 'holder-ready'
        code = ('import sys; from pathlib import Path; '
                'from app.updates.install import InstallLock; '
                'lock=InstallLock(sys.argv[1]); lock.__enter__(); '
                'Path(sys.argv[2]).write_text("locked",encoding="ascii"); '
                'sys.stdin.buffer.read(1); lock.__exit__(None,None,None)')
        process = subprocess.Popen([sys.executable, '-B', '-c', code,
                                    str(self.root), str(ready)], cwd=PROJECT,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists(), 'The isolated holder did not acquire its fixture lock')
            yield
        finally:
            try:
                _, errors = process.communicate(b'x', timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()  # Only the process started above, never another updater.
                _, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors.decode('utf-8', errors='replace'))

    def launch_bootstrap(self):
        output = StringIO()
        with patch('app.paths.PROJECT_ROOT', self.root), \
             patch('app.paths.DATA_ROOT', self.data), \
             patch.object(sys, 'frozen', False, create=True), \
             patch('subprocess.Popen') as recovery, \
             patch('app.updates.progress_window.show_progress') as viewer, redirect_stdout(output):
            code = bootstrap.main()
        return code, recovery, output.getvalue()

    def recover_arguments(self):
        return ['--root', str(self.root), '--recover',
                '--result', str(self.result), '--restart']

    def test_active_owner_with_pending_blocks_bootstrap_recovery_without_mutation(self):
        with self.external_owner():
            code, recovery, message = self.launch_bootstrap()
        with self.subTest(outcome='no competing recovery updater'):
            recovery.assert_not_called()
        with self.subTest(outcome='busy is not successful startup'):
            self.assertEqual(code, 2)
        with self.subTest(outcome='explicit install-in-progress notice'):
            self.assertIn('安装', message)
            self.assertIn('正在', message)
        self.assertEqual(self.pending.read_bytes(), self.pending_bytes)
        self.assertEqual(self.result.read_bytes(), self.result_bytes)
        self.assertEqual(self.partial.read_bytes(), b'new partial payload')

    def test_released_owner_with_pending_still_launches_recovery(self):
        with self.external_owner():
            pass
        code, recovery, _ = self.launch_bootstrap()
        self.assertEqual(code, 0)
        recovery.assert_called_once()
        command = recovery.call_args.args[0]
        self.assertIn('--recover', command)
        self.assertIn('--restart', command)
        self.assertEqual(command[command.index('--root') + 1], str(self.root))
        self.assertEqual(self.pending.read_bytes(), self.pending_bytes)

    def test_recovery_racing_active_owner_keeps_result_and_does_not_report_failed_recovery(self):
        with self.external_owner():
            with patch.object(update_entry.subprocess, 'Popen') as restart, \
                 patch.object(update_entry.ctypes.windll.user32, 'MessageBoxW') as popup:
                code = update_entry.main(self.recover_arguments())
        with self.subTest(outcome='preserve original updater result'):
            self.assertEqual(self.result.read_bytes(), self.result_bytes)
        with self.subTest(outcome='busy does not display recovery failure'):
            popup.assert_not_called()
        with self.subTest(outcome='busy cannot restart an application'):
            restart.assert_not_called()
        self.assertEqual(code, 2, 'Busy recovery must not pretend the journal was recovered')
        self.assertEqual(self.pending.read_bytes(), self.pending_bytes)
        self.assertEqual(self.partial.read_bytes(), b'new partial payload')

    def test_recovery_after_owner_releases_performs_real_rollback_and_restart(self):
        with self.external_owner():
            pass
        with patch.object(update_entry.subprocess, 'Popen') as restart, \
             patch.object(update_entry.ctypes.windll.user32, 'MessageBoxW') as popup:
            code = update_entry.main(self.recover_arguments())
        self.assertEqual(code, 0)
        self.assertFalse(self.pending.exists())
        self.assertFalse(self.partial.exists())
        self.assertTrue(json.loads(self.result.read_text(encoding='utf-8'))['ok'])
        restart.assert_called_once_with([str(self.root / 'TachiTalk.exe')], cwd=self.root)
        popup.assert_not_called()

    def test_genuine_recovery_failure_keeps_original_journal_backup_and_diagnostic(self):
        saved = self.backup / 'services/gpt_sovits/fixture.txt'
        saved.parent.mkdir(parents=True)
        saved.write_bytes(b'corrupt backup fixture')
        journal = json.loads(self.pending.read_text(encoding='utf-8'))
        journal['operations'][0].update(existed=True, sha256='0' * 64)
        self.pending.write_text(json.dumps(journal), encoding='utf-8')
        original = self.pending.read_bytes()
        with patch.object(update_entry.subprocess, 'Popen') as restart, \
             patch.object(update_entry.ctypes.windll.user32, 'MessageBoxW') as popup:
            code = update_entry.main(self.recover_arguments())
        self.assertNotEqual(code, 0)
        self.assertEqual(self.pending.read_bytes(), original)
        self.assertEqual(saved.read_bytes(), b'corrupt backup fixture')
        self.assertEqual(self.partial.read_bytes(), b'new partial payload')
        result = json.loads(self.result.read_text(encoding='utf-8'))
        self.assertFalse(result['ok'])
        self.assertIn('备份', result['error'])
        restart.assert_not_called()
        popup.assert_called_once()

    def test_lock_io_failure_is_not_reclassified_as_a_competing_installer(self):
        lock_api = 'msvcrt.locking' if os.name == 'nt' else 'fcntl.flock'
        with patch(lock_api, side_effect=OSError(errno.EIO, 'fixture lock device error')):
            try:
                with InstallLock(self.root):
                    self.fail('The fixture must fail to acquire its lock')
            except (OSError, RuntimeError) as error:
                caught = error
        self.assertIsInstance(caught, OSError, 'A non-contention IO failure must remain diagnosable')
        self.assertEqual(caught.errno, errno.EIO)

    @unittest.skipUnless(os.name == 'nt', 'Windows lock file initialization')
    def test_lock_metadata_permission_failure_is_not_install_contention(self):
        lock = InstallLock(self.root)
        with patch('app.updates.install.os.fstat', side_effect=PermissionError(errno.EACCES, 'fixture metadata denied')):
            with self.assertRaises(OSError) as caught:
                with lock:
                    self.fail('The metadata lookup must fail')
        self.assertEqual(caught.exception.errno, errno.EACCES)
        self.assertTrue(lock.stream.closed)


if __name__ == '__main__':
    unittest.main()
