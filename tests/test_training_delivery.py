import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from app.updates.install import apply_archive, version_path, uninstall_component
from app.updates.manifest import allowed_path, validate
from app.updates.cleanup import cleanup_committed
from scripts.component_release import training_entries
from tests.test_updates import bundle


class TrainingDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        runtime = self.root / 'services/gpt_sovits/runtime/python.exe'
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b'existing runtime sentinel')
        (self.root / 'release-version.json').write_text('{"version":"2.0.0"}')
        self.voice_record = self.root / 'services/gpt_sovits/component-version.json'
        self.voice_record.write_text('{"version":"stable-voice"}')
        self.payload, data = bundle('training', name='services/gpt_sovits/training/fixture.py', base='*')
        self.archive = self.root / 'fixture.zip'
        self.archive.write_bytes(data)

    def test_training_extension_cannot_replace_runtime_user_data_or_other_component_record(self):
        for path in ['services/gpt_sovits/runtime/torch.dll', 'services/gpt_sovits/component-version.json',
                     'user_data/training/my-voice.pth', 'services/gpt_sovits/training/component-version.json']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                allowed_path('training', path)
        self.assertEqual(validate(self.payload)['component'], 'training')
        with self.assertRaises(ValueError):
            allowed_path('voice', 'services/gpt_sovits/training/fixture.py')

    def test_repair_keeps_a_personally_modified_training_base_checkpoint_backup(self):
        payload, data = bundle('training', name='services/gpt_sovits/training/GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth', base='*')
        self.archive.write_bytes(data)
        apply_archive(self.root, self.archive, payload)
        path = self.root / payload['files'][0]['path']
        path.write_bytes(b'personally modified training base')
        transaction = apply_archive(self.root, self.archive, payload)
        result = cleanup_committed(self.root)
        self.assertTrue(result['complete'])
        backup = transaction / 'backup' / payload['files'][0]['path']
        self.assertTrue(backup.is_file(), 'Repair discarded a locally modified checkpoint')
        self.assertEqual(backup.read_bytes(), b'personally modified training base')

    def test_extension_can_reuse_an_external_legacy_runtime_without_copying_it(self):
        other = TemporaryDirectory()
        self.addCleanup(other.cleanup)
        legacy = Path(other.name).resolve()
        runtime = legacy / 'services/gpt_sovits/runtime/python.exe'
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b'legacy runtime sentinel')
        (self.root / 'services/gpt_sovits/runtime/python.exe').unlink()
        selection = self.root / 'user_data/settings/voice_location.json'
        selection.parent.mkdir(parents=True)
        selection.write_text(json.dumps({'installation': str(legacy)}))
        apply_archive(self.root, self.archive, self.payload)
        self.assertEqual(runtime.read_bytes(), b'legacy runtime sentinel')
        self.assertFalse((self.root / 'services/gpt_sovits/runtime/python.exe').exists())
        self.assertTrue((self.root / self.payload['files'][0]['path']).exists())

    def test_extension_installs_independently_without_overwriting_voice_record(self):
        before = self.voice_record.read_bytes()
        apply_archive(self.root, self.archive, self.payload)
        self.assertEqual(self.voice_record.read_bytes(), before)
        record = json.loads((self.root / version_path('training')).read_text())
        self.assertEqual(record['version'], self.payload['version'])
        self.assertEqual((self.root / 'services/gpt_sovits/runtime/python.exe').read_bytes(), b'existing runtime sentinel')

    def test_failed_extension_rolls_back_and_keeps_existing_voice_usable(self):
        path = self.root / self.payload['files'][0]['path']
        path.parent.mkdir(parents=True)
        path.write_bytes(b'old training code')
        def fail(*_args):
            raise OSError('fixture interrupted')
        with self.assertRaises(OSError):
            apply_archive(self.root, self.archive, self.payload, fault=fail)
        self.assertEqual(path.read_bytes(), b'old training code')
        self.assertTrue(self.voice_record.is_file())
        self.assertFalse((self.root / '.tachitalk-pending.json').exists())

    def test_uninstall_training_preserves_runtime_projects_and_modified_weights(self):
        apply_archive(self.root, self.archive, self.payload)
        private = self.root / 'user_data/training/projects/my-model.pth'
        private.parent.mkdir(parents=True)
        private.write_bytes(b'user trained model')
        uninstall_component(self.root, 'training')
        self.assertFalse((self.root / self.payload['files'][0]['path']).exists())
        self.assertTrue(self.voice_record.is_file())
        self.assertEqual(private.read_bytes(), b'user trained model')

    def test_training_package_contains_only_v2proplus_bases_and_never_runtime_or_user_outputs(self):
        root = Path(__file__).resolve().parents[1]
        names = [relative.as_posix() for _source, relative in training_entries(root)]
        checkpoints = [Path(n).name for n in names if '/GPT_SoVITS/pretrained_models/' in n and n.endswith(('.pth', '.ckpt'))]
        self.assertEqual(set(checkpoints), {'s1v3.ckpt', 's2Gv2ProPlus.pth', 's2Dv2ProPlus.pth'})
        self.assertTrue(all(n.startswith('services/gpt_sovits/training/') for n in names))
        self.assertFalse(any('/runtime/' in n or '/user_data/' in n for n in names))
        self.assertTrue(any(n.endswith('/models/asr/large-v3-turbo.pt') for n in names))
        self.assertTrue(any(n.endswith('/models/uvr/HP2_all_vocals.pth') for n in names))
