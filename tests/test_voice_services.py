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
from PySide6.QtWidgets import QApplication, QPushButton

from config import Settings, redact
from app.audio.play import AudioPlayer
from app.audio.playback_bus import PlaybackBus
from app.audio.record import AudioCapture
from app.audio.vad import SpeechSegmenter
from app.core.conversation_input import ConversationInput
from app.core.models import AudioChunk, AudioFormat, AudioSegment, CaptionPart, SpeechPart
from app.core.pipeline import Pipeline
from app.core.voice_settings import ASROptions, TTSOptions, VoiceSettings
from app.core.voice_runtime import run_voice_commands, serve_conversations
from app.services.catalog import fetch_asr_models
from app.services.speech_services import SpeechServices
from app.ui.control_panel import load_window


class Events:
    def __init__(self):
        self.messages = []

    def __getattr__(self, name):
        return lambda *args: self.messages.append((name, args))


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.005)


class VoiceStateTests(unittest.TestCase):
    def test_text_only_reply_does_not_require_an_available_tts(self):
        inputs = ConversationInput()
        inputs.set_recording(False)
        inputs.set_service_ready('LLM')
        self.assertFalse(inputs.submit_text('你好')[0])
        inputs.set_voice_preferences(auto_read=False, auto_send=True, interrupt=True)
        self.assertTrue(inputs.submit_text('你好')[0])

    def test_commands_are_bounded_and_stale_completion_cannot_replace_newer_request(self):
        voices = VoiceSettings(Settings())
        old = voices.request('models', ASROptions())
        for _ in range(1000):
            latest = voices.request('models', ASROptions(provider='custom'))
        voices.complete('models', old, value=('wrong',))
        self.assertEqual(len(voices.commands()), 1)
        self.assertTrue(voices.result('models').running)
        voices.complete('models', latest, value=('actual',))
        self.assertEqual(voices.result('models').value, ('actual',))

    def test_flags_do_not_recheck_transport_and_keys_are_redacted(self):
        voices = VoiceSettings(Settings())
        old = voices.snapshot()
        voices.set_tts(replace(old.tts, auto_read=False, interrupt=False))
        voices.set_asr(replace(old.asr, auto_send=False, trim_silence=False, language='ja'))
        self.assertEqual(voices.snapshot().asr_revision, old.asr_revision)
        self.assertEqual(voices.snapshot().tts_revision, old.tts_revision)
        voices.set_asr(replace(old.asr, api_key='private-voice-test-secret'))
        self.assertNotIn('private-voice-test-secret', redact('private-voice-test-secret'))
        self.assertEqual(voices.snapshot().asr_revision, old.asr_revision + 1)

    def test_trim_switch_changes_uploaded_edges_but_preserves_speech(self):
        lengths = []
        for trim in (True, False):
            segmenter = SpeechSegmenter(trim_silence=trim)
            frames = [False] * 15 + [True] * 15 + [False] * 30
            result = None
            for index, speech in enumerate(frames):
                result = segmenter.feed((b'\x01\x00' if speech else b'\x00\x00') * 320,
                                        speech=speech, now=index * .02) or result
            lengths.append(len(result.pcm))
            self.assertEqual(result.pcm.count(b'\x01\x00'), 15 * 320)
        self.assertLess(lengths[0], lengths[1])

    def test_manual_release_can_submit_one_interrupt_candidate_only(self):
        inputs = ConversationInput()
        inputs.set_voice_preferences(auto_read=True, auto_send=True, interrupt=True)
        for service in ('ASR', 'LLM', 'TTS'):
            inputs.set_service_ready(service)
        inputs.configure_audio(mode='hold')
        segment = AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter())
        inputs.offer_audio(segment, inputs.recording_state()[1])
        inputs.take_next()
        inputs.set_playback_active(True)
        capture = AudioCapture(Settings(), inputs.gate, inputs)
        self.assertTrue(inputs.set_manual_active(True))
        for index in range(12):
            capture.accept_frame(b'\1\0' * 320, speech=True, now=perf_counter())
        inputs.set_manual_active(False)
        capture.accept_frame(b'\0\0' * 320, speech=False, now=perf_counter())
        self.assertEqual(inputs.pending.qsize(), 1)
        self.assertFalse(inputs.offer_audio(segment, inputs.recording_state()[1]))
        inputs.take_next()
        inputs.finish_turn()
        self.assertTrue(inputs.snapshot().busy)
        inputs.finish_turn()
        self.assertFalse(inputs.snapshot().busy)


class VoiceHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = {}
        app = web.Application()
        app.router.add_get('/models', self.models)
        app.router.add_post('/transcribe', self.transcribe)
        app.router.add_post('/speech', self.speech)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, '127.0.0.1', 0).start()
        self.base = f'http://127.0.0.1:{self.runner.addresses[0][1]}'
        self.session = aiohttp.ClientSession()
        self.settings = Settings()
        self.voices = VoiceSettings(self.settings)
        self.router = SpeechServices(self.session, self.settings, self.voices)

    async def asyncTearDown(self):
        await self.router.close()
        await self.session.close()
        await self.runner.cleanup()

    async def models(self, request):
        self.received['catalog_auth'] = request.headers.get('Authorization')
        return web.json_response({'data': [{'id': 'chat-only'}, {'id': 'whisper-test'}, {'id': 'whisper-test'}]})

    async def transcribe(self, request):
        self.received['asr_auth'] = request.headers.get('Authorization')
        fields = {}
        async for field in await request.multipart():
            fields[field.name] = bytes(await field.read())
        self.received['fields'] = fields
        return web.json_response({'text': 'test words'})

    async def speech(self, request):
        self.received['tts_auth'] = request.headers.get('Authorization')
        self.received['tts'] = await request.json()
        buffer = BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(b'\x01\x00' * 1000)
        return web.Response(body=buffer.getvalue(), content_type='audio/wav')

    async def test_custom_catalog_and_multipart_send_actual_configuration(self):
        options = ASROptions(provider='custom', url=self.base + '/transcribe', models_url=self.base + '/models',
                             model='whisper-test', api_key='test-custom-secret', language='ja')
        self.assertEqual(await fetch_asr_models(self.session, options), ('whisper-test',))
        segment = AudioSegment(b'\1\0' * 320, AudioFormat(16000), perf_counter())
        self.assertEqual(await self.router.transcribe(segment, options), 'test words')
        fields = self.received['fields']
        self.assertEqual(fields['language'], b'ja')
        self.assertEqual(fields['model'], b'whisper-test')
        self.assertTrue(fields['file'].startswith(b'RIFF'))
        self.assertEqual(self.received['asr_auth'], 'Bearer test-custom-secret')

    async def test_silicon_does_not_send_an_undocumented_language_parameter(self):
        options = ASROptions(url=self.base + '/transcribe', model='test', api_key='test', language='zh')
        await self.router.transcribe(AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter()), options)
        self.assertNotIn('language', self.received['fields'])

    async def test_compatible_tts_decodes_wav_and_keeps_part_expression(self):
        options = TTSOptions(provider='custom', url=self.base + '/speech', model='model-id', voice='voice-id',
                             api_key='test-tts-secret', require_key=True)
        chunks = [chunk async for chunk in self.router.stream(SpeechPart(2, 'こんにちは。', '平常'), options)]
        self.assertEqual(self.received['tts'], {'model': 'model-id', 'input': 'こんにちは。',
                                              'voice': 'voice-id', 'response_format': 'wav'})
        self.assertEqual(self.received['tts_auth'], 'Bearer test-tts-secret')
        self.assertEqual(b''.join(chunk.pcm for chunk in chunks), b'\1\0' * 1000)
        self.assertTrue(all((chunk.part_id, chunk.expression) == (2, '平常') for chunk in chunks))

    async def test_model_list_http_failure_is_not_replaced_with_fake_models(self):
        from app.core.models import StageError
        options = ASROptions(provider='custom', models_url=self.base + '/missing', require_key=False)
        with self.assertRaises(StageError) as caught:
            await fetch_asr_models(self.session, options)
        self.assertEqual(caught.exception.status, 404)


class VoiceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings()
        self.voices = VoiceSettings(self.settings)
        self.inputs = ConversationInput()
        self.voices.set_tts(replace(self.voices.snapshot().tts, interrupt=True))
        self.inputs.set_voice_preferences(auto_read=True, auto_send=True, interrupt=True)
        self.inputs.bind_loop()
        for service in ('ASR', 'LLM', 'TTS'):
            self.inputs.set_service_ready(service)
        self.ui = Events()
        self.bus = PlaybackBus(None, self.voices, self.inputs)

    async def asyncTearDown(self):
        self.inputs.close()
        self.inputs.unbind_loop()

    async def test_auto_read_off_generates_text_without_touching_tts_or_player(self):
        self.voices.set_tts(replace(self.voices.snapshot().tts, auto_read=False))
        async def events(text, **kwargs):
            yield SpeechPart(0, 'こんにちは。', '平常')
            yield CaptionPart(0, '你好。')
        pipeline = Pipeline(self.settings, None, SimpleNamespace(events=events), None, None, self.ui, voices=self.voices)
        await pipeline.process_text('你好')
        self.assertFalse(pipeline.last_metrics['spoken'])
        self.assertIn(('caption', (self.ui_turn(pipeline), 0, '你好。')), self.ui.messages)

    def ui_turn(self, pipeline):
        return next(args[0] for name, args in self.ui.messages if name == 'begin_reply')

    async def test_asr_manual_confirmation_stops_at_draft_and_blocks_overwrite(self):
        self.voices.set_asr(replace(self.voices.snapshot().asr, auto_send=False))
        self.inputs.set_voice_preferences(auto_read=True, auto_send=False, interrupt=True)
        async def recognize(segment):
            return '请先让我编辑', 1, 2
        pipeline = SimpleNamespace(recognize=recognize, llm=None)
        task = asyncio.create_task(serve_conversations(pipeline, self.inputs, self.voices, self.bus, self.ui, (), lambda: None))
        segment = AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter())
        try:
            self.assertTrue(self.inputs.offer_audio(segment, self.inputs.recording_state()[1]))
            await wait_until(lambda: self.voices.draft()[0])
            self.assertEqual(self.voices.draft()[0], '请先让我编辑')
            self.assertIsNone(pipeline.llm)
            self.assertFalse(self.inputs.offer_audio(segment, self.inputs.recording_state()[1]))
            self.assertFalse(self.inputs.snapshot().busy)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_new_valid_voice_cancels_old_reply_after_asr_but_echo_does_not(self):
        self.inputs.set_recording(False)
        reply_started, cancelled = asyncio.Event(), asyncio.Event()
        recognized = []
        spoken_text = '今はテスト中です'
        new_replies = []
        async def process_text(text, submitted_at):
            try:
                async with self.bus.lease():
                    self.bus.started()
                    self.bus.remember(spoken_text)
                    reply_started.set()
                    await asyncio.Event().wait()
            finally:
                cancelled.set()
        async def recognize(segment):
            await asyncio.sleep(.01)
            self.assertFalse(cancelled.is_set(), '识别完成前不能因VAD候选停止旧播放')
            return recognized.pop(0), 1, 2
        async def reply(text, *args):
            new_replies.append(text)
        pipeline = SimpleNamespace(process_text=process_text, recognize=recognize, _reply=reply, llm=object())
        task = asyncio.create_task(serve_conversations(pipeline, self.inputs, self.voices, self.bus, self.ui, (), lambda: None))
        try:
            self.inputs.submit_text('start')
            await asyncio.wait_for(reply_started.wait(), 2)
            self.inputs.set_recording(True)
            segment = AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter())
            recognized.append(spoken_text)
            self.assertTrue(self.inputs.offer_audio(segment, self.inputs.recording_state()[1]))
            await wait_until(lambda: not recognized and self.inputs.can_interrupt())
            self.assertFalse(cancelled.is_set())
            recognized.append('请换一个话题')
            self.assertTrue(self.inputs.offer_audio(segment, self.inputs.recording_state()[1]))
            await wait_until(lambda: new_replies)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(new_replies, ['请换一个话题'])
            await wait_until(lambda: not self.inputs.snapshot().busy)
            self.assertEqual(self.inputs.pending.unfinished_tasks, 0)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_interrupt_switch_off_rejects_busy_input(self):
        self.inputs.set_recording(False)
        self.inputs.submit_text('first')
        self.inputs.take_next()
        self.inputs.set_playback_active(True)
        self.inputs.set_voice_preferences(auto_read=True, auto_send=True, interrupt=False)
        self.assertFalse(self.inputs.submit_text('second')[0])
        self.inputs.set_recording(True)
        self.assertFalse(self.inputs.offer_audio(AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter()),
                                                 self.inputs.recording_state()[1]))
        self.inputs.finish_turn()

    async def test_vad_continues_collecting_one_candidate_while_playing(self):
        segment = AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter())
        self.inputs.offer_audio(segment, self.inputs.recording_state()[1])
        self.inputs.take_next()
        self.inputs.set_playback_active(True)
        capture = AudioCapture(self.settings, self.inputs.gate, self.inputs)
        for index, voiced in enumerate([True] * 15 + [False] * 30):
            capture.accept_frame(b'\1\0' * 320, speech=voiced, now=perf_counter())
        self.assertEqual(self.inputs.pending.qsize(), 1)
        self.inputs.take_next()
        self.inputs.finish_turn()
        self.inputs.finish_turn()
        self.assertEqual(self.inputs.pending.unfinished_tasks, 0)

    async def test_cancelled_local_recognition_kills_its_real_child_process(self):
        import sys
        from app.services.local_whisper import LocalWhisper
        whisper = LocalWhisper()
        async def start():
            whisper.process = await asyncio.create_subprocess_exec(
                sys.executable, '-u', '-c', 'import sys,time; sys.stdin.readline(); time.sleep(30)',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            whisper.stderr_task = asyncio.create_task(whisper._drain_stderr(whisper.process))
        with patch.object(whisper, '_start', start):
            task = asyncio.create_task(whisper.request({'operation': 'check'}))
            await wait_until(lambda: whisper.process is not None)
            process = whisper.process
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertIsNotNone(process.returncode)
        self.assertIsNone(whisper.process)

    async def test_local_whisper_filters_punctuation_like_online_asr(self):
        from unittest.mock import AsyncMock
        from app.services.local_whisper import LocalWhisper
        whisper = LocalWhisper()
        with patch.object(whisper, 'request', AsyncMock(return_value={'text': '。 … '})):
            text = await whisper.transcribe(AudioSegment(b'\0\0' * 320, AudioFormat(16000), perf_counter()),
                                            ASROptions(provider='whisper', model='small'))
        self.assertEqual(text, '')

    async def test_preview_stop_cancels_synthesis_and_closes_output_lease(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()
        options = TTSOptions(provider='custom', url='http://localhost/speech', model='test', voice='test')
        async def stream(part, options=None, language=None):
            self.assertEqual((part.japanese, options.provider, language), ('你好', 'custom', 'zh'))
            try:
                entered.set()
                await asyncio.Event().wait()
                yield
            finally:
                cancelled.set()
        async def play(queue, *callbacks):
            await queue.get()
        self.bus.player = SimpleNamespace(play=play)
        task = asyncio.create_task(run_voice_commands(self.settings, self.voices, SimpleNamespace(stream=stream), self.bus, self.ui))
        try:
            self.voices.request('preview', ('你好', options))
            await asyncio.wait_for(entered.wait(), 2)
            self.voices.request('preview', None)
            await wait_until(lambda: not self.voices.result('preview').running)
            self.assertTrue(cancelled.is_set())
            self.assertIsNone(self.bus.owner)
            self.assertFalse(self.inputs.playback_active())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class VoiceControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.panel = load_window()
        self.inputs = ConversationInput()
        for name in ('ASR', 'LLM', 'TTS'):
            self.inputs.set_service_ready(name)
        self.voices = VoiceSettings(Settings())
        self.controls = self.panel.voice_controls
        self.controls.bind_runtime(self.voices, self.inputs)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_defaults_dropdowns_and_combined_preview_button(self):
        c = self.controls
        self.assertEqual([c.w('asrProviderCombo').itemText(i) for i in range(4)],
                         ['硅基流动', 'OpenAI 兼容接口', '本地 Whisper', '自定义服务'])
        self.assertEqual(c.w('ttsProviderCombo').currentText(), 'GPT-SoVITS')
        self.assertEqual(c.w('asrLanguageCombo').count(), 4)
        self.assertFalse(c.w('asrLanguageCombo').isEnabled())
        self.assertTrue(all(c.w(name).isChecked() for name in ('autoReadCheck', 'asrAutoSendCheck', 'trimSilenceCheck')))
        self.assertFalse(c.w('interruptSpeechCheck').isChecked())
        self.assertFalse(self.voices.snapshot().tts.interrupt)
        c.w('interruptSpeechCheck').setChecked(True)
        self.assertTrue(self.voices.snapshot().tts.interrupt)
        c.w('ttsProviderCombo').setCurrentIndex(3)
        self.assertTrue(c.w('interruptSpeechCheck').isChecked())
        self.assertTrue(self.voices.snapshot().tts.interrupt)
        self.assertIsNone(self.panel.findChild(QPushButton, 'stopSampleButton'))
        self.assertEqual(c.w('scanSpeakerButton').property('accent'), 'pink')
        self.assertEqual(c.w('playSampleButton').property('accent'), 'blue')

    def test_changing_service_isolates_keys_and_automatically_requests_new_models(self):
        c = self.controls
        old_id = self.voices.commands()['models'].id
        c.w('asrProviderCombo').setCurrentIndex(3)
        self.assertEqual(c.w('asrApiKeyEdit').text(), '')
        self.assertTrue(c.w('asrLanguageCombo').isEnabled())
        self.assertGreater(self.voices.commands()['models'].id, old_id)
        c.w('asrApiKeyEdit').setText('custom-private-key')
        c.w('asrModelCombo').setCurrentText('actual-asr')
        c.save_asr()
        c.w('asrProviderCombo').setCurrentIndex(0)
        self.assertNotEqual(c.w('asrApiKeyEdit').text(), 'custom-private-key')
        c.w('asrProviderCombo').setCurrentIndex(3)
        self.assertEqual(c.w('asrApiKeyEdit').text(), 'custom-private-key')

    def test_model_result_selects_real_model_and_old_result_is_ignored(self):
        c = self.controls
        c.w('asrProviderCombo').setCurrentIndex(3)
        command = self.voices.commands()['models']
        self.voices.complete('models', command.id, value=('actual-asr', 'another-asr'))
        c.refresh()
        self.assertEqual(self.voices.snapshot().asr.model, 'actual-asr')
        self.assertEqual(c.w('asrModelCombo').count(), 2)

    def test_manual_asr_draft_send_and_playback_volume_reach_runtime(self):
        c = self.controls
        c.w('asrAutoSendCheck').setChecked(False)
        self.voices.set_draft('编辑前')
        self.inputs.set_review_pending(True)
        c.refresh()
        c.w('asrDraftEdit').setPlainText('编辑后')
        c.send_draft()
        self.assertEqual(self.inputs.take_next().payload, '编辑后')
        self.inputs.finish_turn()
        c.w('outputVolumeSlider').setValue(34)
        self.assertEqual(self.voices.snapshot().output.volume, 34)
        self.assertEqual(c.w('outputVolumeSliderValue').text(), '34%')
        self.assertEqual(self.voices.draft()[0], '')

    def test_preview_toggles_one_button_using_selected_tts(self):
        c = self.controls
        c.w('ttsProviderCombo').setCurrentIndex(3)
        for name, value in (('ttsUrlEdit', 'http://localhost/speech'), ('ttsModelEdit', 'model'), ('ttsVoiceEdit', 'voice')):
            c.w(name).setText(value)
        c.w('ttsRequireKeyCheck').setChecked(False)
        c.toggle_preview()
        command = self.voices.commands()['preview']
        self.assertEqual(command.payload[1].provider, 'custom')
        self.assertEqual(c.w('playSampleButton').text(), '结束')
        c.toggle_preview()
        self.assertIsNone(self.voices.commands()['preview'].payload)


class OutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_device_and_volume_change_actual_output_and_only_outputs_are_listed(self):
        from array import array
        streams = []
        class Output:
            def __init__(self, **kwargs):
                self.device, self.active, self.pcm = kwargs['device'], False, b''
                streams.append(self)
            def start(self): self.active = True
            def write(self, pcm): self.pcm += pcm
            def close(self): self.active = False
            def stop(self): self.active = False
            def abort(self): self.active = False
        player = AudioPlayer(Settings(), Output)
        player.voices = VoiceSettings(Settings())
        try:
            player.voices.set_output(device=7, volume=50)
            queue = asyncio.Queue()
            queue.put_nowait(AudioChunk(array('h', [1000] * 320).tobytes(), AudioFormat(16000)))
            queue.put_nowait(None)
            await player.play(queue)
            self.assertEqual(streams[0].device, 7)
            self.assertEqual(array('h', streams[0].pcm)[0], 500)
            player.voices.set_output(device=8, volume=0)
            queue.put_nowait(AudioChunk(array('h', [1000] * 320).tobytes(), AudioFormat(16000)))
            queue.put_nowait(None)
            await player.play(queue)
            self.assertEqual(streams[1].device, 8)
            self.assertFalse(streams[0].active)
            self.assertTrue(all(value == 0 for value in array('h', streams[1].pcm)))
            with patch('app.audio.play.sd.query_devices', return_value=[
                {'name': 'input', 'hostapi': 0, 'max_output_channels': 0},
                {'name': 'speaker', 'hostapi': 0, 'max_output_channels': 2}]), patch(
                    'app.audio.play.sd.query_hostapis', return_value=[{'name': 'MME'}]):
                devices = await player.output_devices()
            self.assertEqual([(device.index, device.name) for device in devices], [(1, 'speaker')])
        finally:
            await player.close()
