import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web

from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QStackedWidget

from app.ui.control_panel import load_window
from app.core.ai_settings import AIOptions, AISettings
from app.core.models import CaptionPart, SpeechPart, StageError
from app.core.conversation_input import ConversationInput
from app.core.voice_settings import VoiceSettings
from app.core.voice_runtime import monitor_voice_services
from app.core.voice_runtime import serve_conversations
from app.core.pipeline import Pipeline
from app.services.llm import LLMClient
from app.services.ai_connection import fetch_models, run_ai_commands, test_connection
from types import SimpleNamespace
from config import Settings


class AIControlDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_deepseek_is_default_and_existing_providers_remain(self):
        panel = load_window()
        try:
            combo = panel.findChild(QComboBox, 'aiProviderCombo')
            self.assertEqual(combo.currentText(), 'DeepSeek')
            self.assertEqual([combo.itemText(i) for i in range(combo.count())],
                             ['DeepSeek', 'OpenAI 兼容接口', '自定义接口'])
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()


class AIHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests, self.failures, self.disconnect = [], [], False
        self.failure_gate = None
        self.catalog_calls = 0
        self.arguments = json.dumps({'parts': [{'expression': '平常', 'japanese': 'こんにちは。', 'chinese': '你好。'}]}, ensure_ascii=False)
        app = web.Application()
        app.router.add_post('/v1/chat/completions', self.chat)
        app.router.add_post('/v1/beta/chat/completions', self.chat)
        app.router.add_get('/v1/models', self.models)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, '127.0.0.1', 0).start()
        self.base = f'http://127.0.0.1:{self.runner.addresses[0][1]}/v1'
        self.settings = replace(Settings(), llm_base_url=self.base, llm_model='test-model')
        self.ai = AISettings(self.settings)
        self.ai.update(AIOptions(provider='custom', base_url=self.base, model='test-model', require_key=False,
                                 temperature=.25, max_tokens=1536, retries=0))
        self.session = aiohttp.ClientSession()
        self.client = LLMClient(self.session, self.settings, ai=self.ai)

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def models(self, request):
        self.catalog_calls += 1
        return web.json_response({'data': [{'id': 'test-model'}, {'id': 'second-model'}]})

    async def chat(self, request):
        payload = await request.json()
        self.requests.append((request.path, request.headers.get('Authorization'), payload))
        if self.failure_gate is not None:
            await self.failure_gate.wait()
        if self.failures:
            return web.Response(status=self.failures.pop(0))
        tool = {'name': 'speak', 'arguments': self.arguments}
        if not payload['stream']:
            return web.json_response({'choices': [{'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{'type': 'function', 'function': tool}]}}]})
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        fragments = (self.arguments[:55], self.arguments[55:])
        for index, fragment in enumerate(fragments):
            event = {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {
                **({'name': 'speak'} if index == 0 else {}), 'arguments': fragment}}]}, 'finish_reason': None}]}
            await response.write(('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n').encode())
            if self.disconnect:
                await response.write_eof()
                return response
        await response.write(b'data: [DONE]\n\n')
        return response

    async def test_selected_provider_parameters_and_key_reach_actual_request(self):
        events = [event async for event in self.client.events('hello')]
        path, key, payload = self.requests[-1]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertIsNone(key)
        self.assertEqual((payload['temperature'], payload['max_tokens']), (.25, 1536))
        self.assertNotIn('thinking', payload)
        self.assertNotIn('strict', payload['tools'][0]['function'])
        self.assertTrue(any(isinstance(event, SpeechPart) for event in events))

    async def test_stream_off_uses_json_response_and_preserves_bilingual_output(self):
        self.ai.update(replace(self.ai.snapshot().options, streaming=False))
        events = [event async for event in self.client.events('hello')]
        self.assertFalse(self.requests[-1][2]['stream'])
        self.assertEqual([event.japanese for event in events if isinstance(event, SpeechPart)], ['こんにちは。'])
        self.assertEqual([event.chinese for event in events if isinstance(event, CaptionPart)][-1], '你好。')
        self.assertEqual(len(self.client.history.messages(20)), 2)

    async def test_reply_length_reaches_request_and_expands_short_sentence_capacity(self):
        self.ai.update(replace(self.ai.snapshot().options, reply_length=2000))
        self.arguments = json.dumps({'parts': [
            {'expression': '平常', 'japanese': 'こんにちは。', 'chinese': '你好。'} for _ in range(12)
        ]}, ensure_ascii=False)
        events = [event async for event in self.client.events('long reply')]
        payload = self.requests[-1][2]
        self.assertIn('2000字', payload['messages'][0]['content'])
        self.assertEqual(len([event for event in events if isinstance(event, SpeechPart)]), 12)
        self.assertEqual(payload['max_tokens'], 1536)
        self.assertNotIn('reply_length', payload)
        self.ai.update(replace(self.ai.snapshot().options, reply_length=0))
        self.arguments = json.dumps({'parts': [{'expression': '平常', 'japanese': 'はい。', 'chinese': '好的。'}]})
        _ = [event async for event in self.client.events('default reply')]
        self.assertNotIn('回复长度偏好', self.requests[-1][2]['messages'][0]['content'])

    async def test_reply_length_rejects_invalid_values_before_request(self):
        for value in (-1, 2001, True, 1.5):
            self.ai.update(replace(self.ai.snapshot().options, reply_length=value))
            with self.assertRaises(ValueError):
                _ = [event async for event in self.client.events('invalid')]
        self.assertEqual(self.requests, [])

    async def test_2000_character_reply_accepts_escaped_bilingual_json(self):
        self.ai.update(replace(self.ai.snapshot().options, reply_length=2000, max_tokens=16384))
        self.arguments = json.dumps({'parts': [
            {'expression': '平常', 'japanese': 'あ' * 125, 'chinese': '文' * 125} for _ in range(16)
        ]})
        events = [event async for event in self.client.events('full budget')]
        self.assertEqual(len([event for event in events if isinstance(event, SpeechPart)]), 16)
        final_captions = {event.part_id: event.chinese for event in events if isinstance(event, CaptionPart)}
        self.assertEqual(sum(map(len, final_captions.values())), 2000)

    async def test_transient_http_failure_retries_but_never_retries_authentication(self):
        self.ai.update(replace(self.ai.snapshot().options, retries=2))
        self.failures = [503]
        events = [event async for event in self.client.events('hello')]
        self.assertTrue(events)
        self.assertEqual(len(self.requests), 2)
        self.failures = [401]
        with self.assertRaises(StageError) as caught:
            _ = [event async for event in self.client.events('again')]
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(len(self.requests), 3)

    async def test_partial_stream_is_not_retried_and_does_not_enter_context(self):
        self.ai.update(replace(self.ai.snapshot().options, retries=2))
        self.disconnect = True
        with self.assertRaises(StageError):
            _ = [event async for event in self.client.events('hello')]
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.client.history.messages(20), [])
        self.assertEqual(self.requests[-1][2]['max_tokens'], self.ai.snapshot().options.max_tokens)

    async def test_request_uses_selected_timeout_and_preserves_one_turn_snapshot(self):
        timeouts = []
        real_session = self.session
        class RecordingSession:
            def post(self, *args, **kwargs):
                timeouts.append(kwargs['timeout'])
                return real_session.post(*args, **kwargs)
        self.client.session = RecordingSession()
        self.ai.update(replace(self.ai.snapshot().options, timeout=12, api_key='test-custom-key'))
        events = self.client.events('hello')
        async with __import__('contextlib').aclosing(events):
            first = await anext(events)
            self.ai.update(replace(self.ai.snapshot().options, model='new-model', streaming=False))
            rest = [event async for event in events]
        self.assertEqual(timeouts[0].total, 12)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][2]['model'], 'test-model')
        self.assertTrue(self.requests[0][2]['stream'])
        self.assertEqual(self.requests[0][1], 'Bearer test-custom-key')
        self.assertTrue(first or rest)

    async def test_catalog_and_manual_test_use_real_http_without_touching_dialogue_history(self):
        names = await fetch_models(self.session, self.ai.snapshot().options)
        self.assertEqual(names, ('test-model', 'second-model'))
        value = await test_connection(self.session, self.settings, self.ai.snapshot())
        self.assertEqual((value['caption'], value['japanese'], value['model']), ('你好。', 'こんにちは。', 'test-model'))
        self.assertGreaterEqual(value['latency_ms'], 0)
        self.assertEqual(self.client.history.messages(20), [])

    async def test_configuration_fix_unblocks_llm_without_restarting_program(self):
        inputs = ConversationInput()
        inputs.set_recording(False)
        voices = VoiceSettings(self.settings)
        voices.set_tts(replace(voices.snapshot().tts, auto_read=False))
        inputs.set_voice_preferences(auto_read=False, auto_send=True, interrupt=False)
        self.ai.update(replace(self.ai.snapshot().options, model='absent-model'))
        ui = SimpleNamespace(info=lambda *_: None, error=lambda *_: None)
        task = asyncio.create_task(monitor_voice_services(self.session, self.settings, inputs, voices, None,
                                                         ui, None, self.ai))
        try:
            await wait_until(lambda: inputs.service_blocked('LLM'))
            self.assertEqual(self.ai.snapshot().phase, 'error')
            self.ai.update(replace(self.ai.snapshot().options, model='test-model'))
            await wait_until(lambda: inputs.service_ready('LLM'))
            self.assertFalse(inputs.service_blocked('LLM'))
            self.assertEqual(self.ai.snapshot().phase, 'ready')
            self.assertGreaterEqual(self.catalog_calls, 2)
            self.assertEqual(self.requests, [], '自动预检不允许生成收费回复')
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_ui_commands_complete_with_real_model_list_and_test_response(self):
        ui = SimpleNamespace(error=lambda *_: None)
        inputs = ConversationInput()
        inputs.block_service('LLM')
        task = asyncio.create_task(run_ai_commands(self.session, self.settings, self.ai, ui, inputs))
        try:
            self.ai.request('models')
            await wait_until(lambda: not self.ai.result('models').running)
            self.assertEqual(self.ai.result('models').value, ('test-model', 'second-model'))
            self.ai.request('test')
            await wait_until(lambda: not self.ai.result('test').running)
            self.assertEqual(self.ai.result('test').value['caption'], '你好。')
            self.assertTrue(inputs.service_ready('LLM'))
            self.assertFalse(inputs.service_blocked('LLM'))
            self.failures = [401]
            self.ai.request('test')
            await wait_until(lambda: not self.ai.result('test').running)
            self.assertEqual(self.ai.result('test').value['status'], 401)
            self.assertIn('HTTP 401', self.ai.result('test').error)
            self.assertTrue(self.ai.result('test').value['time'])
            self.assertTrue(inputs.service_blocked('LLM'))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_old_request_failure_cannot_block_a_new_configuration(self):
        inputs = ConversationInput()
        inputs.bind_loop()
        inputs.set_recording(False)
        inputs.set_voice_preferences(auto_read=False, auto_send=True, interrupt=False)
        inputs.set_service_ready('LLM')
        voices = VoiceSettings(self.settings)
        voices.set_tts(replace(voices.snapshot().tts, auto_read=False))
        errors = []
        ui = SimpleNamespace(status=lambda *_: None, transcript=lambda *_: None, begin_reply=lambda *_: None,
                             end_reply=lambda *_: None, error=errors.append, info=lambda *_: None)
        pipeline = Pipeline(self.settings, None, self.client, None, None, ui, voices=voices)
        self.failures = [401]
        self.failure_gate = asyncio.Event()
        previous_revision = self.ai.snapshot().revision
        task = asyncio.create_task(serve_conversations(pipeline, inputs, voices, None, ui, (), lambda: self.client))
        try:
            inputs.submit_text('hello')
            await wait_until(lambda: self.requests)
            self.ai.update(replace(self.ai.snapshot().options, model='second-model'))
            self.failure_gate.set()
            await wait_until(lambda: not inputs.snapshot().busy)
            self.assertTrue(inputs.service_ready('LLM'), '旧配置返回401不能把已更换的新配置锁死')
            self.assertEqual(errors[0].configuration_revision, previous_revision)
        finally:
            self.failure_gate.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            inputs.unbind_loop()


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.005)


