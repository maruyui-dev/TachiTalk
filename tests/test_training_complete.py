import asyncio
import base64
import json
import math
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory
import unittest
import wave
from unittest.mock import patch

from app.training.project import TRAINING_FILES, TrainingProject, TrainingOptions
from app.updates.download import Policy
from app.updates.install import apply_archive
from app.updates.cleanup import cleanup_committed
from app.updates.client import UpdateClient
from app.updates.manifest import canonical
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.test_updates import bundle

ROOT = Path(__file__).resolve().parents[1]
ASR = 'models/asr/large-v3-turbo.pt'
UVR = 'models/uvr/HP2_all_vocals.pth'


class CompleteTrainingTests(unittest.TestCase):
    def test_complete_resources_require_packaged_recognition_and_separation_weights(self):
        self.assertIn(ASR, TRAINING_FILES)
        self.assertIn(UVR, TRAINING_FILES)

    def test_training_manifest_and_parts_use_the_same_two_sources(self):
        source = {'name': '魔搭', 'layout': 'modelscope',
                  'prefix': 'https://modelscope.cn/models/MaruYui/TachiTalk-Voice-Runtime/resolve/master/'}
        base = 'https://github.com/maruyui-dev/TachiTalk/releases/'
        for tail, name in [('latest/download/training-manifest.json', 'training-manifest.json'),
                           ('download/v2.0.0/training-v2ProPlus-training-2.zip',
                            'training-v2ProPlus-training-2.zip'),
                           ('download/v2.0.0/training-v2ProPlus-training-2.zip.part000',
                            'training-v2ProPlus-training-2.zip.part000')]:
            with self.subTest(name=name):
                self.assertEqual(Policy().source_url(base + tail, source), source['prefix'] + name)
                self.assertEqual(Policy().source_url(base + tail, {'name': 'GitHub', 'prefix': ''}), base + tail)
                Policy().redirect(source['prefix'] + name, source['prefix'] + name)
        for name in ('training-evil.exe', 'training-v3.zip.part000', 'training-v2ProPlus-training-2.zip.part000/evil'):
            with self.assertRaises(ValueError):
                Policy().source_url(base + 'download/v2.0.0/' + name, source)

    def test_training_discovery_verifies_signatures_for_both_user_selected_sources(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            client = UpdateClient(root=root, data=root / 'data')
            key = Ed25519PrivateKey.generate()
            client.keys = {'fixture': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
            payload, _ = bundle('training', name='services/gpt_sovits/training/fixture.py', base='*')
            envelope = dict(key_id='fixture', payload=payload,
                signature=base64.b64encode(key.sign(canonical(payload))).decode())
            async def fetch(url, configured, **kwargs):
                self.assertTrue(url.endswith('/training-manifest.json'))
                self.assertEqual(len(configured), 1)
                self.assertEqual(configured[0]['name'], selected)
                body = json.dumps(envelope).encode()
                kwargs['validator'](body)
                return body
            for selected in ('GitHub', '魔搭'):
                with self.subTest(source=selected), patch('app.updates.client.fetch_small', fetch):
                    actual = asyncio.run(client.voice_manifest(component='training', selected_source=selected))
                    self.assertEqual(actual, envelope)
            envelope['signature'] = base64.b64encode(b'0' * 64).decode()
            with patch('app.updates.client.fetch_small', fetch), self.assertRaisesRegex(ValueError, '签名'):
                asyncio.run(client.voice_manifest(component='training', selected_source=selected))

    def test_repair_preserves_personally_modified_asr_weights(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'services/gpt_sovits/runtime/python.exe'
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b'owned fixture runtime')
            (root / 'release-version.json').write_text('{"version":"2.0.0"}')
            payload, data = bundle('training', name='services/gpt_sovits/training/' + ASR, base='*')
            archive = root / 'fixture.zip'
            archive.write_bytes(data)
            apply_archive(root, archive, payload)
            weight = root / payload['files'][0]['path']
            weight.write_bytes(b'personally modified recognition model')
            transaction = apply_archive(root, archive, payload)
            self.assertTrue(cleanup_committed(root)['complete'])
            saved = transaction / 'backup' / payload['files'][0]['path']
            self.assertTrue(saved.exists(), 'Repair discarded the modified ASR model')
            self.assertEqual(saved.read_bytes(), b'personally modified recognition model')

    def test_real_slicing_needs_no_whisper_model_and_keeps_source_and_annotation_history(self):
        from scripts.start_tts import service_environment
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'original.wav'
            rate = 16000
            audio = bytearray()
            for seconds, amplitude in [(4, 9000), (1.2, 0), (4, 9000)]:
                audio.extend(b''.join(struct.pack('<h', round(amplitude * math.sin(2 * math.pi * 220 * i / rate)))
                                      for i in range(round(rate * seconds))))
            with wave.open(str(source), 'wb') as stream:
                stream.setparams((1, 2, rate, 0, 'NONE', ''))
                stream.writeframes(audio)
            original = source.read_bytes()
            short = root / 'short.wav'
            with wave.open(str(short), 'wb') as stream:
                stream.setparams((1, 2, rate, 0, 'NONE', ''))
                stream.writeframes(audio[:rate * 2])
            project = TrainingProject.create(root / 'projects', '切分验证', 'ja')
            imported = project.import_audio([source, short])
            project.set_annotations([dict(row, text='此前的完整标注') for row in imported])
            ready = project.directory / 'features/ready.json'
            ready.parent.mkdir()
            ready.write_text('{}')
            job = project.directory / 'jobs/fixture'
            job.mkdir(parents=True)
            service = ROOT / 'services/gpt_sovits'
            request = dict(project=str(project.directory), service=str(service), task='preprocess',
                training=str(service / 'training'), operation='slice',
                options=vars(TrainingOptions(gpu='cpu')), language='ja')
            (job / 'request.json').write_text(json.dumps(request), encoding='utf-8')
            completed = subprocess.run([str(service / 'runtime/python.exe'), '-B',
                str(ROOT / 'scripts/training_worker.py'), '--request', str(job / 'request.json')],
                cwd=ROOT, env=service_environment(service), capture_output=True, timeout=120)
            result = json.loads((job / 'result.json').read_text(encoding='utf-8'))
            self.assertTrue(result['ok'], result)
            self.assertEqual(completed.returncode, 0)
            after = TrainingProject(project.directory)
            self.assertGreaterEqual(len(after.state['annotations']), 3)
            self.assertTrue(all(not r['text'] for r in after.state['annotations']))
            self.assertFalse(ready.exists())
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(len(list((project.directory / 'annotation-history').glob('*.json'))), 1)


class CompletePreprocessUITests(unittest.TestCase):
    def test_dialog_selects_operation_and_bundled_models_without_file_picker(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox
        from app.ui.control_panel import load_window
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        panel = load_window()
        self.addCleanup(panel.close)
        failures = []
        def accept():
            dialog = app.activeModalWidget()
            try:
                mode = dialog.findChild(QComboBox, 'preprocessOperationCombo')
                self.assertIsNotNone(mode, 'The dialog still requires a manually selected Whisper .pt')
                self.assertEqual(mode.count(), 4)
                mode.setCurrentIndex(mode.findData('slice'))
                dialog.findChild(QDoubleSpinBox, 'preprocessMaxLength').setValue(12)
                dialog.accept()
            except Exception as error:
                failures.append(str(error))
                dialog.reject()
        QTimer.singleShot(0, accept)
        with patch.object(panel.training_page, 'run') as start:
            panel.training_page.preprocess()
            self.assertEqual(failures, [])
            self.assertEqual(start.call_args.args, ('preprocess',))
            self.assertEqual(start.call_args.kwargs['operation'], 'slice')
            self.assertEqual(start.call_args.kwargs['slicing']['max_length'], 12)
            self.assertNotIn('whisper_model', start.call_args.kwargs)
