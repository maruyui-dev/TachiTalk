"""Cleanup boundary guards use only isolated, tiny files."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from app.updates.cleanup import cleanup_committed, cleanup_updater_copies, needs_cleanup
from app.updates.install import apply_archive
from tests.test_updates import bundle


class CleanupGuardTests(unittest.TestCase):
    def test_startup_routes_interrupted_committed_cleanup_to_independent_updater(self):
        import sys
        from app import bootstrap
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'TachiTalk.exe').write_bytes(b'old')
            payload, data = bundle()
            archive = root / 'offline.zip'
            archive.write_bytes(data)
            transaction = apply_archive(root, archive, payload)
            self.assertFalse((root / '.tachitalk-pending.json').exists())
            self.assertTrue(needs_cleanup(root))
            with patch('app.paths.PROJECT_ROOT', root), patch('app.paths.DATA_ROOT', root / 'user_data'), \
                 patch.object(sys, 'frozen', False, create=True), patch('subprocess.Popen') as launch:
                self.assertEqual(bootstrap.main(), 0)
            command = launch.call_args.args[0]
            self.assertIn('--recover', command)
            self.assertIn('--show-progress', command)
            self.assertTrue((transaction / 'cleanup.json').exists(), 'Parent must leave cleanup to independent updater')

    def test_locally_modified_default_voice_model_backup_is_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'TachiTalk.exe').write_bytes(b'fixture')
            (root / 'release-version.json').write_text('{"version":"2.0.0"}')
            name = 'services/gpt_sovits/GPT_weights_v2ProPlus/default.ckpt'
            payload, data = bundle(component='voice', name=name, base='*')
            archive = root / 'offline.zip'
            archive.write_bytes(data)
            first = apply_archive(root, archive, payload)
            self.assertTrue(cleanup_committed(root)['complete'])
            self.assertFalse(first.exists())
            (root / name).write_bytes(b'personally trained replacement')
            transaction = apply_archive(root, archive, payload)
            result = cleanup_committed(root)
            self.assertTrue(result['complete'])
            self.assertEqual((transaction / 'backup' / name).read_bytes(), b'personally trained replacement')
            self.assertFalse((transaction / 'stage').exists())
            self.assertFalse((transaction / 'cleanup.json').exists())
            self.assertTrue(result['preserved'])

    def test_marker_cannot_redirect_cleanup_to_personal_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'TachiTalk.exe').write_bytes(b'old')
            payload, data = bundle()
            archive = root / 'offline.zip'
            archive.write_bytes(data)
            transaction = apply_archive(root, archive, payload)
            private = root / 'assets/personal.wav'
            private.parent.mkdir()
            private.write_bytes(b'keep personal voice')
            marker = transaction / 'cleanup.json'
            job = json.loads(marker.read_text())
            job['cache'] = {'profile': '../assets', 'sha256': payload['archive']['sha256'], 'parts': 1}
            marker.write_text(json.dumps(job), encoding='utf-8')
            result = cleanup_committed(root)
            self.assertFalse(result['complete'])
            self.assertEqual(private.read_bytes(), b'keep personal voice')
            self.assertEqual((transaction / 'backup/TachiTalk.exe').read_bytes(), b'old')
            self.assertFalse(needs_cleanup(root), 'Invalid cleanup must not create a restart loop')

    @unittest.skipUnless(os.name == 'nt', 'Windows directory junction')
    def test_transaction_junction_does_not_remove_external_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'TachiTalk.exe').write_bytes(b'old')
            payload, data = bundle()
            archive = root / 'offline.zip'
            archive.write_bytes(data)
            transaction = apply_archive(root, archive, payload)
            outside = root / 'personal'
            outside.mkdir()
            (outside / 'keep.pth').write_bytes(b'user trained model')
            link = transaction / 'stage/linked'
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                           cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True)
            result = cleanup_committed(root)
            self.assertFalse(result['complete'])
            self.assertEqual((outside / 'keep.pth').read_bytes(), b'user trained model')
            self.assertTrue((transaction / 'backup/TachiTalk.exe').exists())

    def test_old_updater_copies_retire_without_touching_new_handoff_or_user_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            data = root / 'user_data'
            copies = data / 'updates/updaters'
            copies.mkdir(parents=True)
            old = copies / ('a' * 32 + '.exe')
            old.write_bytes(b'old helper')
            user = copies / 'personal.exe'
            user.write_bytes(b'user file')
            started_at = time.time()
            time.sleep(.02)
            new = copies / ('b' * 32 + '.exe')
            new.write_bytes(b'new handoff')
            self.assertEqual(cleanup_updater_copies(root, data, started_at), 1)
            self.assertFalse(old.exists())
            self.assertEqual(new.read_bytes(), b'new handoff')
            self.assertEqual(user.read_bytes(), b'user file')
