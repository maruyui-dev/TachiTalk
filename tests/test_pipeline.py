import asyncio
from dataclasses import replace
from time import perf_counter, sleep
from types import SimpleNamespace
import unittest

from config import Settings
from app.core.models import AudioChunk, AudioFormat, AudioSegment, CaptionPart, SpeechPart, StageError
from app.core.pipeline import Pipeline
from app.audio.play import AudioPlayer
from app.core.persona import PersonaStore


class TestUI:
    def __init__(self):
        self.messages = []
        self.first_audio = asyncio.Event()

    def status(self, text):
        self.messages.append(text)
        if text.startswith("播放回复"):
            self.first_audio.set()

    def info(self, text):
        self.messages.append(text)

    def transcript(self, text):
        self.messages.append(text)

    def begin_reply(self, turn_id):
        self.turn_id = turn_id

    def caption(self, turn_id, part_id, text):
        self.messages.append(text)

    def part_started(self, turn_id, part_id, expression):
        self.expression = expression

    def end_reply(self, turn_id):
        self.finished_turn = turn_id

    def timings(self, values):
        self.metrics = values


class TestOutput:
    instances = []

    def __init__(self, **kwargs):
        self.active = False
        self.blocks = []
        self.aborted = False
        self.closed = False
        self.instances.append(self)

    def start(self):
        self.active = True

    def write(self, data):
        sleep(.002)
        self.blocks.append(data)
        return False

    def stop(self):
        self.active = False

    def abort(self):
        self.aborted = True
        self.active = False

    def close(self):
        self.closed = True
        self.active = False


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        TestOutput.instances = []
        self.settings = Settings()
        self.ui = TestUI()
        self.player = AudioPlayer(self.settings, TestOutput)
        self.segment = AudioSegment(b"\0\0" * 320, AudioFormat(16000), perf_counter())

    async def asyncTearDown(self):
        await self.player.close()

    async def test_empty_asr_does_not_call_llm_or_tts(self):
        async def transcribe(_):
            return ""
        pipeline = Pipeline(self.settings, SimpleNamespace(transcribe=transcribe), None, None, self.player, self.ui)
        await pipeline.process(self.segment)
        self.assertEqual(TestOutput.instances, [])
        self.assertEqual(len(pipeline.history), 0)

    async def test_failed_output_device_is_closed_before_the_next_turn(self):
        class FailedOutput(TestOutput):
            def write(self, data):
                raise RuntimeError("device removed")

        self.player.stream_factory = FailedOutput
        queue = asyncio.Queue()
        for _ in range(3):
            queue.put_nowait(AudioChunk(b"\1\0" * 640, AudioFormat(32000)))
        queue.put_nowait(None)
        with self.assertRaises(StageError):
            await self.player.play(queue)
        self.assertTrue(TestOutput.instances[0].closed)

    async def test_expression_events_follow_played_part_boundaries(self):
        queue = asyncio.Queue(maxsize=10)
        for part_id, expression in ((0, "平常"), (1, "疑问")):
            for _ in range(3):
                queue.put_nowait(AudioChunk(b"\1\0" * 640, AudioFormat(32000), part_id, expression))
        queue.put_nowait(None)
        boundaries = []
        await self.player.play(queue, on_part_start=lambda index, expression, timestamp:
                               boundaries.append((index, expression, len(TestOutput.instances[0].blocks))))
        self.assertEqual(boundaries, [(0, "平常", 1), (1, "疑问", 4)])

    async def test_playback_starts_before_llm_finishes_and_reuses_output_stream(self):
        events = []

        async def transcribe(_):
            return "你好"

        async def sentences(_, **_options):
            yield SpeechPart(0, "こんにちは。", "平常")
            await asyncio.wait_for(self.ui.first_audio.wait(), 2)
            yield CaptionPart(0, "你好。")
            events.append("llm_finished")

        async def stream(_):
            for _ in range(40):
                yield AudioChunk(b"\1\0" * 640, AudioFormat(32000))
                await asyncio.sleep(.001)
            events.append("tts_finished")

        pipeline = Pipeline(self.settings, SimpleNamespace(transcribe=transcribe),
                            SimpleNamespace(events=sentences), SimpleNamespace(stream=stream), self.player, self.ui)
        await asyncio.wait_for(pipeline.process(self.segment), 3)
        self.assertTrue(self.ui.first_audio.is_set())
        self.assertEqual(len(TestOutput.instances[0].blocks), 40)
        self.assertLessEqual(pipeline.last_metrics["audio_queue_high_water"], self.settings.playback_queue_size)
        self.assertLessEqual(pipeline.last_metrics["sentence_queue_high_water"], 2)
        self.assertEqual(events, ["llm_finished", "tts_finished"])
        metrics = pipeline.last_metrics
        self.assertIn('japanese_to_tts_seconds', metrics)
        self.assertAlmostEqual(metrics['japanese_to_first_audio_seconds'],
                               metrics['japanese_to_tts_seconds'] + metrics['tts_first_chunk_seconds']
                               + metrics['first_chunk_to_play_seconds'])
        self.assertGreaterEqual(metrics['tts_stream_seconds'], metrics['tts_first_chunk_seconds'])
        self.assertIn("你好。", self.ui.messages)
        self.assertEqual(self.ui.finished_turn, self.ui.turn_id)
        await pipeline.process(self.segment)
        self.assertEqual(len(TestOutput.instances), 1)
        self.assertFalse(TestOutput.instances[0].active)

    async def test_voice_reference_stays_fixed_per_turn_while_portrait_changes(self):
        recorded, portraits = [], []
        first_expression = '疑问'
        async def events(_, **options):
            yield SpeechPart(0, '今日はよく頑張ったね。', first_expression)
            yield CaptionPart(0, '今天辛苦了。')
            yield SpeechPart(1, '少し休んでね。', '平常')
        async def stream(part):
            recorded.append((part.expression, part.voice_expression))
            for _ in range(3):
                yield AudioChunk(b'\1\0' * 640, AudioFormat(32000), part.part_id, part.expression)
        self.ui.part_started = lambda turn, part, expression: portraits.append(expression)
        pipeline = Pipeline(self.settings, None, SimpleNamespace(events=events),
                            SimpleNamespace(stream=stream), self.player, self.ui)
        await pipeline.process_text('第一轮')
        self.assertEqual(recorded, [('疑问', '疑问'), ('平常', '疑问')])
        self.assertEqual(portraits, ['疑问', '平常'])
        first_expression = '紧张'
        recorded.clear()
        await pipeline.process_text('下一轮')
        self.assertEqual(recorded, [('紧张', '紧张'), ('平常', '紧张')])

    async def test_audio_reference_is_locked_even_if_later_sentence_requests_another(self):
        from app.core.audio_library import AudioReference
        first = AudioReference('first', '温柔', 'D:/first.wav', 'こんにちは。')
        other = replace(first, key='other', name='开心', path='D:/other.wav')
        recorded = []
        async def events(_, **options):
            yield SpeechPart(0, 'こんにちは。', '疑问', audio_reference=first)
            yield SpeechPart(1, '休みましょう。', '平常', audio_reference=other)
        async def stream(part):
            recorded.append((part.expression, part.audio_reference))
            yield AudioChunk(b'\1\0' * 640, AudioFormat(32000), part.part_id, part.expression)
        pipeline = Pipeline(self.settings, None, SimpleNamespace(events=events),
                            SimpleNamespace(stream=stream), self.player, self.ui)
        await pipeline.process_text('测试')
        self.assertEqual(recorded, [('疑问', first), ('平常', first)])

    async def test_buffered_llm_yields_to_tts_before_reading_later_translation(self):
        order = []

        async def transcribe(_):
            return "你好"

        async def events(_, **_options):
            yield SpeechPart(0, "はい。", "平常")
            order.append("later_translation")
            yield CaptionPart(0, "好。")

        async def stream(part):
            order.append("tts_requested")
            yield AudioChunk(b"\1\0" * 640, AudioFormat(32000), 0, "平常")

        pipeline = Pipeline(self.settings, SimpleNamespace(transcribe=transcribe),
                            SimpleNamespace(events=events), SimpleNamespace(stream=stream), self.player, self.ui)
        await pipeline.process(self.segment)
        self.assertEqual(order, ["tts_requested", "later_translation"])

    async def test_expression_switch_affects_portrait_only_and_uses_a_turn_snapshot(self):
        profiles = PersonaStore()
        profiles.update(character_name='茉子', user_name='', reply_language='简体中文', persona_prompt='', switch_expression=False)
        visible, spoken = [], []
        self.ui.part_started = lambda turn, part, expression: visible.append(expression)

        async def events(_, **options):
            yield SpeechPart(0, 'はい。', '疑问')
            yield CaptionPart(0, '好。')

        async def stream(part):
            spoken.append(part.expression)
            profiles.update(character_name='茉子', user_name='', reply_language='简体中文', persona_prompt='', switch_expression=True)
            yield AudioChunk(b'\1\0' * 640, AudioFormat(32000), part.part_id, part.expression)

        settings = replace(self.settings, available_expressions=('平常', '疑问'))
        pipeline = Pipeline(settings, None, SimpleNamespace(events=events), SimpleNamespace(stream=stream),
                            self.player, self.ui, profiles)
        await pipeline.process_text('第一轮固定平常')
        self.assertTrue(visible)
        self.assertEqual(set(visible), {'平常'})
        self.assertEqual(spoken, ['疑问'], '关闭立绘表情切换不能改变TTS参考情绪')
        visible.clear()
        await pipeline.process_text('第二轮恢复表情')
        self.assertEqual(visible, ['疑问'])

    async def test_rebuilding_pipeline_does_not_reuse_old_ui_turn_ids(self):
        async def transcribe(_):
            return "你好"

        async def events(_, **_options):
            yield SpeechPart(0, "はい。", "平常")
            yield CaptionPart(0, "好。")

        async def stream(_):
            yield AudioChunk(b"\1\0" * 640, AudioFormat(32000), 0, "平常")

        def pipeline():
            return Pipeline(self.settings, SimpleNamespace(transcribe=transcribe),
                            SimpleNamespace(events=events), SimpleNamespace(stream=stream), self.player, self.ui)

        await pipeline().process(self.segment)
        previous = self.ui.turn_id
        await pipeline().process(self.segment)
        self.assertGreater(self.ui.turn_id, previous)

    async def test_tts_error_cancels_waiting_llm_and_preserves_error_status(self):
        llm_closed = asyncio.Event()

        async def transcribe(_):
            return "你好"

        async def sentences(_, **_options):
            try:
                yield SpeechPart(0, "はい。", "平常")
                await asyncio.Event().wait()
            finally:
                llm_closed.set()

        async def stream(_):
            raise StageError("TTS", "服务拒绝请求", 401)
            yield

        pipeline = Pipeline(self.settings, SimpleNamespace(transcribe=transcribe),
                            SimpleNamespace(events=sentences), SimpleNamespace(stream=stream), self.player, self.ui)
        with self.assertRaises(StageError) as caught:
            await asyncio.wait_for(pipeline.process(self.segment), 2)
        self.assertEqual(caught.exception.status, 401)
        self.assertTrue(llm_closed.is_set())

    async def test_cancellation_closes_infinite_audio_producer_and_aborts_output(self):
        producer_closed = asyncio.Event()
        produced = 0

        async def transcribe(_):
            return "继续"

        async def sentences(_, **_options):
            yield SpeechPart(0, "はい。", "平常")

        async def stream(_):
            nonlocal produced
            try:
                while True:
                    produced += 1
                    yield AudioChunk(b"\1\0" * 640, AudioFormat(32000))
            finally:
                producer_closed.set()

        pipeline = Pipeline(self.settings, SimpleNamespace(transcribe=transcribe),
                            SimpleNamespace(events=sentences), SimpleNamespace(stream=stream), self.player, self.ui)
        task = asyncio.create_task(pipeline.process(self.segment))
        await asyncio.wait_for(self.ui.first_audio.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(producer_closed.is_set())
        self.assertTrue(TestOutput.instances[0].aborted)
        self.assertLess(produced, 100)
