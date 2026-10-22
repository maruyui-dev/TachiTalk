import json
import asyncio
import unittest
from time import perf_counter
from dataclasses import replace
from types import SimpleNamespace

from config import Settings
from app.core.audio_library import AudioReference, AudioSnapshot
from app.core.models import SpeechPart
from app.services.llm import LLMClient, ReplyParser
from app.core.voice_settings import ReferencePreview, VoiceSettings
from app.core.voice_runtime import run_voice_commands
from app.core.conversation_input import ConversationInput
from app.audio.playback_bus import PlaybackBus
from config import REF_MAP


class AudioProtocolTests(unittest.TestCase):
    def setUp(self):
        self.ref = AudioReference('id', '温柔', 'D:/reference.wav', 'こんにちは。', '安慰', enabled=True)
        self.snapshot = AudioSnapshot((self.ref,), self.ref)

    def test_character_stream_submits_japanese_before_caption_with_fixed_audio(self):
        parser = ReplyParser(Settings(), audio=self.snapshot)
        prefix = '{"audio_nickname":"温柔","parts":[{"expression":"平常","japanese":"おかえり。"'
        events = []
        for char in prefix:
            events.extend(parser.feed(char))
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], SpeechPart)
        self.assertIs(events[0].audio_reference, self.ref)
        parser.feed(',"chinese":"回来啦。"},{"expression":"疑问","japanese":"元気ですか。","chinese":"还好吗？"}]}')
        parser.finish()

    def test_tool_and_prompt_change_after_rename_and_disable(self):
        current = [self.snapshot]
        client = LLMClient(None, Settings(), audio=SimpleNamespace(snapshot=lambda: current[0]))
        def names():
            return client.reply_tool()['function']['parameters']['properties']['audio_nickname']['enum']
        self.assertEqual(names(), ['温柔'])
        new = replace(self.ref, name='轻声')
        current[0] = AudioSnapshot((new,), new)
        self.assertEqual(names(), ['轻声'])
        self.assertIn('轻声', client.system_prompt(client.profiles.snapshot()))
        self.assertNotIn('温柔', client.system_prompt(client.profiles.snapshot()))

    def test_stale_llm_name_uses_current_snapshot_default(self):
        parser = ReplyParser(Settings(), audio=self.snapshot)
        events = parser.feed(json.dumps({'audio_nickname': '已经删除', 'parts': [
            {'expression': '平常', 'japanese': 'はい。', 'chinese': '好。'}]}))
        parser.finish()
        self.assertIs(events[0].audio_reference, self.ref)

    def test_text_only_and_other_tts_do_not_require_audio_library(self):
        def fail():
            raise ValueError('empty library')
        client = LLMClient(None, Settings(), audio=SimpleNamespace(snapshot=fail), audio_active=lambda: False)
        self.assertNotIn('audio_nickname', client.reply_tool()['function']['parameters']['properties'])

    def test_duplicate_audio_choice_is_rejected(self):
        from app.core.models import StageError
        parser = ReplyParser(Settings(), audio=self.snapshot)
        parser.feed('{"audio_nickname":"温柔","parts":[{"expression":"平常","japanese":"はい。","chinese":"好。"}],"audio_nickname":"旧昵称"}')
        with self.assertRaises(StageError):
            parser.finish()


class AudioPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_raw_preview_recovers_and_tts_uses_selected_reference(self):
        from app.core.models import AudioChunk, AudioFormat
        settings, voices = Settings(), VoiceSettings(Settings())
        inputs = ConversationInput()
        played, requests = [], []
        async def play(queue, first, started):
            seen = None
            while (chunk := await queue.get()) is not None:
                played.append(chunk)
                if chunk.part_id is not None and seen != chunk.part_id:
                    first(perf_counter())
                    started(chunk.part_id, chunk.expression, perf_counter())
                    seen = chunk.part_id
        async def stream(part, **kwargs):
            requests.append(part)
            yield AudioChunk(b'\0\0' * 640, AudioFormat(32000))
        bus = PlaybackBus(SimpleNamespace(play=play), voices, inputs)
        ui = SimpleNamespace(error=lambda *_: None)
        task = asyncio.create_task(run_voice_commands(settings, voices, SimpleNamespace(stream=stream), bus, ui))
        async def wait():
            async with asyncio.timeout(3):
                while voices.result('preview').running:
                    await asyncio.sleep(.01)
        try:
            ref = AudioReference('id', '昵称', 'D:/does-not-exist.wav', 'こんにちは。')
            voices.request('preview', ReferencePreview(ref, True))
            await wait()
            self.assertTrue(voices.result('preview').error)
            path, prompt = REF_MAP['平常']
            ref = replace(ref, path=path, prompt=prompt)
            voices.request('preview', ReferencePreview(ref, True))
            await wait()
            self.assertFalse(voices.result('preview').error)
            self.assertTrue(played)
            self.assertEqual(requests, [])
            self.assertTrue(bus.is_echo(prompt, perf_counter()), '原音试听也必须登记原文，防止识别成用户输入')
            voices.request('preview', ReferencePreview(ref))
            await wait()
            self.assertEqual(requests[0].audio_reference, ref)
            self.assertIsNone(bus.owner)
            self.assertFalse(inputs.playback_active())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
