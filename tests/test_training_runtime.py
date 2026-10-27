import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import importlib.util
from unittest.mock import patch
from unittest.mock import AsyncMock

from app.services.local_tts import LocalTTSService
from app.core.voice_settings import TTSOptions
from scripts.tts_service_entry import active_models
from scripts.training_worker import run_script


class TrainingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_active_model_pair_is_v2proplus_and_owned_by_the_selected_project(self):
        project = self.root / 'training/projects/fixture'
        project.mkdir(parents=True)
        gpt, sovits = project / 'voice.ckpt', project / 'voice.pth'
        gpt.write_bytes(b'gpt')
        sovits.write_bytes(b'sovits')
        data = dict(version='v2ProPlus', project=str(project), gpt=str(gpt), sovits=str(sovits))
        record = self.root / 'active.json'
        record.write_text(json.dumps(data))
        selected = active_models(record, self.root)
        # Windows TEMP may use its 8.3 alias; the loader returns canonical paths.
        self.assertTrue(Path(selected['t2s_weights_path']).samefile(gpt))
        external = self.root / 'external.pth'
        external.write_bytes(b'outside model')
        for change in [dict(sovits=str(external)), dict(version='v3')]:
            record.write_text(json.dumps(dict(data, **change)))
            with self.assertRaises(ValueError):
                active_models(record, self.root)

    def test_suspending_a_reused_service_does_not_kill_or_spawn_external_processes(self):
        service = LocalTTSService(SimpleNamespace(info=lambda *_: None), state_dir=self.root / 'tts')
        service.ready = True
        with patch('app.services.local_tts.subprocess.Popen') as spawn:
            asyncio.run(service.suspend())
            self.assertTrue(service.suspended)
            self.assertFalse(service.ready)
            spawn.assert_not_called()
            with self.assertRaisesRegex(ValueError, '训练'):
                # Empty URL describes no local endpoint and intentionally returns early.
                asyncio.run(service.ensure(TTSOptions(url='http://127.0.0.1:9880/tts')))

    def test_cancelled_pause_clears_suspension_when_the_close_is_still_pending(self):
        service = LocalTTSService(SimpleNamespace(info=lambda *_: None), state_dir=self.root / 'tts')
        async def scenario():
            entered = asyncio.Event()
            async def slow_close():
                entered.set()
                await asyncio.Event().wait()
            service.close = AsyncMock(side_effect=slow_close)
            pending = asyncio.create_task(service.suspend())
            await entered.wait()
            self.assertTrue(service.suspended)
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            self.assertFalse(service.suspended, 'Cancelled preparation left all future TTS requests blocked')
        asyncio.run(scenario())

    def test_embedded_python_child_receives_explicit_import_paths_despite_dot_pth(self):
        root = Path(__file__).resolve().parents[1]
        (self.root / 'owned_module.py').write_text('value=729\n')
        stage = self.root / 'stage.py'
        stage.write_text('import owned_module\nassert owned_module.value==729\n')
        with patch('scripts.training_worker.sys.executable', str(root / 'services/gpt_sovits/runtime/python.exe')), \
             patch.dict(os.environ, {'TACHITALK_TRAIN_PATHS': str(self.root)}):
            run_script(stage)

    def test_progress_snapshot_sharing_failure_is_reported_without_aborting_training(self):
        root = Path(__file__).resolve().parents[1]
        source = root / 'services/gpt_sovits/training/training_progress.py'
        spec = importlib.util.spec_from_file_location('training_telemetry_fixture', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        snapshot = self.root / 'epoch.json'
        snapshot.write_text('{"completed":1}')
        with patch.dict(os.environ, {'TACHITALK_TRAIN_PROGRESS': str(snapshot)}), \
             patch.object(Path, 'replace', side_effect=PermissionError('fixture reader holds snapshot')), \
             patch('builtins.print') as log:
            module.report('GPT', 2, 4, force=True)
            self.assertEqual(json.loads(snapshot.read_text())['completed'], 1)
            self.assertIn('TACHITALK_PROGRESS_ERROR', log.call_args.args[0])
