import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from app.core.audio_library import AudioLibrary, inspect_audio


class AudioLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'voice.wav'
        self.wav(self.source)
        self.library = AudioLibrary(self.root / 'state.json', {'平常': (str(self.source), 'こんにちは。')})

    @staticmethod
    def wav(path, seconds=4):
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, 32000, 0, 'NONE', ''))
            stream.writeframes(b'\0\0' * (32000 * seconds))

    def test_rename_publish_and_restart_preserve_id_and_old_snapshot(self):
        old = self.library.snapshot()
        ref = old.resolve('平常')
        self.library.update(ref.key, name='温柔', scene='安慰', prompt='こんにちは。', enabled=True, default=True)
        self.assertEqual(self.library.snapshot().names, ('温柔',))
        self.assertEqual(old.resolve('平常').name, '平常')
        self.assertEqual(AudioLibrary(self.root / 'state.json').snapshot().resolve('温柔').key, ref.key)

    def test_replace_remove_leave_inflight_file_and_default_is_valid(self):
        ref = self.library.snapshot().resolve('平常')
        imported = self.library.add(self.source)
        self.library.update(imported.key, name='开心', scene='', prompt='いいですね。', enabled=True, default=True)
        before = self.library.snapshot()
        self.library.replace(imported.key, self.source)
        self.assertNotEqual(before.resolve('开心').path, self.library.snapshot().resolve('开心').path)
        self.assertTrue(Path(before.resolve('开心').path).is_file())
        self.library.remove(imported.key)
        self.assertEqual(self.library.snapshot().default.name, ref.name)

    def test_duplicate_disabled_and_missing_references_not_offered(self):
        imported = self.library.add(self.source)
        with self.assertRaises(ValueError):
            self.library.update(imported.key, name='平常', scene='', prompt='a', enabled=True, default=False)
        self.assertEqual(self.library.snapshot().names, ('平常',))
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, '可用'):
            self.library.snapshot()

    def test_failed_save_does_not_publish(self):
        before = self.library.snapshot()
        with patch('app.core.audio_library.save_resource_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.library.update(before.default.key, name='修改', scene='', prompt='a', enabled=True, default=True)
        self.assertEqual(self.library.snapshot(), before)

    def test_pack_selection_and_removal_are_independent(self):
        key = self.library.create_pack('另一个角色')
        self.library.add(self.source)
        with self.assertRaises(ValueError):
            self.library.snapshot()
        self.library.select_pack('default')
        self.assertEqual(self.library.snapshot().names, ('平常',))
        self.library.select_pack(key)
        self.library.remove_pack()
        self.assertEqual(self.library.active_id, 'default')

    def test_invalid_and_truncated_audio_rejected(self):
        self.wav(self.source, 1)
        with self.assertRaises(ValueError):
            inspect_audio(self.source)
        self.wav(self.source)
        self.source.write_bytes(self.source.read_bytes()[:100])
        with self.assertRaises(ValueError):
            inspect_audio(self.source)

    def test_pack_export_import_preserves_names_transcripts_and_default(self):
        self.library.export_pack(self.root / 'export')
        self.library.import_pack(self.root / 'export')
        snapshot = self.library.snapshot()
        self.assertEqual(snapshot.names, ('平常',))
        self.assertEqual(snapshot.default.prompt, 'こんにちは。')

    def test_corrupt_config_is_preserved_and_cannot_be_overwritten(self):
        path = self.root / 'broken.json'
        path.write_text('{broken', encoding='utf-8')
        library = AudioLibrary(path, {'平常': (str(self.source), 'こんにちは。')})
        self.assertTrue(library.read_only)
        with self.assertRaises(ValueError):
            library.select_pack('default')
        self.assertEqual(path.read_text(encoding='utf-8'), '{broken')

    def test_backup_reference_ids_cannot_escape_export_directory(self):
        from copy import deepcopy
        data = deepcopy(self.library.state)
        data['packs']['default']['references'][0]['key'] = '../outside'
        data['packs']['default']['default'] = '../outside'
        with self.assertRaises(ValueError):
            AudioLibrary.validate(data)

    def test_builtin_ids_are_stable_before_first_library_save(self):
        seeds = {'平常': (str(self.source), 'こんにちは。')}
        second = AudioLibrary(self.root / 'state.json', seeds)
        self.assertEqual(self.library.snapshot().default.key, second.snapshot().default.key)
