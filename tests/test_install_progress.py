"""Small isolated transactions: never touches the daily installation or models."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import subprocess
import os
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app.updates.progress import InstallProgress
from app.updates.progress_window import InstallProgressWindow
from app.updates.install import apply_archive, target
from tests.test_updates import bundle
from scripts import update_entry


class InstallProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_finished_transaction_leaves_readable_progress_and_stage_log(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.py').write_text('# fixture', encoding='utf-8')
            result = root / 'updates/install-result.json'
            self.assertEqual(update_entry.main(['--root', str(root), '--recover',
                                               '--result', str(result)]), 0)
            progress = result.with_name('install-progress.json')
            self.assertTrue(progress.is_file(), 'Installation has no readable progress record')
            state = json.loads(progress.read_text(encoding='utf-8'))
            self.assertEqual(state['status'], 'succeeded')
            self.assertTrue(Path(state['log']).is_file())
            self.assertIn('recovery', Path(state['log']).read_text(encoding='utf-8'))

    def test_real_archive_reports_all_stages_and_failure_reports_actual_recovery(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'TachiTalk.exe').write_bytes(b'old')
            payload, data = bundle()
            archive = root / 'fixture.zip'
            archive.write_bytes(data)
            events = []
            def report(phase, completed=None, total=None, **fields):
                if completed is not None and total is not None:
                    self.assertLessEqual(completed, total)
                events.append((phase, completed, total))
            apply_archive(root, archive, payload, progress=report)
            for phase in ('prepare', 'install'):
                self.assertIn(phase, [e[0] for e in events])
            self.assertNotIn('verify', [e[0] for e in events])
            for phase in ('prepare', 'install'):
                last = [e for e in events if e[0] == phase][-1]
                self.assertEqual(last[1], last[2], phase)
            (root / 'release-version.json').unlink()
            events.clear()
            def fail(*args):
                raise OSError('fixture replacement failed')
            with self.assertRaises(OSError):
                apply_archive(root, archive, payload, progress=report, fault=fail)
            self.assertIn('recovery', [e[0] for e in events])
            self.assertFalse((root / '.tachitalk-pending.json').exists())

    def test_qt_window_updates_remains_responsive_and_distinguishes_stall_and_dead_process(self):
        with TemporaryDirectory() as directory:
            result = Path(directory) / 'install-result.json'
            with InstallProgress(result, directory) as progress:
                window = InstallProgressWindow(result)
                window.show()
                progress.report('replace', 1, 4, current='runtime/one.dll')
                window.refresh()
                self.assertEqual(window.bar.value(), 250)
                self.assertIn('one.dll', window.current.text())
                self.assertFalse(window.close(), 'Closing an active owner must not stop the install')
                before = progress.state['progress_at']
                QTest.qWait(2100)
                self.assertGreater(progress.state['heartbeat_at'], before)
                self.assertEqual(progress.state['progress_at'], before, 'Heartbeat cannot fake work')
                progress.report('replace', 3, 4, current='runtime/three.dll')
                deadline = time.monotonic() + 3
                while window.bar.value() != 750 and time.monotonic() < deadline:
                    QTest.qWait(50)
                self.assertEqual(window.bar.value(), 750)
                with patch('app.updates.progress_window.time.time', return_value=time.time() + 180):
                    window.refresh()
                    self.assertIn('没有实际进度', window.notice.text())
                with patch('app.updates.progress_window.process_alive', return_value=False):
                    window.refresh()
                    self.assertIn('进程已退出', window.notice.text())
                progress.finish('recovery_failed', 'fixture backup hash mismatch')
                window.refresh()
                self.assertIn('恢复未完成', window.heading.text())
                self.assertIn('fixture backup', window.diagnostics.toPlainText())
                self.assertTrue(window.close())
                window.deleteLater()
                self.app.processEvents()

    @unittest.skipUnless(os.name == 'nt', 'Windows junction guard')
    def test_junction_and_traversal_guards_survive_path_optimization(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'root'
            outside = Path(directory) / 'outside'
            root.mkdir(); outside.mkdir()
            link = root / 'linked'
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                           cwd=Path(__file__).resolve().parents[1], capture_output=True, check=True)
            with self.assertRaises(ValueError):
                target(root, 'linked/file.bin')
            with self.assertRaises(ValueError):
                target(root, '../outside/file.bin')
            self.assertEqual(target(root, 'safe/deep/file.bin'), root.resolve() / 'safe/deep/file.bin')


if __name__ == '__main__':
    unittest.main()
