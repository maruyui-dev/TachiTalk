import json
import asyncio
from dataclasses import replace
from io import BytesIO
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import aiohttp
from aiohttp import web

from config import PROMPT, REF_MAP, Settings, get_api_key, redact, register_runtime_key
from app.services.asr import ASRClient
from app.core.ai_settings import AISettings
from app.core.voice_settings import ASROptions, VoiceSettings
from app.services.llm import LLMClient
from app.core.models import AudioFormat, AudioSegment, CaptionPart, SpeechPart, StageError
from app.core.pipeline import Pipeline, check_services, run_application
from app.core.conversation_input import ConversationInput
from app.core.persona import PersonaStore
from app.services.tts import TTSClient
from app.core.expressions import ExpressionStore


class CredentialTests(unittest.TestCase):
    def test_credentials_are_redacted(self):
        secret = "sk-test-000000000000"
        register_runtime_key(secret)
        self.assertNotIn(secret, redact("Authorization: Bearer " + secret))

    def test_missing_key_points_to_ui_and_console_url(self):
        with self.assertRaises(ValueError) as caught:
            get_api_key("asr")
        self.assertIn("语音与音频页", str(caught.exception))
        self.assertNotIn("config.py", str(caught.exception))
        self.assertIn("https://cloud.siliconflow.cn/account/ak", str(caught.exception))


    def test_source_variables_cannot_supply_service_credentials(self):
        with patch('config.ASR_API_KEY', 'sk-test-source-asr', create=True), patch('config.DS_API_KEY', 'sk-test-source-ai', create=True):
            self.assertEqual(VoiceSettings(Settings()).snapshot().asr.api_key, '')
            self.assertEqual(AISettings(Settings()).snapshot().options.api_key, '')
            with self.assertRaises(ValueError):
                get_api_key('asr')


class HTTPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.asr_status = 200
        self.transcript = "你好"
        self.caption_text = "你好。"
        self.llm_fragments = None
        self.requests = []
        self.tts_payload = None
        self.tts_payloads = []
        self.llm_payload = None
        self.asr_fields = {}
        self.tts_requested = asyncio.Event()
        app = web.Application()
        app.router.add_post("/v1/audio/transcriptions", self.asr_handler)
        app.router.add_post("/v1/beta/chat/completions", self.llm_handler)
        app.router.add_post("/tts", self.tts_handler)
        app.router.add_get("/v1/models", self.models_handler)
        app.router.add_get("/openapi.json", self.openapi_handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        base = f"http://127.0.0.1:{self.runner.addresses[0][1]}"
        self.settings = replace(Settings(), asr_url=base + "/v1/audio/transcriptions",
                                llm_base_url=base + "/v1", tts_url=base + "/tts", tts_streaming_mode=2,
                                available_expressions=("平常", "疑问", "紧张"))
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))
        self.ai = AISettings(self.settings)
        self.ai.update(replace(self.ai.snapshot().options, api_key='sk-test-llm-000000'))
        self.asr = ASRClient(self.session, self.settings, ASROptions(
            url=self.settings.asr_url, model=self.settings.asr_model, api_key='sk-test-asr-000000'))
        self.llm = LLMClient(self.session, self.settings, ai=self.ai)
        self.tts = TTSClient(self.session, self.settings)
        self.segment = AudioSegment(b"\0\0" * 320, AudioFormat(16000), perf_counter())

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def models_handler(self, request):
        return web.json_response({"data": [{"id": self.settings.asr_model}, {"id": self.settings.llm_model}]})

    async def openapi_handler(self, request):
        return web.json_response({"paths": {"/tts": {"post": {}}}})

    async def asr_handler(self, request):
        self.requests.append("asr")
        if self.asr_status != 200:
            return web.Response(status=self.asr_status)
        reader = await request.multipart()
        async for field in reader:
            self.asr_fields[field.name] = bytes(await field.read())
        return web.json_response({"text": self.transcript})

    async def llm_handler(self, request):
        self.requests.append("llm")
        self.llm_payload = await request.json()
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        fragments = self.llm_fragments or ('{"parts":[{"expression":"疑问","japanese":"こんにちは。","chinese":',
                                           json.dumps(self.caption_text, ensure_ascii=False) + '}]}')
        for index, fragment in enumerate(fragments):
            if index == 1:
                # 中文故意等到TTS已启动；若程序等待整组/整轮，就会超时失败。
                await asyncio.wait_for(self.tts_requested.wait(), 2)
            function = {"arguments": fragment}
            if index == 0:
                function["name"] = "speak"
            event = {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": function}]}, "finish_reason": None}]}
            payload = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
            # 特意拆开UTF-8与事件行，验证客户端不依赖网络分块边界。
            for position in range(0, len(payload), 7):
                await response.write(payload[position:position+7])
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    async def tts_handler(self, request):
        self.requests.append("tts")
        self.tts_payload = await request.json()
        self.tts_payloads.append(self.tts_payload)
        self.tts_requested.set()
        buffer = BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(32000)
            output.writeframes(b"")
        response = web.StreamResponse(headers={"Content-Type": "audio/wav"})
        await response.prepare(request)
        await response.write(buffer.getvalue()[:13])
        await response.write(buffer.getvalue()[13:])
        for _ in range(10):
            await response.write(b"\1\0" * 640)
            await asyncio.sleep(.001)
        await response.write_eof()
        return response

    async def test_audio_rename_during_stream_keeps_reference_then_updates_next_turn(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from app.core.audio_library import AudioLibrary
        with TemporaryDirectory() as directory:
            source, prompt = REF_MAP['平常']
            library = AudioLibrary(Path(directory) / 'audio.json', {'旧昵称': (source, prompt)})
            self.llm.audio = library
            def reply(name):
                return (json.dumps({'audio_nickname': name, 'parts': [
                    {'expression': '疑问', 'japanese': 'こんにちは。', 'chinese': '你好。'},
                    {'expression': '平常', 'japanese': '少し休みましょう。', 'chinese': '休息一下。'}]}, ensure_ascii=False),)
            self.llm_fragments = reply('旧昵称')
            original = library.snapshot().default
            heard = []
            async for event in self.llm.events('测试音频'):
                if isinstance(event, SpeechPart):
                    heard.append(event.audio_reference)
                    if event.part_id == 0:
                        library.replace(original.key, source)
                        library.update(original.key, name='新昵称', scene='安慰', prompt='新しい原文。', enabled=True, default=True)
                    async for _ in self.tts.stream(event):
                        pass
            self.assertEqual(heard, [original, original])
            self.assertEqual([value['ref_audio_path'] for value in self.tts_payloads], [source, source])
            self.assertEqual([value['prompt_text'] for value in self.tts_payloads], [prompt, prompt])
            self.assertEqual([value['text'] for value in self.tts_payloads], ['こんにちは。', '少し休みましょう。'])
            self.llm_fragments = reply('新昵称')
            current = library.snapshot().default
            async for event in self.llm.events('下一轮'):
                if isinstance(event, SpeechPart):
                    self.assertEqual(event.audio_reference, current)
                    async for _ in self.tts.stream(event):
                        pass
            schema = self.llm_payload['tools'][0]['function']['parameters']
            self.assertEqual(schema['properties']['audio_nickname']['enum'], ['新昵称'])
            self.assertEqual(self.tts_payload['ref_audio_path'], current.path)
            self.assertEqual(self.tts_payload['prompt_text'], '新しい原文。')

    async def test_real_multipart_sse_and_wav_protocols_connect_the_pipeline(self):
        played = []

        async def play(queue, on_first, on_part_start):
            first = True
            while (chunk := await queue.get()) is not None:
                played.append(chunk)
                if first:
                    on_first(perf_counter())
                first = False

        captions = []
        ui = SimpleNamespace(status=lambda _: None, info=lambda _: None, transcript=lambda _: None,
                             begin_reply=lambda _: None, caption=lambda *args: captions.append(args[-1]),
                             part_started=lambda *args: None, end_reply=lambda _: None, timings=lambda _: None)
        pipeline = Pipeline(self.settings, self.asr, self.llm, self.tts, SimpleNamespace(play=play), ui)
        await pipeline.process(self.segment)
        self.assertEqual(self.requests, ["asr", "llm", "tts"])
        with wave.open(BytesIO(self.asr_fields["file"]), "rb") as audio:
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.getnchannels(), 1)
        self.assertEqual(self.llm_payload["thinking"], {"type": "disabled"})
        self.assertTrue(self.llm_payload["stream"])
        self.assertTrue(self.llm_payload['messages'][0]['content'].startswith(PROMPT))
        self.assertIn('文本必须使用简体中文', self.llm_payload['messages'][0]['content'])
        tool = self.llm_payload["tools"][0]["function"]
        self.assertTrue(tool["strict"])
        self.assertEqual(tool["parameters"]["properties"]["parts"]["items"]["properties"]["expression"]["enum"],
                         ["平常", "疑问", "紧张"])
        self.assertEqual(self.tts_payload["streaming_mode"], 2)
        self.assertFalse(self.tts_payload["parallel_infer"])
        self.assertEqual(self.tts_payload["ref_audio_path"], REF_MAP["疑问"][0])
        self.assertEqual(self.tts_payload["text"], "こんにちは。")
        self.assertEqual(captions, ["你好。"])
        self.assertEqual(len(played), 10)
        self.assertTrue(all(chunk.part_id == 0 and chunk.expression == "疑问" for chunk in played))

    async def test_reply_locks_voice_reference_but_keeps_streaming_and_visual_changes(self):
        self.llm.expressions.update(('平常', '疑问', '紧张', '害羞'), '平常')
        played, expressions = [], []

        async def play(queue, on_first, on_part_start):
            previous = None
            while (chunk := await queue.get()) is not None:
                if not played:
                    on_first(perf_counter())
                played.append(chunk)
                if chunk.part_id != previous:
                    on_part_start(chunk.part_id, chunk.expression, perf_counter())
                    previous = chunk.part_id

        ui = SimpleNamespace(status=lambda _: None, transcript=lambda _: None, begin_reply=lambda _: None,
                             caption=lambda *args: None, part_started=lambda *args: expressions.append(args[-1]),
                             end_reply=lambda _: None, timings=lambda _: None)
        pipeline = Pipeline(self.settings, self.asr, self.llm, self.tts, SimpleNamespace(play=play), ui)
        for first, expected in (('疑问', '疑问'), ('害羞', '平常'), ('紧张', '紧张')):
            with self.subTest(main_emotion=first):
                played.clear()
                expressions.clear()
                self.tts_payloads.clear()
                self.tts_requested.clear()
                # 服务等待首段TTS启动才提供第二段，确保实现没有等待完整回复。
                self.llm_fragments = ('{"parts":[{"expression":' + json.dumps(first) +
                                      ',"japanese":"はい。","chinese":',
                                      '"好。"},{"expression":"紧张","japanese":"大丈夫です。","chinese":"没事的。"}]}')
                await pipeline.process_text('测试整轮语气一致')
                self.assertEqual([item['ref_audio_path'] for item in self.tts_payloads], [REF_MAP[expected][0]] * 2)
                self.assertEqual([item['prompt_text'] for item in self.tts_payloads], [REF_MAP[expected][1]] * 2)
                self.assertEqual(expressions, [first, '紧张'])
                self.assertIn('整轮主情绪', self.llm_payload['messages'][0]['content'])

    async def test_resource_expression_updates_llm_schema_parser_and_tts_without_recreating_client(self):
        store = ExpressionStore(self.settings.available_expressions, self.settings.default_expression)
        self.llm.expressions = store
        store.update(('平常', '害羞'), '平常')
        self.llm_fragments = ('{"parts":[{"expression":"害羞","japanese":"はい。","chinese":"好。"}]}',)
        events = [event async for event in self.llm.events('你好')]
        enum = self.llm_payload['tools'][0]['function']['parameters']['properties']['parts']['items']['properties']['expression']['enum']
        self.assertEqual(enum, ['平常', '害羞'])
        self.assertIn('害羞', self.llm_payload['messages'][0]['content'])
        part = next(event for event in events if isinstance(event, SpeechPart))
        self.assertEqual(part.expression, '害羞')
        chunks = [chunk async for chunk in self.tts.stream(part)]
        self.assertTrue(chunks)
        self.assertEqual(self.tts_payload['ref_audio_path'], REF_MAP['平常'][0])
        self.assertTrue(all(chunk.expression == '害羞' for chunk in chunks), '参考音频回退不能改变立绘神态')
        store.update(('平常',), '平常')
        self.llm_fragments = ('{"parts":[{"expression":"平常","japanese":"はい。","chinese":"好。"}]}',)
        _ = [event async for event in self.llm.events('继续')]
        enum = self.llm_payload['tools'][0]['function']['parameters']['properties']['parts']['items']['properties']['expression']['enum']
        self.assertEqual(enum, ['平常'])

    async def test_one_reply_keeps_its_expression_snapshot_while_resources_change(self):
        from contextlib import aclosing
        store = ExpressionStore(('平常', '害羞'), '平常')
        self.llm.expressions = store
        self.llm_fragments = ('{"parts":[{"expression":"害羞","japanese":"はい。","chinese":"好。"},',
                              '{"expression":"害羞","japanese":"そうです。","chinese":"对。"}]}')
        self.tts_requested.set()  # 此测试只消费LLM，不必等独立的TTS任务。
        events = []
        async with aclosing(self.llm.events('你好')) as stream:
            first = await anext(stream)
            events.append(first)
            store.update(('平常',), '平常')
            events.extend([event async for event in stream])
        speech = [event for event in events if isinstance(event, SpeechPart)]
        self.assertEqual([part.expression for part in speech], ['害羞', '害羞'])
        self.assertEqual(store.snapshot().names, ('平常',))
        self.llm_fragments = ('{"parts":[{"expression":"害羞","japanese":"はい。","chinese":"好。"}]}',)
        with self.assertLogs('tachitalk', level='WARNING'):
            events = [event async for event in self.llm.events('下一轮')]
        self.assertEqual(next(event for event in events if isinstance(event, SpeechPart)).expression, '平常')

    async def test_http_authentication_failure_preserves_status(self):
        self.asr_status = 401
        with self.assertRaises(StageError) as caught:
            await self.asr.transcribe(self.segment)
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(self.requests, ["asr"])

    async def test_fragment_mode_explicitly_enables_parallel_inference(self):
        client = TTSClient(self.session, replace(self.settings, tts_streaming_mode=1))
        chunks = [chunk async for chunk in client.stream(SpeechPart(0, "はい。", "平常"))]
        self.assertEqual(len(chunks), 10)
        self.assertEqual(self.tts_payload["streaming_mode"], 1)
        self.assertTrue(self.tts_payload["parallel_infer"])

    async def test_empty_and_single_character_asr_are_distinguished(self):
        self.transcript = " ...！？ "
        self.assertEqual(await self.asr.transcribe(self.segment), "")
        self.transcript = "嗯"
        self.assertEqual(await self.asr.transcribe(self.segment), "嗯")

    async def test_startup_checks_all_services_without_generating_replies(self):
        results = await check_services(self.session, self.settings,
                                       api_keys={'ASR': 'sk-test-asr-000000', 'LLM': 'sk-test-llm-000000'})
        self.assertEqual(results, {"ASR": None, "LLM": None, "TTS": None})
        self.assertEqual(self.requests, [])

    async def test_network_streaming_and_buffered_caption_modes_keep_speech_early(self):
        self.llm_fragments = ('{"parts":[{"expression":"疑问","japanese":"こんにちは。","chinese":"你', '好', '。"}]}')
        for enabled in (True, False):
            with self.subTest(streaming=enabled):
                self.tts_requested.clear()
                self.llm.profiles.update(character_name='茉子', user_name='', reply_language='简体中文',
                                         persona_prompt='', stream_reply=enabled)
                events = []
                async for event in self.llm.events('测试流式气泡'):
                    events.append(event)
                    if isinstance(event, SpeechPart):
                        self.tts_requested.set()  # 服务等首段语音消费后才发送后续文字。
                self.assertIsInstance(events[0], SpeechPart)
                captions = [e.chinese for e in events if isinstance(e, CaptionPart)]
                self.assertEqual(captions, ['你', '你好', '你好。'] if enabled else ['你好。'])
                self.assertTrue(self.llm_payload['stream'], '关闭气泡流式显示仍需保留语音流水线')

    async def test_invalid_reply_does_not_enter_conversation_context(self):
        self.tts_requested.set()
        self.llm_fragments = ('{"parts":[{"expression":"疑问","japanese":"こんにちは。","chinese":"你', '好')
        with self.assertRaises(StageError):
            async for _ in self.llm.events('不能记录这个失败轮次'):
                pass
        self.assertEqual(self.llm.history.messages(20), [])

    async def test_text_runtime_uses_real_http_llm_tts_without_asr_key_or_microphone(self):
        from app.audio.play import AudioPlayer
        from test_pipeline import TestOutput, TestUI
        TestOutput.instances = []
        inputs = ConversationInput()
        inputs.set_recording(False)
        profiles = PersonaStore()
        ui = TestUI()
        ui.error = lambda error: ui.messages.append(str(error))
        with (patch('config.Path.is_file', return_value=True),
              patch('app.audio.record.pyaudio.PyAudio') as microphone,
              patch('app.services.speech_services.ASRClient') as asr_factory,
              patch('app.core.pipeline.AudioPlayer', side_effect=lambda settings: AudioPlayer(settings, TestOutput))):
            task = asyncio.create_task(run_application(self.settings, ui, inputs, profiles, ai=self.ai))
            try:
                async with asyncio.timeout(3):
                    while not inputs.snapshot().ready:
                        await asyncio.sleep(.005)
                # 每轮分别防止挂起；这里验证功能，不把两轮总时长当作性能要求。
                for text, language, caption, persona in (
                    ('现在不方便说话', '英文', 'Hello.', '你是严谨简洁的伙伴。'),
                    ('第二轮也使用文字', '日文', 'こんにちは。', ''),
                ):
                    profiles.update(character_name='小夏', user_name='阿明', reply_language=language, persona_prompt=persona)
                    self.caption_text = caption
                    async with asyncio.timeout(4):
                        self.assertTrue(inputs.submit_text(text)[0])
                        while inputs.snapshot().busy:
                            await asyncio.sleep(.005)
                    prompt = self.llm_payload['messages'][0]['content']
                    self.assertTrue(prompt.startswith(persona or PROMPT))
                    if persona:
                        self.assertNotIn(PROMPT, prompt, '自定义人设必须替换config人设')
                    self.assertIn('小夏', prompt)
                    self.assertIn('阿明', prompt)
                    self.assertIn(f'文本必须使用{language}', prompt)
                    properties = self.llm_payload['tools'][0]['function']['parameters']['properties']['parts']['items']['properties']
                    self.assertIn('English' if language == '英文' else 'Japanese', properties['chinese']['description'])
                    self.assertIn(caption, ui.messages, '所选语言文本须实际传到气泡接口')
                    self.assertEqual(self.tts_payload['text'], 'こんにちは。', '气泡语言不能改变配音语言')
                self.assertFalse(task.done(), '两轮文字对话后也必须保持程序常驻')
                self.assertEqual(self.requests, ['llm', 'tts', 'llm', 'tts'])
                self.assertEqual(self.llm_payload['messages'][-1]['content'], '第二轮也使用文字')
                messages = self.llm_payload['messages']
                self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'user'])
                self.assertEqual(messages[1]['content'], '现在不方便说话')
                self.assertEqual(json.loads(messages[2]['content'])['parts'][0]['chinese'], 'Hello.')
                self.assertEqual(self.tts_payload['text'], 'こんにちは。')
                self.assertEqual(ui.metrics['input_kind'], 'text')
                self.assertTrue(TestOutput.instances[0].blocks)
                asr_factory.assert_not_called()
                microphone.assert_not_called()
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(TestOutput.instances[0].closed)
