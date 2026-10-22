import asyncio
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.core.voice_settings import TTSOptions
from app.services.local_tts import LocalTTSService
from app.services.owned_process import spawn_hidden
from scripts.start_tts import service_environment


class LocalServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_owned_service_requests_local_warmup_with_existing_reference(self):
        import json
        from config import REF_MAP
        with patch.dict('os.environ', {}, clear=True):
            request = json.loads(service_environment().get('TACHITALK_TTS_WARMUP', '{}'))
        self.assertEqual(request.get('ref_audio_path'), REF_MAP['平常'][0])
        self.assertEqual(request.get('prompt_text'), REF_MAP['平常'][1])
        self.assertEqual(request.get('speed_factor'), 1.0)

    def test_explicit_warmup_disable_is_preserved_for_benchmarks(self):
        with patch.dict('os.environ', {'TACHITALK_TTS_WARMUP': '0'}):
            self.assertEqual(service_environment()['TACHITALK_TTS_WARMUP'], '0')

    def setUp(self):
        self.ui = SimpleNamespace(status=Mock(), info=Mock())
        self.options = TTSOptions(url='http://127.0.0.1:9880/tts')

    async def test_cpu_fallback_reason_is_visible_in_main_ui(self):
        import json
        with TemporaryDirectory() as folder:
            service = LocalTTSService(self.ui, state_dir=folder)
            (Path(folder) / 'runtime_status.json').write_text(json.dumps(
                {'device': 'cpu', 'reason': 'nvrtc: invalid gpu-architecture'}), encoding='utf-8')
            service.report_runtime()
        self.assertIn('CPU', self.ui.info.call_args.args[0])
        self.assertIn('gpu-architecture', self.ui.info.call_args.args[0])

    async def test_oversized_runtime_report_is_not_loaded(self):
        with TemporaryDirectory() as folder:
            service = LocalTTSService(self.ui, state_dir=folder)
            (Path(folder) / 'runtime_status.json').write_bytes(b'x' * 16385)
            service.report_runtime()
        self.ui.info.assert_not_called()

    async def test_existing_service_is_reused_and_never_closed(self):
        service = LocalTTSService(self.ui)
        service.probe = AsyncMock(return_value=True)
        service.launch = Mock()
        await service.ensure(self.options)
        self.assertTrue(service.ready)
        service.launch.assert_not_called()
        await service.close()
        self.assertIsNone(service.process)

    async def test_remote_and_other_tts_providers_are_never_started(self):
        service = LocalTTSService(self.ui)
        service.probe = AsyncMock()
        for options in (replace(self.options, url='https://example.com/tts'), replace(self.options, provider='openai')):
            await service.ensure(options)
        service.probe.assert_not_called()

    async def test_busy_non_tts_port_is_not_touched(self):
        service = LocalTTSService(self.ui)
        service.probe = AsyncMock(return_value=False)
        with patch.object(service, 'port_in_use', return_value=True), patch.object(service, 'launch') as launch:
            with self.assertRaisesRegex(ValueError, '占用'):
                await service.ensure(self.options)
        launch.assert_not_called()

    async def test_spawned_service_waits_for_readiness_and_closes_own_job(self):
        service = LocalTTSService(self.ui)
        service.probe = AsyncMock(side_effect=[False, False, True])
        process, job = Mock(), Mock()
        process.poll.return_value = None
        def launch(_):
            service.process, service.job = process, job
        with patch.object(service, 'launch', side_effect=launch), patch.object(service, 'port_in_use', return_value=False):
            await service.ensure(self.options)
        self.assertTrue(service.ready)
        self.assertEqual(service.probe.await_count, 3)
        await service.close()
        job.close.assert_called_once()
        process.wait.assert_called_once()

    async def test_cancel_during_spawn_still_reaps_owned_process(self):
        service = LocalTTSService(self.ui)
        service.probe = AsyncMock(return_value=False)
        service.port_in_use = Mock(return_value=False)
        process, job = Mock(), Mock()
        process.poll.return_value = None
        import threading
        started, release = threading.Event(), threading.Event()
        def launch(_):
            started.set()
            release.wait(2)
            service.process, service.job = process, job
        with patch.object(service, 'launch', side_effect=launch):
            task = asyncio.create_task(service.ensure(self.options))
            await asyncio.to_thread(started.wait, 2)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        job.close.assert_called_once()

    async def test_windows_job_kills_only_its_process(self):
        if sys.platform != 'win32':
            self.skipTest('Windows Job Object')
        other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], creationflags=subprocess.CREATE_NO_WINDOW)
        process, job = spawn_hidden([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            self.assertIsNone(process.poll())
            job.close()
            await asyncio.to_thread(process.wait, timeout=5)
            self.assertIsNone(other.poll())
        finally:
            job.close()
            if process.poll() is None:
                process.kill()
                process.wait()
            other.terminate()
            other.wait()
