import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.training.project import TrainingOptions, TrainingProject, training_status
from app.training.project import training_location
import shutil
from scripts.training_worker import make_configs
from app.training.project import apply_voice
from app.core.audio_library import AudioLibrary
from unittest.mock import patch
import wave


class TrainingBusinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = TrainingProject.create(self.root / 'projects', '我的声音', 'ja')

    def test_import_preserves_original_and_rejects_escape_in_annotation(self):
        source = self.root / 'source.wav'
        source.write_bytes(b'original audio')
        row = self.project.import_audio([source])[0]
        self.project.owned(row['audio']).write_bytes(b'owned copy')
        self.assertEqual(source.read_bytes(), b'original audio')
        with self.assertRaisesRegex(ValueError, '越界'):
            self.project.set_annotations([dict(row, audio='../source.wav')])

    def test_incomplete_or_invalid_annotations_cannot_train(self):
        source = self.root / 'source.wav'
        source.write_bytes(b'fixture')
        row = self.project.import_audio([source])[0]
        with self.assertRaisesRegex(ValueError, '标注'):
            self.project.write_filelist()
        with self.assertRaises(ValueError):
            self.project.set_annotations([dict(row, text='a|b')])
        self.project.set_annotations([dict(row, text='こんにちは')])
        self.assertIn('|speaker|ja|こんにちは', self.project.write_filelist().read_text(encoding='utf-8'))
        self.assertEqual(TrainingProject(self.project.directory).state['annotations'][0]['text'], 'こんにちは')

    def test_models_are_project_owned_and_both_stages_are_required(self):
        models = self.project.directory / 'models'
        models.mkdir()
        (models / 'voice.pth').write_bytes(b'sovits fixture')
        self.project.refresh_models()
        with self.assertRaises(ValueError):
            self.project.model_pair()
        (models / 'voice.ckpt').write_bytes(b'gpt fixture')
        self.project.refresh_models()
        self.assertEqual(set(self.project.model_pair()), {'gpt', 'sovits'})
        self.project.state['models']['gpt'] = '../../outside.ckpt'
        with self.assertRaises(ValueError):
            self.project.model_pair()

    def test_no_alternative_version_is_accepted(self):
        for version in ('v1', 'v2', 'v3', 'v4', 'v2Pro'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                TrainingOptions(version=version).validate()
        self.assertEqual(training_status(self.root)['version'], 'v2ProPlus')
        self.assertFalse(training_status(self.root)['installed'])

    def test_training_additions_can_live_in_current_app_while_runtime_is_external(self):
        service = self.root / 'old-install/services/gpt_sovits'
        app = self.root / 'new-app'
        self.assertEqual(training_location(service, app), service / 'training')
        local = app / 'services/gpt_sovits/training'
        (local / 'GPT_SoVITS/configs').mkdir(parents=True)
        self.assertEqual(training_location(service, app), local)
        original = Path(__file__).resolve().parents[1] / 'services/gpt_sovits/training/GPT_SoVITS/configs'
        for name in ('s1longer-v2.json', 's2v2ProPlus.json'):
            shutil.copy2(original / name, local / 'GPT_SoVITS/configs' / name)
        s2, s1 = make_configs(service, self.project.directory, vars(TrainingOptions()), local)
        self.assertTrue(Path(s2['train']['pretrained_s2G']).is_relative_to(local))
        self.assertTrue(Path(s1['pretrained_s1']).is_relative_to(local))

    def test_editing_annotations_invalidates_features_but_reexporting_does_not(self):
        source = self.root / 'source.wav'
        source.write_bytes(b'audio fixture')
        row = self.project.import_audio([source])[0]
        self.project.set_annotations([dict(row, text='hello')])
        marker = self.project.directory / 'features/ready.json'
        marker.parent.mkdir()
        marker.write_text('{}')
        self.project.write_filelist()
        self.assertTrue(marker.exists())
        self.project.set_annotations([dict(row, text='changed')])
        self.assertFalse(marker.exists())

    def test_apply_adds_trained_reference_and_rolls_back_audio_settings_on_model_write_failure(self):
        source = self.root / 'reference.wav'
        with wave.open(str(source), 'wb') as stream:
            stream.setparams((1, 2, 32000, 0, 'NONE', ''))
            stream.writeframes(b'\0\0' * 32000 * 4)
        library = AudioLibrary(self.root / 'audio.json', {'平常': (str(source), 'こんにちは。')})
        models = self.project.directory / 'models'
        models.mkdir()
        (models / 'voice.ckpt').write_bytes(b'gpt fixture')
        (models / 'voice.pth').write_bytes(b'sovits fixture')
        self.project.refresh_models()
        previous = library.snapshot()
        with patch('app.training.project.save_resource_json', side_effect=OSError('fixture readonly model settings')):
            with self.assertRaises(OSError):
                apply_voice(self.project, self.root, library, source, '你好。', 'zh')
        self.assertEqual(library.snapshot(), previous)
        apply_voice(self.project, self.root, library, source, '你好。', 'zh')
        self.assertEqual(library.snapshot().default.language, 'zh')
        self.assertIn(previous.default, library.snapshot().references)
        selected = json.loads((self.root / 'settings/active_voice_model.json').read_text(encoding='utf-8'))
        self.assertEqual(selected['version'], 'v2ProPlus')

    def test_generated_configs_reuse_environment_and_write_only_project_outputs(self):
        service = Path(__file__).resolve().parents[1] / 'services/gpt_sovits'
        s2, s1 = make_configs(service, self.project.directory, vars(TrainingOptions(gpu='cpu')))
        self.assertEqual(s2['model']['version'], 'v2ProPlus')
        self.assertFalse(s2['train']['fp16_run'])
        self.assertTrue(s2['train']['grad_ckpt'])
        self.assertEqual(s2['save_weight_dir'], str(self.project.directory / 'models'))
        self.assertEqual(s1['train']['half_weights_save_dir'], s2['save_weight_dir'])
        self.assertTrue(s2['train']['pretrained_s2D'].endswith('s2Dv2ProPlus.pth'))
        saved = json.loads((self.project.directory / 's1.json').read_text())
        self.assertEqual(saved['train']['precision'], '32')
        self.assertIsInstance(saved['optimizer']['lr_init'], float)
        self.assertTrue((self.project.directory / 'features/logs_s2_v2ProPlus').is_dir(),
                        'The upstream trainer requires its checkpoint directory to exist before saving')
