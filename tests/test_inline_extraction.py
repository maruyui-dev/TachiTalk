"""Install hashes ZIP output in memory, without a second stage-file hash pass."""
import hashlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from app.updates.install import apply_archive
from app.updates.manifest import sha256
from tests.test_updates import bundle


class InlineExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'TachiTalk.exe').write_bytes(b'old executable')
        self.archive = self.root / 'fixture.zip'
        self.payload, data = bundle()
        self.archive.write_bytes(data)

    def test_valid_install_has_no_separate_verification_phase_or_stage_hash_read(self):
        events, hashed = [], []
        def observe_hash(path, progress=None):
            hashed.append(Path(path))
            return sha256(path, progress)
        with patch('app.updates.install.sha256', side_effect=observe_hash):
            apply_archive(self.root, self.archive, self.payload,
                          progress=lambda phase, *a, **k: events.append(phase))
        self.assertEqual(set(events), {'prepare', 'install'}, 'Install still has avoidable standalone phases')
        self.assertTrue(all('stage' not in p.parts for p in hashed),
                        'Staged files were reopened for a second full hash pass')
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'new executable')

    def test_same_size_wrong_hash_never_replaces_the_original_file(self):
        self.payload['files'][0]['sha256'] = '0' * 64
        events = []
        with self.assertRaisesRegex(ValueError, '哈希'):
            apply_archive(self.root, self.archive, self.payload,
                          progress=lambda phase, *a, **k: events.append(phase))
        self.assertNotIn('backup', events)
        self.assertNotIn('replace', events)
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'old executable')
        self.assertFalse((self.root / '.tachitalk-pending.json').exists())

    def test_staged_payload_is_promoted_without_copying_the_whole_file_again(self):
        import shutil
        copy = shutil.copyfile
        def reject_stage_copy(source, destination, **kwargs):
            if 'stage' in Path(source).parts:
                self.fail('Staged data was copied instead of moved into its final location')
            return copy(source, destination, **kwargs)
        with patch('app.updates.install.shutil.copyfile', side_effect=reject_stage_copy):
            transaction = apply_archive(self.root, self.archive, self.payload)
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'new executable')
        self.assertFalse(any(p.is_file() for p in (transaction / 'stage').rglob('*')))

    def test_link_unavailable_still_preserves_real_rollback(self):
        def fail(*args):
            raise OSError('fixture install interrupted')
        with patch('app.updates.install.os.link', side_effect=OSError('fixture filesystem has no hard links')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                apply_archive(self.root, self.archive, self.payload, fault=fail)
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'old executable')
        self.assertFalse((self.root / '.tachitalk-pending.json').exists())

    def test_existing_vendor_file_uses_link_snapshot_and_new_file_has_own_identity(self):
        original_id = (self.root / 'TachiTalk.exe').stat().st_ino
        transaction = apply_archive(self.root, self.archive, self.payload)
        saved = transaction / 'backup/TachiTalk.exe'
        self.assertEqual(saved.stat().st_ino, original_id)
        self.assertNotEqual((self.root / 'TachiTalk.exe').stat().st_ino, original_id)
        self.assertEqual(saved.read_bytes(), b'old executable')

    def test_empty_and_multi_block_files_keep_exact_content_and_extraction_totals(self):
        files = {'_internal/empty.bin': b'', '_internal/blocks.bin': b'abcde' * 500000}
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)
        archive_data = output.getvalue()
        self.archive.write_bytes(archive_data)
        self.payload['files'] = [dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
                                 for name, data in files.items()]
        artifact = dict(size=len(archive_data), sha256=hashlib.sha256(archive_data).hexdigest())
        self.payload['archive'] = artifact
        self.payload['parts'][0].update(artifact)
        progress = []
        apply_archive(self.root, self.archive, self.payload,
                      progress=lambda phase, *a, **k: progress.append((phase, a, k)))
        for name, data in files.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        extraction = [event for event in progress if event[0] == 'install']
        self.assertEqual(extraction[-1][1][0], extraction[-1][1][1])
        self.assertGreater(extraction[-1][1][0], sum(map(len, files.values())), 'Final metadata is installed too')
        self.assertNotIn('verify', [event[0] for event in progress])
