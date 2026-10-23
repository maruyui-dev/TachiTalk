"""Updater must not restart a second app when its parent is still running."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import update_entry


class UpdateEntryTests(unittest.TestCase):
    def test_parent_wait_failure_does_not_start_duplicate_application(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'TachiTalk.exe').write_bytes(b'fixture')
            result = root / 'result.json'
            with patch.object(update_entry, 'wait_parent', side_effect=TimeoutError('still running')), \
                    patch.object(update_entry.subprocess, 'Popen') as restart:
                code = update_entry.main(['--root', str(root), '--recover', '--parent-pid', '123',
                                          '--result', str(result), '--restart'])
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(result.read_text())['ok'])
            restart.assert_not_called()

    def test_recovered_failure_after_parent_exit_restarts_original_application(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'TachiTalk.exe').write_bytes(b'fixture')
            result = root / 'result.json'
            with patch.object(update_entry, 'wait_parent'), \
                    patch.object(update_entry, 'recover', side_effect=OSError('recovered failure')), \
                    patch.object(update_entry.subprocess, 'Popen') as restart:
                code = update_entry.main(['--root', str(root), '--recover', '--parent-pid', '123',
                                          '--result', str(result), '--restart'])
            self.assertEqual(code, 1)
            restart.assert_called_once_with([str(root / 'TachiTalk.exe')], cwd=root)
