"""Updater cleanup behavior using tiny isolated archives, never desktop data."""
import json
import ctypes
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.updates.install import apply_archive
from app.updates.cleanup import needs_cleanup
from app.updates.manifest import atomic_json
from scripts import update_entry
from tests.test_updates import bundle


class CleanupLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='tachitalk-cleanup-lifecycle-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.root = self.directory / 'installation'
        self.root.mkdir()
        (self.root / 'TachiTalk.exe').write_bytes(b'fixture - never executed')
        atomic_json(self.root / 'release-version.json', {'version': '2.0.0'})
        self.name = 'services/gpt_sovits/runtime/fixture.dll'
        self.voice = self.root / self.name
        self.voice.parent.mkdir(parents=True)
        self.voice.write_bytes(b'original voice runtime')
        self.payload, self.data = bundle(component='voice', data=b'new voice runtime',
                                         base='*', name=self.name)
        self.updates = self.root / 'user_data/updates'
        self.result = self.updates / 'install-result.json'
        self.cache = self.updates / 'downloads' / self.payload['archive']['sha256']
        self.cache.mkdir(parents=True)
        self.archive = self.cache / 'package.zip'
        self.archive.write_bytes(self.data)
        (self.cache / '0000.bin').write_bytes(self.data)
        self.manifest = self.cache / 'manifest.json'
        self.envelope = {'payload': self.payload, 'key_id': 'offline fixture'}
        atomic_json(self.manifest, self.envelope)
        atomic_json(self.cache / 'source-lock.json', {'source': 'offline fixture'})
        self.other = self.updates / 'downloads' / ('f' * 64) / '0000.bin.part'
        self.other.parent.mkdir(parents=True)
        self.other.write_bytes(b'other resumable task')
        self.personal = {
            'user_data/settings/preferences.json': b'{"fixture":"settings"}',
            'user_data/memory/conversation.dat': b'fixture encrypted conversation',
            'assets/custom-character.png': b'fixture user portrait',
            'services/gpt_sovits/user-trained-model.pth': b'fixture user training output',
            'assets/audio/source-user.wav': b'fixture local source audio',
        }
        for name, data in self.personal.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def invoke(self, *, archive=None, manifest=None, recover=False):
        args = ['--root', str(self.root), '--result', str(self.result)]
        if recover:
            args.append('--recover')
        else:
            args += ['--archive', str(archive or self.archive),
                     '--manifest', str(manifest or self.manifest)]
        # The signature boundary is stubbed; payload validation, hashing,
        # extraction, replacement, backup and recovery remain real operations.
        with patch.object(update_entry, 'load_signed', return_value=(self.envelope, self.payload)):
            return update_entry.main(args)

    def assert_personal_data_unchanged(self):
        for name, data in self.personal.items():
            self.assertEqual((self.root / name).read_bytes(), data, name)
        self.assertEqual(self.other.read_bytes(), b'other resumable task')

    def test_success_removes_only_its_download_and_committed_transaction_materials(self):
        self.assertEqual(self.invoke(), 0)
        self.assertTrue(json.loads(self.result.read_text(encoding='utf-8'))['ok'])
        self.assertEqual(self.voice.read_bytes(), b'new voice runtime')
        self.assert_personal_data_unchanged()
        for name in ('package.zip', '0000.bin', 'manifest.json', 'source-lock.json'):
            with self.subTest(material=name):
                self.assertFalse((self.cache / name).exists(), 'Completed download material remains')
        for name in ('stage', 'backup'):
            with self.subTest(material=name):
                self.assertEqual(list((self.root / '.tachitalk-transactions').glob('*/' + name)), [],
                                 'Committed installation material remains')

    def test_cleanup_keeps_extra_user_file_inside_cache_and_other_download_task(self):
        extra = self.cache / 'user-note.txt'
        extra.write_bytes(b'personal note - never part of the download job')
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(extra.read_bytes(), b'personal note - never part of the download job')
        self.assert_personal_data_unchanged()
        self.assertFalse(self.archive.exists(), 'Managed archive must be cleaned without deleting extra user content')
        self.assertFalse((self.cache / '0000.bin').exists())

    def test_external_offline_archive_is_preserved_when_transaction_materials_are_cleaned(self):
        external = self.directory / 'my offline package.zip'
        external.write_bytes(self.data)
        external_manifest = self.directory / 'my offline manifest.json'
        atomic_json(external_manifest, self.envelope)
        manifest_bytes = external_manifest.read_bytes()
        self.assertEqual(self.invoke(archive=external, manifest=external_manifest), 0)
        self.assertEqual(external.read_bytes(), self.data)
        self.assertEqual(external_manifest.read_bytes(), manifest_bytes)
        self.assertEqual(self.voice.read_bytes(), b'new voice runtime')
        self.assert_personal_data_unchanged()
        self.assertEqual(list((self.root / '.tachitalk-transactions').glob('*/stage')), [],
                         'An external offline source must still get automatic staging cleanup')

    def test_replacement_failure_preserves_download_backup_and_personal_files(self):
        def fail_after_replacement(*args):
            raise OSError('fixture replacement failure')

        def apply_with_fault(*args, **kwargs):
            return apply_archive(*args, fault=fail_after_replacement, **kwargs)

        with patch.object(update_entry, 'apply_archive', side_effect=apply_with_fault):
            self.assertEqual(self.invoke(), 1)
        self.assertFalse(json.loads(self.result.read_text(encoding='utf-8'))['ok'])
        self.assertEqual(self.voice.read_bytes(), b'original voice runtime')
        self.assertEqual(self.archive.read_bytes(), self.data)
        self.assertEqual((self.cache / '0000.bin').read_bytes(), self.data)
        backups = list((self.root / '.tachitalk-transactions').glob('*/backup/' + self.name))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'original voice runtime')
        self.assert_personal_data_unchanged()

    def test_invalid_archive_preserves_repair_materials(self):
        self.archive.write_bytes(b'corrupt archive fixture')
        self.assertEqual(self.invoke(), 1)
        self.assertFalse(json.loads(self.result.read_text(encoding='utf-8'))['ok'])
        self.assertEqual(self.voice.read_bytes(), b'original voice runtime')
        self.assertEqual(self.archive.read_bytes(), b'corrupt archive fixture')
        self.assertEqual((self.cache / '0000.bin').read_bytes(), self.data)
        self.assert_personal_data_unchanged()

    def test_failed_recovery_preserves_journal_backup_and_download_materials(self):
        backup = self.root / '.tachitalk-transactions/failed-fixture/backup'
        saved = backup / self.name
        saved.parent.mkdir(parents=True)
        saved.write_bytes(b'corrupt saved fixture')
        pending = self.root / '.tachitalk-pending.json'
        atomic_json(pending, {'component': 'voice', 'state': 'applying',
                             'backup': backup.relative_to(self.root).as_posix(),
                             'operations': [{'path': self.name, 'existed': True, 'sha256': '0' * 64}]})
        original_pending = pending.read_bytes()
        self.assertEqual(self.invoke(recover=True), 1)
        self.assertFalse(json.loads(self.result.read_text(encoding='utf-8'))['ok'])
        self.assertEqual(pending.read_bytes(), original_pending)
        self.assertEqual(saved.read_bytes(), b'corrupt saved fixture')
        self.assertEqual(self.archive.read_bytes(), self.data)
        self.assertEqual(self.voice.read_bytes(), b'original voice runtime')
        self.assert_personal_data_unchanged()

    def test_recovery_finishes_cleanup_after_committed_install_without_rolling_back(self):
        # Stop after the real file transaction, before the updater's cleanup:
        # this represents a process exiting between commit and housekeeping.
        transaction = apply_archive(self.root, self.archive, self.payload)
        self.assertEqual(self.voice.read_bytes(), b'new voice runtime')
        self.assertTrue((transaction / 'stage').is_dir())
        self.assertTrue((transaction / 'backup').is_dir())
        self.assertFalse((self.root / '.tachitalk-pending.json').exists())
        self.assertTrue(needs_cleanup(self.root), 'Committed cleanup must survive a process exit')
        self.assertEqual(self.invoke(recover=True), 0)
        result = json.loads(self.result.read_text(encoding='utf-8'))
        self.assertTrue(result['ok'])
        self.assertTrue(result.get('cleanup', {}).get('complete'), 'Recovery did not finish committed cleanup')
        self.assertEqual(self.voice.read_bytes(), b'new voice runtime', 'Committed files must not be rolled back')
        self.assertFalse((transaction / 'stage').exists())
        self.assertFalse((transaction / 'backup').exists())
        self.assertFalse(self.archive.exists())
        self.assertFalse(needs_cleanup(self.root))
        self.assert_personal_data_unchanged()

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing modes')
    def test_occupied_archive_reports_cleanup_warning_then_retries_without_restart_loop(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.HANDLE)
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        # Real read handle permits the installer's reads and writes but omits
        # FILE_SHARE_DELETE, so cleanup must encounter a genuine Windows error.
        handle = kernel.CreateFileW(str(self.archive), 0x80000000, 0x1 | 0x2,
                                    None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value,
                            f'Failed to open fixture handle: {ctypes.get_last_error()}')
        try:
            self.assertEqual(self.invoke(), 0, 'Cleanup failure must not invalidate a successful install')
            result = json.loads(self.result.read_text(encoding='utf-8'))
            self.assertTrue(result['ok'])
            cleanup = result.get('cleanup')
            self.assertIsInstance(cleanup, dict, 'Result must explain incomplete cleanup')
            self.assertIs(cleanup.get('complete'), False)
            self.assertTrue(cleanup.get('errors'), 'Windows cleanup error must remain diagnosable')
            self.assertTrue(self.archive.exists())
            self.assertEqual(self.voice.read_bytes(), b'new voice runtime')
            self.assertFalse(needs_cleanup(self.root), 'Known IO failure must not create a restart/recovery loop')
        finally:
            kernel.CloseHandle(handle)
        self.assertEqual(self.invoke(recover=True), 0)
        result = json.loads(self.result.read_text(encoding='utf-8'))
        self.assertTrue(result['ok'])
        self.assertTrue(result.get('cleanup', {}).get('complete'), 'Released file should clean on explicit retry')
        self.assertFalse(self.archive.exists())
        self.assertFalse(needs_cleanup(self.root))
        self.assertEqual(self.voice.read_bytes(), b'new voice runtime')
        self.assert_personal_data_unchanged()


if __name__ == '__main__':
    unittest.main()
