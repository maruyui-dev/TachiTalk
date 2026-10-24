"""Real Qt focus/layout regression; no public network or normal user profile."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QStyle, QStyleOptionButton

from app.ui.control_panel import ControlPanelWindow
from app.ui.update_controls import UpdateControls
from app.updates.client import UpdateClient


class OptionalVoicePreferenceTests(unittest.TestCase):
    def test_temporary_unavailability_can_clear_without_changing_user_preference(self):
        from dataclasses import replace
        from app.core.voice_settings import VoiceSettings
        from app.core.components import prepare_optional_voice
        from config import Settings
        voices = VoiceSettings(Settings())
        with patch('app.core.components.voice_status', return_value={'installed': False}):
            self.assertFalse(prepare_optional_voice(voices))
        self.assertFalse(voices.snapshot().tts.auto_read)
        with patch('app.core.components.voice_status', return_value={'installed': True}):
            self.assertTrue(prepare_optional_voice(voices))
        self.assertTrue(voices.snapshot().tts.auto_read)
        voices.set_tts(replace(voices.snapshot().tts, auto_read=False))
        voices.set_local_voice_available(False)
        voices.set_local_voice_available(True)
        self.assertFalse(voices.snapshot().tts.auto_read)

    def test_remote_provider_and_incomplete_url_do_not_inherit_local_absence(self):
        from dataclasses import replace
        from app.core.voice_settings import VoiceSettings
        from config import Settings
        voices = VoiceSettings(Settings())
        voices.set_local_voice_available(False)
        voices.set_tts(replace(voices.snapshot().tts, provider='custom', url='https://example.test/tts', auto_read=True))
        self.assertTrue(voices.snapshot().tts.auto_read)
        voices.set_tts(replace(voices.snapshot().tts, url='http://['))
        self.assertEqual(voices.snapshot().tts.url, 'http://[')


class RecordingIndicatorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_indicator_resources_draw_all_states_and_click_matches_state(self):
        from app.ui.control_panel import ControlPanelLoader, BASE_DIR
        loader = ControlPanelLoader()
        check = loader.createWidget('QCheckBox', None, 'recordingEnabledCheck')
        check.setText('启用录音对话')
        # InstallerAssetTests guards the missing files at their actual cause.
        # Here verify the product style with the correctly installed resources.
        check.setStyleSheet((BASE_DIR / 'character_control.qss').read_text(encoding='utf-8')
                           .replace('@ASSETS@', (BASE_DIR / 'assets').as_posix()))
        check.resize(220, 35)
        check.show()
        try:
            pictures = []
            for enabled in (True, False):
                for checked in (False, True):
                    with self.subTest(enabled=enabled, checked=checked):
                        check.setEnabled(enabled)
                        check.setChecked(checked)
                        self.app.processEvents()
                        option = QStyleOptionButton()
                        check.initStyleOption(option)
                        rect = check.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, check)
                        image = check.grab().toImage()
                        scale = image.devicePixelRatio()
                        crop = image.copy(round(rect.x()*scale), round(rect.y()*scale),
                                          round(rect.width()*scale), round(rect.height()*scale))
                        ink = sum(crop.pixelColor(x, y).alpha() > 0 and crop.pixelColor(x, y).lightness() < 230
                                  for x in range(crop.width()) for y in range(crop.height()))
                        pictures.append(crop)
                        self.assertGreater(ink, 100 * scale * scale, 'indicator 只剩空白')
            self.assertNotEqual(pictures[0], pictures[1])
            self.assertNotEqual(pictures[2], pictures[3])
            check.setEnabled(True)
            check.setChecked(False)
            QTest.mouseClick(check, Qt.MouseButton.LeftButton, pos=check.rect().center())
            self.assertTrue(check.isChecked())
        finally:
            check.close()
            check.deleteLater()


class DownloadScrollRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_network_check_keeps_viewport_at_start_and_completion(self):
        with tempfile.TemporaryDirectory() as directory, patch('app.updates.main_feed.ENABLED', False):
            root = Path(directory)
            panel = ControlPanelWindow()
            client = UpdateClient(root=root, data=root / 'data')
            async def diagnose(*args, **kwargs):
                await asyncio.sleep(.15)
                probe = {'state': 'ok', 'latency_ms': 300, 'detail': 'HTTP 206 fixture'}
                return {'state': 'ok', 'manifest': probe, 'artifact': probe,
                        'modelscope': {'manifest': probe, 'artifact': probe},
                        'proxy': {'state': 'not_found', 'summary': '未发现代理'}, 'manifest_error': ''}
            client.diagnose = diagnose
            ui = UpdateControls(panel, client)
            panel.setCentralWidget(ui)
            panel.resize(1150, 700)
            panel.show()
            try:
                QTest.qWait(100)
                for start in (0, 70):
                    with self.subTest(scroll=start):
                        bar = ui.verticalScrollBar()
                        bar.setValue(start)
                        self.app.processEvents()
                        QTest.mouseClick(ui.network_check_button, Qt.MouseButton.LeftButton)
                        self.app.processEvents()
                        self.assertTrue(ui.busy)
                        self.assertEqual(bar.value(), start, '检测开始时焦点转移导致页面向下滚动')
                        deadline = time.monotonic() + 3
                        while ui.busy and time.monotonic() < deadline:
                            self.app.processEvents()
                            time.sleep(.005)
                        self.app.processEvents()
                        self.assertFalse(ui.busy)
                        self.assertEqual(bar.value(), start, '检测结束时焦点转移导致页面向下滚动')
            finally:
                ui.shutdown()
                if ui.thread:
                    ui.thread.join(timeout=3)
                panel.close()
                panel.deleteLater()
