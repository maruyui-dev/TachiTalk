"""Emotion guidance follows the live resource snapshot without banning surprise."""
from dataclasses import replace
import unittest

from config import REF_MAP, Settings
from app.core.expressions import ExpressionSnapshot
from app.core.models import SpeechPart
from app.services.llm import LLMClient, ReplyParser


class EmotionPrecisionTests(unittest.TestCase):
    def setUp(self):
        self.expressions = ExpressionSnapshot(tuple(REF_MAP), '平常')
        self.client = LLMClient(None, Settings())

    def test_system_rules_distinguish_similar_emotions_and_raise_surprise_threshold(self):
        profile = replace(self.client.profiles.snapshot(), persona_prompt='为了活泼，每句话都要惊讶！')
        prompt = self.client.system_prompt(profile, self.expressions, audio=None)
        rules = prompt[prompt.index('## 本轮实际设置与程序协议'):]
        for meaning in ('期待落地', '放下心', '信息不清', '自己的局促', '对方的处境', '显著超出预期'):
            self.assertIn(meaning, rules)
        self.assertIn('普通问句', rules)
        self.assertIn('不为变化而强行切换', rules)
        self.assertIn('不确定时', rules)

    def test_tool_schema_keeps_surprise_available_but_explains_its_rare_use(self):
        schema = self.client.reply_tool(expressions=self.expressions, audio=None)
        field = schema['function']['parameters']['properties']['parts']['items']['properties']['expression']
        self.assertIn('惊讶', field['enum'])
        self.assertIn('显著超出预期', field.get('description', ''))
        self.assertIn('开心', field['description'])
        self.assertIn('欣慰', field['description'])

    def test_guidance_does_not_offer_removed_emotions_or_invent_an_enum(self):
        snapshot = ExpressionSnapshot(('平常', '开心'), '平常')
        schema = self.client.reply_tool(expressions=snapshot, audio=None)
        field = schema['function']['parameters']['properties']['parts']['items']['properties']['expression']
        self.assertEqual(field['enum'], ['平常', '开心'])
        self.assertNotIn('惊讶', field.get('description', ''))
        self.assertNotIn('欣慰', field.get('description', ''))

    def test_parser_preserves_an_allowed_genuine_surprise_and_speech_timing(self):
        parser = ReplyParser(Settings(), expressions=self.expressions)
        events = parser.feed('{"parts":[{"expression":"惊讶","japanese":"まさか、本当に当選したの？"')
        speech = [e for e in events if isinstance(e, SpeechPart)]
        self.assertEqual(len(speech), 1)
        self.assertEqual(speech[0].expression, '惊讶')
        parser.feed(',"chinese":"居然真的中奖了？"}]}')
        parser.finish()

    def test_daily_companion_can_tell_stories_and_teach_without_game_only_constraints(self):
        prompt = self.client.system_prompt(self.client.profiles.snapshot(), self.expressions, audio=None)
        for rule in ('不受游戏世界观限制', '有起因、发展和结尾', '必要步骤、理由和结果', '不编造共同经历'):
            self.assertIn(rule, prompt)
        from config import PROMPT
        self.assertNotIn('不要解释、不要补充背景', PROMPT)
        self.assertNotIn('你能看到用户在用电脑', PROMPT)


class LongFormRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_story_has_room_for_multiple_parts_without_forcing_long_everyday_chat(self):
        import json
        from app.core.ai_settings import AISettings, AIOptions
        ai = AISettings(Settings())
        ai.update(AIOptions(provider='custom', base_url='http://127.0.0.1:1', require_key=False, model='fixture'))
        client = LLMClient(None, Settings(), ai=ai)
        requests = []
        async def request(options, profile, payload, parser, progress):
            requests.append(payload)
            data = json.dumps({'parts': [{'expression': '平常', 'japanese': '森で鈴が鳴った。',
                'chinese': f'故事第{i}段。'} for i in range(4)]})
            for event in parser.feed(data):
                yield event
            parser.finish()
        client._request = request
        events = [event async for event in client.events('讲一个完整的睡前故事')]
        self.assertEqual(len([e for e in events if isinstance(e, SpeechPart)]), 4)
        self.assertIn('最多8组', requests[-1]['messages'][0]['content'])
        self.assertNotIn('回复长度偏好', requests[-1]['messages'][0]['content'])


if __name__ == '__main__':
    unittest.main()
