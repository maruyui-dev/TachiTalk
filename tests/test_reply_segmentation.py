"""Small local HTTP fixtures for complete replies delivered as chat-sized parts.

No account, production profile, microphone, voice runtime, or external API is used.
"""
import asyncio
from dataclasses import replace
import json
import logging
from types import SimpleNamespace
import unittest

import aiohttp
from aiohttp import web

from config import Settings
from app.core.ai_settings import AIOptions, AISettings
from app.core.models import CaptionPart, SpeechPart, StageError
from app.core.persona import PersonaProfile
from app.services.llm import LLMClient
from app.ui.console import ConsoleUI
from app.ui.runtime_console import ConsoleLogHandler


class ReplySegmentationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.parts = [self.part(index) for index in range(4)]
        self.requests = []
        self.first_part_sent = asyncio.Event()
        self.release_rest = None
        app = web.Application()
        app.router.add_post('/v1/chat/completions', self.chat)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, '127.0.0.1', 0).start()
        base = f'http://127.0.0.1:{self.runner.addresses[0][1]}/v1'
        self.settings = replace(Settings(), llm_base_url=base, llm_model='offline-fixture')
        self.ai = AISettings(self.settings)
        self.ai.update(AIOptions(provider='custom', base_url=base,
                                 model='offline-fixture', require_key=False, retries=0))
        self.session = aiohttp.ClientSession()
        self.client = LLMClient(self.session, self.settings, ai=self.ai)

    async def asyncTearDown(self):
        if self.release_rest is not None:
            self.release_rest.set()
        await self.session.close()
        await self.runner.cleanup()

    @staticmethod
    def part(index):
        return {'expression': '平常', 'japanese': f'手紙の話、その{index + 1}です。',
                'chinese': f'纸条上的第{index + 1}段。'}

    async def chat(self, request):
        payload = await request.json()
        self.requests.append(payload)
        arguments = json.dumps({'parts': self.parts}, ensure_ascii=False, separators=(',', ':'))
        if not payload['stream']:
            return web.json_response({'choices': [{'finish_reason': 'tool_calls', 'message': {
                'content': None, 'tool_calls': [{'type': 'function', 'function': {
                    'name': 'speak', 'arguments': arguments}}]}}]})
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        # Split exactly after the first complete part; the rest may be held to
        # prove the consumer sees a real part before generation has finished.
        first = '{"parts":[' + json.dumps(self.parts[0], ensure_ascii=False, separators=(',', ':'))
        rest = arguments[len(first):]
        for index, fragment in enumerate((first, rest)):
            if index and self.release_rest is not None:
                await self.release_rest.wait()
            event = {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {
                **({'name': 'speak'} if index == 0 else {}), 'arguments': fragment}}]},
                'finish_reason': None}]}
            await response.write(('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n').encode())
            if not index:
                self.first_part_sent.set()
        await response.write(b'data: [DONE]\n\n')
        return response

    async def complete_reply(self, text, **kwargs):
        try:
            return [event async for event in self.client.events(text, **kwargs)]
        except StageError as error:
            self.fail(f'A valid segmented reply must complete instead of aborting: {error}')

    async def test_short_followup_keeps_a_complete_segmented_story_reply(self):
        self.client.history.append('我想听一个小故事', '旧故事背景', 20)
        events = await self.complete_reply('什么纸条?')
        captions = {event.part_id: event.chinese for event in events if isinstance(event, CaptionPart)}
        self.assertEqual(captions, {index: part['chinese'] for index, part in enumerate(self.parts)})
        self.assertEqual([event.part_id for event in events if isinstance(event, SpeechPart)], list(range(4)))
        messages = self.client.history.messages(20)
        self.assertEqual(len(messages), 4, 'All parts must remain one complete conversation turn')
        self.assertEqual(json.loads(messages[-1]['content'])['parts'], self.parts)
        self.assertEqual(len(self.requests), 1, 'Do not retry or start another model request after partial output')

    async def test_long_reply_can_use_many_natural_short_parts_without_keyword_gate(self):
        self.parts = [self.part(index) for index in range(12)]
        events = await self.complete_reply('请继续说下去')
        captions = {event.part_id: event.chinese for event in events if isinstance(event, CaptionPart)}
        self.assertEqual(list(captions.values()), [part['chinese'] for part in self.parts])
        self.assertEqual(self.requests[0]['max_tokens'], self.ai.snapshot().options.max_tokens)

    async def test_disabling_token_streaming_keeps_separate_complete_caption_parts(self):
        self.parts = self.parts[:2]
        profile = replace(PersonaProfile(), stream_reply=False)
        events = await self.complete_reply('你好', profile=profile)
        captions = [event for event in events if isinstance(event, CaptionPart)]
        self.assertEqual(captions, [CaptionPart(index, part['chinese'])
                                    for index, part in enumerate(self.parts)])

    async def test_nonstreaming_http_response_also_keeps_distinct_parts(self):
        self.parts = self.parts[:2]
        self.ai.update(replace(self.ai.snapshot().options, streaming=False))
        profile = replace(PersonaProfile(), stream_reply=False)
        events = await self.complete_reply('你好', profile=profile)
        self.assertEqual([event for event in events if isinstance(event, CaptionPart)],
                         [CaptionPart(index, part['chinese']) for index, part in enumerate(self.parts)])

    async def test_first_caption_arrives_before_later_parts_are_generated(self):
        self.parts = self.parts[:2]
        self.release_rest = asyncio.Event()
        received = []
        first_caption = asyncio.Event()

        async def collect():
            async for event in self.client.events('你好'):
                received.append(event)
                if isinstance(event, CaptionPart):
                    first_caption.set()

        task = asyncio.create_task(collect())
        try:
            await asyncio.wait_for(first_caption.wait(), timeout=2)
            self.assertFalse(task.done(), 'The rest of the model response has not been sent yet')
            self.assertEqual([event.chinese for event in received if isinstance(event, CaptionPart)],
                             [self.parts[0]['chinese']])
        finally:
            self.release_rest.set()
            await asyncio.wait_for(task, timeout=2)
        self.assertEqual([event.part_id for event in received if isinstance(event, CaptionPart)], [0, 1])


