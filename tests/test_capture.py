from dataclasses import replace
import asyncio
from threading import Event
import unittest
from unittest.mock import patch

from config import Settings
from app.audio.record import AudioCapture, TurnGate
from app.core.conversation_input import ConversationInput


class CaptureTests(unittest.TestCase):
    frame = b"\0\0" * 320

    def feed(self, capture, count, speech, start=0):
        for number in range(count):
            capture.accept_frame(self.frame, speech=speech, now=(start + number) * .02)

    def test_silence_never_enters_the_downstream_queue(self):
        capture = AudioCapture(Settings(), TurnGate())
        self.feed(capture, 180000, False)
        self.assertEqual(capture.segments.qsize(), 0)
        self.assertLessEqual(len(capture.segmenter.pre_roll), 15)

    def test_slow_consumer_can_have_only_one_turn(self):
        gate = TurnGate()
        capture = AudioCapture(replace(Settings(), max_segment_seconds=1), gate)
        self.feed(capture, 10000, True)
        self.assertTrue(gate.busy)
        self.assertEqual(capture.segments.qsize(), 1)
        self.assertLessEqual(capture.segments.get_nowait().duration, 1)
        self.assertEqual(capture.queue_high_water, 1)
        self.assertEqual(len(capture.segmenter.frames), 0)

    def test_busy_audio_is_not_replayed_after_release(self):
        gate = TurnGate()
        capture = AudioCapture(Settings(), gate)
        gate.claim()
        self.feed(capture, 1000, True)
        gate.release()
        self.feed(capture, 100, True)
        self.assertFalse(capture.segmenter.active)
        self.feed(capture, 10, False)
        self.feed(capture, 10, True)
        self.assertTrue(capture.segmenter.active)

    def test_gate_claim_is_atomic_and_does_not_allow_duplicate_reservation(self):
        gate = TurnGate()
        self.assertTrue(gate.claim())
        self.assertFalse(gate.claim())
        gate.release()
        self.assertTrue(gate.claim())

    def test_settings_reject_unbounded_queue(self):
        with self.assertRaises(ValueError):
            replace(Settings(), segment_queue_size=0).validate()

    def test_manual_recording_sends_on_release_and_ignores_unpressed_audio(self):
        inputs = ConversationInput()
        for name in ('ASR', 'LLM', 'TTS'):
            inputs.set_service_ready(name)
        inputs.configure_audio(mode='hold')
        capture = AudioCapture(Settings(), inputs.gate, inputs)
        self.feed(capture, 10, True)
        self.assertFalse(capture.segmenter.active, '未按快捷键不能收集对话')
        self.assertTrue(inputs.set_manual_active(True))
        self.feed(capture, 10, True)
        self.assertEqual(inputs.pending.qsize(), 0)
        inputs.set_manual_active(False)
        self.feed(capture, 1, False)
        self.assertEqual(inputs.pending.qsize(), 1, '松开后应立即提交，不再等600ms静音')
        self.assertEqual(inputs.take_next().payload.reason, 'manual')
        inputs.finish_turn()

    def test_manual_pause_and_microphone_test_never_submit_unintended_turns(self):
        inputs = ConversationInput()
        for name in ('ASR', 'LLM', 'TTS'):
            inputs.set_service_ready(name)
        inputs.configure_audio(mode='toggle')
        capture = AudioCapture(Settings(), inputs.gate, inputs)
        inputs.set_manual_active(True)
        self.feed(capture, 10, True)
        self.feed(capture, 40, False)
        self.assertEqual(inputs.pending.qsize(), 0, '点击录音中的停顿不应提前发送')
        inputs.set_testing(True)
        self.feed(capture, 2000, True)
        self.assertEqual(inputs.pending.qsize(), 0)
        self.assertFalse(capture.segmenter.active)

    def test_initial_audio_driver_failure_is_reported_and_retried(self):
        capture = AudioCapture(replace(Settings(), retry_delay=.001), TurnGate())

        class TestAudio:
            def open(self, **kwargs):
                capture.stop_event.set()
                return type("TestStream", (), {"close": lambda self: None})()

            def terminate(self):
                pass

        with patch("app.audio.record.pyaudio.PyAudio", side_effect=[OSError("no device yet"), TestAudio()]) as factory:
            capture._run()
        self.assertEqual(factory.call_count, 2)
        self.assertTrue(any(kind == "error" for kind, text in list(capture.notices.queue)))


class CaptureModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_mode_does_not_open_a_microphone(self):
        inputs = ConversationInput()
        inputs.set_recording(False)
        capture = AudioCapture(Settings(), inputs.gate, inputs)
        with patch('app.audio.record.pyaudio.PyAudio') as factory:
            capture.start()
            try:
                await asyncio.sleep(.03)
                factory.assert_not_called()
            finally:
                await asyncio.to_thread(capture.close)
        self.assertFalse(capture.thread.is_alive())

    async def test_turning_off_closes_and_terminates_before_reopening(self):
        inputs = ConversationInput()
        released = [Event(), Event()]
        instances = []

        class TestAudio:
            def __init__(self):
                self.number = len(instances)
                self.closed = False
                instances.append(self)

            def get_default_input_device_info(self):
                return {'index': 0}

            def is_format_supported(self, *args, **kwargs):
                return True

            def open(self, **kwargs):
                return self

            def read(self, count):
                inputs.set_recording(False)
                return b'\0\0' * count

            def close(self):
                self.closed = True

            def terminate(self):
                released[self.number].set()

        capture = AudioCapture(Settings(), inputs.gate, inputs)
        with patch('app.audio.record.pyaudio.PyAudio', TestAudio):
            capture.start()
            try:
                self.assertTrue(await asyncio.to_thread(released[0].wait, 1))
                self.assertTrue(instances[0].closed)
                self.assertEqual(len(instances), 1)
                inputs.set_recording(True)
                self.assertTrue(await asyncio.to_thread(released[1].wait, 1))
                self.assertTrue(instances[1].closed)
                self.assertEqual(len(instances), 2)
                self.assertEqual(len(capture.segmenter.frames), 0)
                self.assertEqual(inputs.pending.qsize(), 0)
            finally:
                await asyncio.to_thread(capture.close)
        self.assertFalse(capture.thread.is_alive())
