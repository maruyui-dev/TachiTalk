from array import array
import asyncio
from threading import Event
from time import sleep
import unittest
from unittest.mock import patch

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from config import Settings
from app.audio.devices import apply_input_volume
from app.audio.record import AudioCapture
from app.core.audio_input import InputDevice
from app.core.conversation_input import ConversationInput
from app.core.models import AudioFormat, AudioSegment
from app.ui.control_panel import load_window


class InputAudioTests(unittest.TestCase):
    def test_gain_changes_the_actual_pcm_and_zero_volume_has_zero_level(self):
        frame = array('h', [12000, -12000, 6000, -6000]).tobytes()
        scaled, level = apply_input_volume(frame, 50)
        self.assertEqual(list(array('h', scaled)), [6000, -6000, 3000, -3000])
        original, original_level = apply_input_volume(frame, 100)
        self.assertEqual(original, frame)
        self.assertGreater(original_level, level)
        muted, muted_level = apply_input_volume(frame, 0)
        self.assertEqual(muted, bytes(len(frame)))
        self.assertEqual(muted_level, 0)

    def test_volume_does_not_restart_stream_but_device_and_rate_discard_pending_audio(self):
        inputs = ConversationInput()
        for name in ('ASR', 'LLM', 'TTS'):
            inputs.set_service_ready(name)
        _, revision = inputs.recording_state()
        inputs.configure_audio(volume=20)
        self.assertEqual(inputs.recording_state()[1], revision)
        segment = AudioSegment(bytes(640), AudioFormat(16000), 1.0)
        self.assertTrue(inputs.offer_audio(segment, revision))
        inputs.configure_audio(device=7, sample_rate=32000)
        self.assertEqual(inputs.pending.qsize(), 0)
        self.assertFalse(inputs.gate.busy)
        self.assertFalse(inputs.offer_audio(segment, revision))


class DeviceCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def wait_until(self, predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(.005)

    async def test_scanning_while_recording_off_never_opens_a_stream(self):
        inputs = ConversationInput()
        inputs.set_recording(False)
        inputs.request_device_scan()
        terminated = Event()

        class DeviceDriver:
            def get_device_count(self):
                return 2

            def get_device_info_by_index(self, index):
                return {'name': 'mic' if index == 0 else 'speaker', 'hostApi': 0, 'maxInputChannels': 1 if index == 0 else 0}

            def get_host_api_info_by_index(self, index):
                return {'name': 'MME'}

            def open(self, **kwargs):
                raise AssertionError('设备枚举不能打开录音流')

            def terminate(self):
                terminated.set()

        capture = AudioCapture(Settings(), inputs.gate, inputs)
        with patch('app.audio.record.pyaudio.PyAudio', DeviceDriver):
            capture.start()
            try:
                await self.wait_until(lambda: inputs.audio_status().scan_version == 1)
                self.assertEqual(inputs.audio_status().devices, (InputDevice(0, 'mic', 'MME'),))
                self.assertTrue(terminated.is_set())
                self.assertEqual(inputs.pending.qsize(), 0)
            finally:
                await asyncio.to_thread(capture.close)

    async def test_switching_device_and_rate_releases_old_stream_before_new_audio(self):
        inputs = ConversationInput()
        for name in ('ASR', 'LLM', 'TTS'):
            inputs.set_service_ready(name)
        inputs.configure_audio(mode='hold')
        opens, live = [], []
        maximum_live = 0

        class Driver:
            def get_default_input_device_info(self):
                return {'index': 0}

            def is_format_supported(self, *args, **kwargs):
                return True

            def get_device_info_by_index(self, index):
                return {'name': 'second mic'}

            def open(self, **kwargs):
                nonlocal maximum_live
                opens.append(kwargs)
                live.append(self)
                maximum_live = max(maximum_live, len(live))
                return self

            def read(self, count):
                sleep(.003)
                return b'\x10\x01' * count

            def close(self):
                live.remove(self)

            def terminate(self):
                pass

        capture = AudioCapture(Settings(), inputs.gate, inputs)
        capture.detector.is_speech = lambda frame, rate: True
        with patch('app.audio.record.pyaudio.PyAudio', Driver):
            capture.start()
            try:
                await self.wait_until(lambda: inputs.audio_status().capture_active)
                inputs.set_manual_active(True)
                await self.wait_until(lambda: capture.segmenter.active)
                inputs.configure_audio(device=7, device_name='second mic', sample_rate=32000)
                await self.wait_until(lambda: len(opens) == 2 and inputs.audio_status().capture_active)
                self.assertEqual(inputs.pending.qsize(), 0)
                self.assertEqual(opens[-1]['rate'], 32000)
                self.assertEqual(opens[-1]['input_device_index'], 7)
                inputs.set_manual_active(True)
                await self.wait_until(lambda: capture.segmenter.active)
                inputs.set_manual_active(False)
                await self.wait_until(lambda: not inputs.pending.empty())
                segment = inputs.take_next().payload
                self.assertEqual(segment.format.sample_rate, 32000)
                self.assertEqual(segment.reason, 'manual')
                self.assertEqual(maximum_live, 1)
                inputs.finish_turn()
            finally:
                await asyncio.to_thread(capture.close)
        self.assertEqual(live, [])


class AudioControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.panel = load_window()
        self.inputs = ConversationInput()
        for name in ('ASR', 'LLM', 'TTS'):
            self.inputs.set_service_ready(name)
        self.inputs.set_capture_active(True)
        self.controls = self.panel.audio_controls
        self.controls.bind_inputs(self.inputs)
        self.inputs.take_device_scan()
        self.inputs.finish_device_scan((InputDevice(7, 'USB mic', 'MME'),))
        self.controls.refresh()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_device_buttons_share_a_row_and_selection_gain_rate_reach_capture(self):
        controls = self.controls
        self.assertEqual(controls.scan.property('accent'), 'pink')
        self.assertIs(controls.scan.parentWidget(), controls.test.parentWidget())
        controls.device.setCurrentIndex(controls.device.findData(7))
        controls.rate.setCurrentText('32000 Hz')
        controls.volume.setValue(100)
        options = self.inputs.capture_state().options
        self.assertEqual((options.device, options.device_name, options.sample_rate, options.volume), (7, 'USB mic', 32000, 100))
        self.inputs.report_level(63)
        controls.refresh()
        self.assertEqual(controls.level.value(), 63)
        self.assertEqual(controls.volume_label.text(), '100%')

    def test_microphone_test_temporarily_opens_when_recording_off_without_dialogue(self):
        self.inputs.set_recording(False)
        self.controls.toggle_test()
        self.assertTrue(self.inputs.capture_state().enabled)
        self.assertFalse(self.inputs.snapshot().recording)
        self.inputs.report_level(60)
        self.controls.finish_test()
        self.assertFalse(self.inputs.capture_state().enabled)
        self.assertFalse(self.inputs.snapshot().recording)
        self.assertEqual(self.inputs.pending.qsize(), 0)
        self.assertIn('检测到输入信号', self.controls.status.text())

    def test_click_mode_and_global_hold_mode_use_press_edges_and_release(self):
        controls = self.controls
        controls.mode.setCurrentIndex(2)
        controls.manual.click()
        self.assertTrue(self.inputs.capture_state().manual_active)
        controls.manual.click()
        self.assertFalse(self.inputs.capture_state().manual_active)
        keys = set()
        controls.hotkey.key_state = lambda code: 0x8000 if code in keys else 0
        controls.mode.setCurrentIndex(1)
        keys.update((0x11, 0x20))
        controls.hotkey.poll()
        self.assertTrue(self.inputs.capture_state().manual_active)
        self.inputs.set_manual_active(False)  # 模拟达到单段上限后自动提交。
        controls.hotkey.poll()
        self.assertFalse(self.inputs.capture_state().manual_active, '物理按键未松开时不能重复触发')
        keys.clear()
        controls.hotkey.poll()
        keys.update((0x11, 0x20))
        controls.hotkey.poll()
        self.assertTrue(self.inputs.capture_state().manual_active)
        keys.remove(0x20)
        controls.hotkey.poll()
        self.assertFalse(self.inputs.capture_state().manual_active)
        controls.shortcut.setKeySequence(QKeySequence())
        controls.change_shortcut()
        self.assertEqual(controls.shortcut.keySequence(), QKeySequence('Ctrl+Space'))