class ImportantLogTests(unittest.TestCase):
    def test_default_logs_omit_chat_and_frequent_status_but_keep_important_events(self):
        ui = ConsoleUI(max_parts=4)
        with self.assertLogs('tachitalk', level='INFO') as captured:
            ui.status('正在等待AI生成回复')
            ui.status('正在合成语音，等待首段音频')
            ui.transcript('用户聊天正文示例')
            ui.begin_reply(1)
            self.assertEqual(ui.caption(1, 0, '桌宠第一段。'), '桌宠第一段。')
            self.assertEqual(ui.caption(1, 1, '桌宠第二段。'), '桌宠第一段。桌宠第二段。')
            ui.end_reply(1)
            ui.info('组件校验完成')
            ui.error(StageError('LLM', '请求失败示例'))
        messages = '\n'.join(record.getMessage() for record in captured.records)
        for noise in ('用户聊天正文示例', '桌宠第一段', '桌宠第二段',
                      '正在等待AI生成回复', '正在合成语音'):
            self.assertNotIn(noise, messages)
        self.assertIn('组件校验完成', messages)
        self.assertIn('请求失败示例', messages)
        self.assertTrue(any(record.levelno == logging.ERROR for record in captured.records))

    def test_runtime_console_does_not_reenable_debug_noise_by_default(self):
        emitted = []
        console = SimpleNamespace(active=True, output=SimpleNamespace(
            emit=lambda text, level: emitted.append((text, level))))
        handler = ConsoleLogHandler(console)
        logger = logging.getLogger('tachitalk.fixture-important-log')
        original = logger.level, logger.propagate, list(logger.handlers)
        try:
            logger.handlers = [handler]
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            logger.debug('切换页面：角色设置')
            logger.info('安装完成示例')
            logger.error('恢复失败示例')
        finally:
            logger.setLevel(original[0])
            logger.propagate = original[1]
            logger.handlers = original[2]
            handler.close()
        text = ''.join(message for message, _ in emitted)
        self.assertNotIn('切换页面', text)
        self.assertIn('安装完成示例', text)
        self.assertIn('恢复失败示例', text)


if __name__ == '__main__':
    unittest.main()
