import asyncio
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
import unittest

from app.core.conversation_input import ConversationInput
from app.core.models import AudioFormat, AudioSegment


class ConversationInputTests(unittest.TestCase):
    def ready(self, recording=False):
        inputs = ConversationInput()
        inputs.set_recording(recording)
        for name in ('LLM', 'TTS', 'ASR'):
            inputs.set_service_ready(name)
        return inputs

    def test_text_mode_needs_llm_tts_but_not_asr(self):
        inputs = ConversationInput()
        inputs.set_service_ready('LLM')
        inputs.set_service_ready('TTS')
        self.assertFalse(inputs.snapshot().ready)
        inputs.set_recording(False)
        self.assertTrue(inputs.snapshot().ready)
        self.assertTrue(inputs.submit_text('你好')[0])
        request = inputs.take_next()
        self.assertEqual(request.payload, '你好')
        inputs.finish_turn()

    def test_multiple_threads_can_reserve_only_one_text_turn(self):
        inputs = self.ready()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: inputs.submit_text('同时发送'), range(40)))
        self.assertEqual(sum(accepted for accepted, _ in results), 1)
        self.assertEqual(inputs.pending.qsize(), 1)
        self.assertTrue(inputs.snapshot().busy)
        inputs.take_next()
        inputs.finish_turn()
        self.assertTrue(inputs.submit_text('下一轮')[0])

    def test_disabling_recording_discards_queued_audio_and_old_revisions(self):
        inputs = self.ready(recording=True)
        segment = AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter())
        _, revision = inputs.recording_state()
        self.assertTrue(inputs.offer_audio(segment, revision))
        inputs.set_recording(False)
        self.assertIsNone(inputs.take_next())
        self.assertFalse(inputs.snapshot().busy)
        self.assertTrue(inputs.submit_text('现在使用文字')[0])
        inputs.take_next()
        inputs.finish_turn()
        inputs.set_recording(True)
        self.assertFalse(inputs.offer_audio(segment, revision), '快速开关后不能接纳旧缓冲区音频')

    def test_disabling_recording_keeps_an_active_reply_busy(self):
        inputs = self.ready(recording=True)
        segment = AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter())
        self.assertTrue(inputs.offer_audio(segment, inputs.recording_state()[1]))
        inputs.take_next()
        inputs.set_recording(False)
        self.assertFalse(inputs.submit_text('不能插入')[0])
        inputs.finish_turn()
        self.assertTrue(inputs.submit_text('回复完成后再发送')[0])

    def test_switching_to_voice_preserves_an_already_accepted_text(self):
        inputs = self.ready()
        inputs.submit_text('已发送的文字')
        inputs.set_recording(True)
        self.assertEqual(inputs.take_next().payload, '已发送的文字')
        inputs.finish_turn()
        self.assertFalse(inputs.snapshot().busy)

    def test_invalid_or_unready_text_never_enters_the_queue(self):
        inputs = ConversationInput()
        inputs.set_recording(False)
        for value in ('', '  ', 'x' * 2001, '服务未就绪'):
            self.assertFalse(inputs.submit_text(value)[0])
        self.assertEqual(inputs.pending.qsize(), 0)
        self.assertFalse(inputs.snapshot().busy)
        inputs.close()
        self.assertFalse(inputs.submit_text('已关闭')[0])


class ConversationWakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_wakes_the_bound_loop_without_polling(self):
        inputs = ConversationInput()
        inputs.bind_loop()
        await asyncio.sleep(0)
        inputs.clear_wake()
        await asyncio.to_thread(inputs.set_recording, False)
        await asyncio.wait_for(inputs.wait_changed(), 1)
        self.assertFalse(inputs.snapshot().recording)
        inputs.unbind_loop()

    async def test_pending_asr_check_does_not_hold_text_mode_hostage(self):
        from config import Settings
        from app.core.voice_runtime import monitor_voice_services
        from app.core.voice_settings import ASROptions, TTSOptions, VoiceSettings
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        inputs = ConversationInput()
        asr_started, asr_cancelled = asyncio.Event(), asyncio.Event()

        async def local_asr(*args):
            asr_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                asr_cancelled.set()

        async def check_llm(*args):
            return None

        ui = SimpleNamespace(info=lambda _: None, error=lambda _: None)
        voices = VoiceSettings(Settings())
        voices.set_asr(ASROptions(provider='whisper', model='small'))
        voices.set_tts(TTSOptions(provider='system', voice='test'))
        speech = SimpleNamespace(whisper=SimpleNamespace(request=local_asr),
                                 system=SimpleNamespace(voices=AsyncMock(return_value=[{'name': 'test'}]), request=AsyncMock()))
        task = asyncio.create_task(monitor_voice_services(None, Settings(), inputs, voices, speech, ui, check_llm))
        try:
            await asyncio.wait_for(asr_started.wait(), 1)
            while not inputs.service_ready('TTS'):
                await asyncio.sleep(.005)
            self.assertFalse(inputs.snapshot().ready)
            inputs.set_recording(False)
            self.assertTrue(inputs.snapshot().ready)
            self.assertTrue(inputs.submit_text('文字不应等待ASR超时')[0])
            await asyncio.wait_for(asr_cancelled.wait(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
