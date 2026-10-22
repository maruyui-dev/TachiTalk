import json
from dataclasses import replace
import unittest

from config import Settings
from app.services.llm import ReplyParser
from app.core.models import CaptionPart, SpeechPart, StageError


class BilingualParserTests(unittest.TestCase):
    def settings(self, **changes):
        return replace(Settings(), available_expressions=("平常", "疑问", "紧张"), **changes)

    def test_japanese_is_ready_while_chinese_is_still_incomplete(self):
        parser = ReplyParser(self.settings())
        events = parser.feed('{"parts":[{"expression":"平常","japanese":"こんにちは。","chinese":"你')
        self.assertEqual(events, [SpeechPart(0, "こんにちは。", "平常")])
        self.assertEqual(parser.feed('好。"}]}'), [CaptionPart(0, "你好。")])
        parser.finish()

    def test_streaming_caption_is_updated_before_its_json_string_closes(self):
        parser = ReplyParser(self.settings())
        parser.stream_captions = True
        prefix = '{"parts":[{"expression":"平常","japanese":"こんにちは。","chinese":"'
        events = parser.feed(prefix + '你')
        self.assertIn(CaptionPart(0, '你'), events)
        self.assertEqual(parser.feed('好'), [CaptionPart(0, '你好')])
        self.assertEqual(parser.feed('。"}]}'), [CaptionPart(0, '你好。')])
        parser.finish()

    def test_streaming_escapes_never_show_half_unicode_or_duplicate_final_text(self):
        parser = ReplyParser(self.settings())
        parser.stream_captions = True
        caption = '你好😀 "A" \\ \nOK'
        payload = json.dumps({'parts': [{'expression': '平常', 'japanese': 'はい。', 'chinese': caption}]})
        captions = []
        for char in payload:
            for event in parser.feed(char):
                if isinstance(event, CaptionPart):
                    event.chinese.encode('utf-8')
                    captions.append(event.chinese)
        parser.finish()
        self.assertGreater(len(captions), 1)
        self.assertEqual(captions[-1], caption)
        self.assertEqual(len(captions), len(set(captions)))
        self.assertTrue(all(caption.startswith(text) for text in captions))

    def test_field_reordering_preserves_pair_identity(self):
        parser = ReplyParser(self.settings())
        events = parser.feed('{"parts":[{"chinese":"回来啦。","japanese":"おかえり。","expression":"疑问"}]}')
        self.assertEqual(events, [CaptionPart(0, "回来啦。"), SpeechPart(0, "おかえり。", "疑问")])
        parser.finish()

    def test_every_character_boundary_preserves_quotes_and_unicode(self):
        parser = ReplyParser(self.settings())
        japanese = '「A」\\"\nおはよう。'
        payload = json.dumps({"parts": [{"expression": "平常", "japanese": japanese, "chinese": "早上好。"}]})
        events = []
        for char in payload:
            events.extend(parser.feed(char))
        parser.finish()
        self.assertEqual(events, [SpeechPart(0, japanese, "平常"), CaptionPart(0, "早上好。")])

    def test_unknown_or_missing_expression_warns_and_uses_real_default(self):
        for item in ({"expression": "开心", "japanese": "はい。", "chinese": "好。"},
                     {"japanese": "はい。", "chinese": "好。"},
                     {"expression": 100, "japanese": "はい。", "chinese": "好。"}):
            parser = ReplyParser(self.settings())
            with self.assertLogs("tachitalk", level="WARNING"):
                events = parser.feed(json.dumps({"parts": [item]}))
            parser.finish()
            self.assertIn(SpeechPart(0, "はい。", "平常"), events)

    def test_missing_translation_does_not_hold_back_valid_speech(self):
        parser = ReplyParser(self.settings())
        with self.assertLogs("tachitalk", level="WARNING"):
            events = parser.feed('{"parts":[{"expression":"平常","japanese":"はい。"}]}')
        self.assertEqual(events, [SpeechPart(0, "はい。", "平常")])
        parser.finish()

    def test_missing_japanese_is_reported_without_fake_speech(self):
        parser = ReplyParser(self.settings())
        with self.assertLogs("tachitalk", level="WARNING"):
            events = parser.feed('{"parts":[{"expression":"平常","chinese":"你好。"}]}')
        self.assertEqual(events, [CaptionPart(0, "你好。")])
        with self.assertRaises(StageError):
            parser.finish()

    def test_part_count_and_text_buffers_are_bounded(self):
        item = {"expression": "平常", "japanese": "はい。", "chinese": "好。"}
        with self.assertRaises(StageError):
            ReplyParser(self.settings(max_reply_parts=1)).feed(json.dumps({"parts": [item, item]}))
        with self.assertRaises(StageError):
            ReplyParser(self.settings(max_llm_chars=20)).feed(" " * 21)

    def test_duplicate_fields_are_rejected(self):
        with self.assertRaises(StageError):
            ReplyParser(self.settings()).feed('{"parts":[{"expression":"平常","expression":"紧张"}]}')

    def test_incomplete_final_json_remains_an_error(self):
        parser = ReplyParser(self.settings())
        parser.feed('{"parts":[{"expression":"平常","japanese":"はい。","chinese":"好。"}')
        with self.assertRaises(StageError):
            parser.finish()

    def test_empty_response_is_not_a_success(self):
        parser = ReplyParser(self.settings())
        parser.feed('{"parts":[]}')
        with self.assertRaises(StageError):
            parser.finish()
