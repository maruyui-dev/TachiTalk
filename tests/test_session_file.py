from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSaveFile
from app.core.session_file import SessionFile


class SessionFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = SessionFile(Path(self.temp.name) / 'settings' / 'last_session.dat')

    def test_roundtrip_encrypts_unicode_and_keys_with_current_windows_user(self):
        data = {'title': '茉子', 'api_key': 'sk-test-session-000000', 'volume': 37}
        self.assertIsNone(self.file.read())
        self.file.write(data)
        self.assertEqual(self.file.read(), data)
        raw = self.file.path.read_bytes()
        self.assertNotIn(data['api_key'].encode(), raw)
        self.assertNotIn('茉子'.encode(), raw)

    def test_failed_commit_preserves_last_good_file(self):
        self.file.write({'value': 1})
        before = self.file.path.read_bytes()
        with patch.object(QSaveFile, 'commit', return_value=False):
            with self.assertRaises(OSError):
                self.file.write({'value': 2})
        self.assertEqual(self.file.path.read_bytes(), before)
        self.assertEqual(self.file.read(), {'value': 1})

    def test_corrupted_or_oversized_files_are_rejected(self):
        self.file.write({'value': 1})
        raw = bytearray(self.file.path.read_bytes())
        raw[-20] ^= 1
        self.file.path.write_bytes(raw)
        with self.assertRaises((OSError, ValueError)):
            self.file.read()
        with self.assertRaises(ValueError):
            self.file.write({'value': 'x' * (8 * 1024 * 1024)})