class AIStateTests(unittest.TestCase):
    def test_missing_static_ai_configuration_does_not_lock_the_live_settings_page(self):
        from config import startup_configuration_errors
        settings = replace(Settings(), llm_base_url='', llm_model='')
        errors = startup_configuration_errors(settings, services=(), check_references=False, check_service_fields=False)
        self.assertEqual(errors, [], '地址和模型应由运行配置预检，让用户能够在面板修复，而非锁死后台')
        with self.assertRaises(ValueError):
            settings.validate()  # 命令行完整检查仍应报告缺失的静态配置。

    def test_two_command_slots_replace_older_requests_and_reject_stale_results(self):
        ai = AISettings(Settings())
        old = ai.request('models')
        for _ in range(1000):
            last = ai.request('models')
        ai.complete('models', old, value=('obsolete',))
        self.assertTrue(ai.result('models').running)
        self.assertEqual(len(ai.commands()), 1)
        ai.complete('models', last, value=('current',))
        self.assertEqual(ai.result('models').value, ('current',))
        old_test = ai.request('test')
        ai.update(replace(ai.snapshot().options, temperature=.1))
        ai.complete('test', old_test, value={'caption': 'must-not-appear'})
        self.assertIsNone(ai.result('test').value)
        self.assertFalse(ai.result('test').running)

    def test_deepseek_and_compatible_endpoints_do_not_share_beta_fields(self):
        self.assertEqual(AIOptions(base_url='https://api.deepseek.com/v1').chat_url,
                         'https://api.deepseek.com/beta/chat/completions')
        self.assertEqual(AIOptions(base_url='https://api.deepseek.com/beta').models_url,
                         'https://api.deepseek.com/models')
        self.assertEqual(AIOptions(provider='custom', base_url='http://localhost:11434/v1').chat_url,
                         'http://localhost:11434/v1/chat/completions')

    def test_missing_key_points_to_console_url_and_ui(self):
        with self.assertRaises(ValueError) as caught:
            AIOptions(base_url='https://api.deepseek.com', model='test').validate()
        self.assertIn('https://platform.deepseek.com/api_keys', str(caught.exception))
        self.assertIn('AI服务页', str(caught.exception))
        self.assertNotIn('config.py', str(caught.exception))
        AIOptions(provider='custom', base_url='http://localhost/v1', require_key=False, model='test').validate()


class AIControlBusinessTests(AIControlDefaultsTests):
    def test_reply_length_range_and_provider_switch_reach_runtime(self):
        from PySide6.QtWidgets import QSpinBox
        length = self.panel.findChild(QSpinBox, 'replyLengthSpin')
        self.assertIsNotNone(length)
        self.assertEqual((length.minimum(), length.maximum(), length.value()), (0, 2000, 0))
        length.setValue(2000)
        self.assertEqual(self.ai.snapshot().options.reply_length, 2000)
        self.controls.w('aiProviderCombo').setCurrentIndex(2)
        self.assertEqual(self.ai.snapshot().options.reply_length, 2000)

    def test_long_reply_captions_are_not_dropped_during_live_length_changes(self):
        from app.ui.console import ConsoleUI
        ui = ConsoleUI(2)
        ui.ai_settings = self.ai
        ui.begin_reply(1)
        self.ai.update(replace(self.ai.snapshot().options, reply_length=2000))
        self.ai.update(replace(self.ai.snapshot().options, reply_length=0))
        for part in range(18):
            combined = ui.caption(1, part, '文')
        self.assertEqual(combined, '文' * 18)
        self.assertIsNone(ui.caption(1, 32, '越界'))
        ui.begin_reply(2)
        self.assertIsNone(ui.caption(2, 32, '越界'))

    def setUp(self):
        self.panel = load_window()
        self.ai = AISettings(Settings())
        self.controls = self.panel.ai_controls
        self.controls.bind_runtime(self.ai, ConversationInput())

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_switching_provider_isolates_keys_and_preserves_user_configuration(self):
        c = self.controls
        c.w('aiProviderCombo').setCurrentIndex(2)
        self.assertEqual(c.w('apiKeyEdit').text(), '')
        c.w('baseUrlEdit').setText('http://localhost/v1')
        c.w('apiKeyEdit').setText('test-custom-private')
        c.w('llmModelCombo').setCurrentText('custom-model')
        c.w('temperatureSpin').setValue(.3)
        c.save()
        c.w('aiProviderCombo').setCurrentIndex(0)
        self.assertNotEqual(c.w('apiKeyEdit').text(), 'test-custom-private')
        self.assertEqual(c.w('temperatureSpin').value(), .3)
        c.w('aiProviderCombo').setCurrentIndex(2)
        self.assertEqual(self.ai.snapshot().options.api_key, 'test-custom-private')
        self.assertEqual(self.ai.snapshot().options.model, 'custom-model')

    def test_model_list_populates_editable_selection_and_changes_actual_model(self):
        c = self.controls
        id = self.ai.request('models')
        self.ai.complete('models', id, value=('model-a', 'model-b'))
        c.refresh()
        self.assertEqual(c.w('llmModelCombo').count(), 2)
        c.w('llmModelCombo').setCurrentIndex(1)
        self.assertEqual(self.ai.snapshot().options.model, 'model-b')

    def test_parameters_reach_runtime_and_connection_result_describes_current_configuration(self):
        c = self.controls
        c.w('maxTokensSpin').setValue(1536)
        c.w('timeoutSpin').setValue(45)
        c.w('retrySpin').setValue(0)
        c.w('apiStreamingCheck').setChecked(False)
        options = self.ai.snapshot().options
        self.assertEqual((options.max_tokens, options.timeout, options.retries, options.streaming), (1536, 45, 0, False))
        id = self.ai.request('test')
        self.ai.complete('test', id, value={'latency_ms': 42, 'model': options.model, 'time': '2026-10-20 10:00:00',
                                          'caption': '你好', 'japanese': 'こんにちは', 'streaming': False})
        c.refresh()
        self.assertEqual(c.w('connectionStateLabel').text(), '连接成功')
        self.assertEqual(c.w('latencyValue').text(), '42 ms')
        self.assertIn('你好', c.w('connectionResultEdit').toPlainText())
        self.ai.health(self.ai.snapshot().revision, 'error', '实际对话请求失败')
        c.refresh()
        self.assertEqual(c.w('connectionStateLabel').text(), '连接异常')
        self.assertIn('实际对话请求失败', c.w('connectionGuide').text())
        c.w('temperatureSpin').setValue(.2)
        self.assertEqual(c.w('latencyValue').text(), '— ms')
        self.assertNotEqual(c.w('connectionStateLabel').text(), '连接成功')

    def test_reset_button_only_resets_ai_page_and_default_interrupt_stays_off(self):
        c = self.controls
        c.w('temperatureSpin').setValue(.1)
        self.panel.findChild(QPushButton, 'resetButton').click()
        self.assertEqual(self.ai.snapshot().options.temperature, .1)
        self.panel.findChild(QPushButton, 'navAI').click()
        self.panel.findChild(QPushButton, 'resetButton').click()
        self.assertEqual(self.ai.snapshot().options.temperature, .7)
        self.assertFalse(self.panel.voice_controls.w('interruptSpeechCheck').isChecked())
