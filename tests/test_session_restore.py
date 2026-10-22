"""自动恢复只使用临时文件和模拟运行状态，不启动录音、模型或网络。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from copy import deepcopy

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QSlider, QCheckBox, QComboBox, QDoubleSpinBox, QPushButton, QStackedWidget, QPlainTextEdit, QSpinBox
from app.ui import control_panel
from app.ui.desktop_pet import DesktopPetWindow
from app.core.ai_settings import AISettings
from app.core.conversation_input import ConversationInput
from app.core.voice_settings import VoiceSettings
from app.ui.desktop import DesktopSignals
from config import Settings


class SessionRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in (('DATA_ROOT', self.root / 'runtime'),
                            ('RESOURCE_STATE', self.root / 'resources.json'),
                            ('RESOURCE_DIRECTORY', self.root / 'assets'),
                            ('RESOURCE_BUBBLE_DIRECTORY', self.root / 'bubbles')):
            change = patch.object(control_panel, name, value)
            change.start()
            self.addCleanup(change.stop)
        (self.root / 'assets').mkdir()
        (self.root / 'bubbles').mkdir()

    def panel(self, *, runtime=False):
        pet = DesktopPetWindow()
        panel = control_panel.load_window(pet=pet)
        if runtime:
            panel.test_inputs = ConversationInput()
            panel.test_signals = DesktopSignals()
            panel.test_voices = VoiceSettings(Settings())
            panel.test_ai = AISettings(Settings())
            panel.conversation_controls.bind_inputs(panel.test_inputs, panel.test_signals)
            panel.audio_controls.bind_inputs(panel.test_inputs)
            panel.voice_controls.bind_runtime(panel.test_voices, panel.test_inputs)
            panel.ai_controls.bind_runtime(panel.test_ai, panel.test_inputs)
        control_panel.remember_session(panel)
        self.addCleanup(pet.deleteLater)
        self.addCleanup(panel.deleteLater)
        self.addCleanup(pet.shutdown)
        self.addCleanup(panel.close)
        return panel, pet

    def test_close_and_restart_restore_character_and_persona_without_manual_export(self):
        first, _ = self.panel()
        first.findChild(QSlider, 'scaleSlider').setValue(145)
        first.findChild(QLineEdit, 'userNameEdit').setText('上次的称呼')
        first.close()
        second, pet = self.panel()
        self.assertEqual(second.findChild(QSlider, 'scaleSlider').value(), 145)
        self.assertEqual(pet.scale_percent, 145)
        self.assertEqual(second.findChild(QLineEdit, 'userNameEdit').text(), '上次的称呼')

    def test_runtime_restores_audio_models_keys_and_recording_before_worker_starts(self):
        first, _ = self.panel(runtime=True)
        first.findChild(QCheckBox, 'recordingEnabledCheck').setChecked(False)
        first.findChild(QSlider, 'inputVolumeSlider').setValue(31)
        first.findChild(QSlider, 'outputVolumeSlider').setValue(43)
        first.findChild(QComboBox, 'recordingModeCombo').setCurrentIndex(1)
        first.findChild(QComboBox, 'microphoneCombo').addItem('fixture input', 7)
        first.findChild(QComboBox, 'microphoneCombo').setCurrentIndex(first.findChild(QComboBox, 'microphoneCombo').findData(7))
        first.findChild(QComboBox, 'speakerCombo').addItem('fixture output', 9)
        first.findChild(QComboBox, 'speakerCombo').setCurrentIndex(first.findChild(QComboBox, 'speakerCombo').findData(9))
        first.findChild(QComboBox, 'llmModelCombo').setCurrentText('fixture-model')
        first.findChild(QLineEdit, 'apiKeyEdit').setText('sk-test-session-ai')
        first.findChild(QLineEdit, 'asrApiKeyEdit').setText('sk-test-session-asr')
        first.findChild(QDoubleSpinBox, 'temperatureSpin').setValue(.4)
        first.findChild(QSpinBox, 'replyLengthSpin').setValue(750)
        first.close()
        second, _ = self.panel(runtime=True)
        self.assertEqual(second.test_ai.snapshot().options.model, 'fixture-model')
        self.assertEqual(second.test_ai.snapshot().options.api_key, 'sk-test-session-ai')
        self.assertEqual(second.test_ai.snapshot().options.temperature, .4)
        self.assertEqual(second.test_ai.snapshot().options.reply_length, 750)
        self.assertEqual(second.test_voices.snapshot().asr.api_key, 'sk-test-session-asr')
        self.assertEqual(second.test_voices.snapshot().output.volume, 43)
        self.assertEqual(second.test_voices.snapshot().output.device, 9)
        capture = second.test_inputs.capture_state()
        self.assertEqual(capture.options.volume, 31)
        self.assertEqual(capture.options.device, 7)
        self.assertFalse(second.test_inputs.recording_state()[0])

    def test_view_size_audio_tab_and_hidden_pet_survive_restart(self):
        first, pet = self.panel()
        first.resize(1310, 970)
        first.findChild(QPushButton, 'navAssets').click()
        first.audio_resource_controls.tabs.setCurrentIndex(1)
        first.audio_resource_controls.w('audioSearchEdit', QLineEdit).setText('疑问')
        first.show()
        self.app.processEvents()
        pet.hide()
        first.close()
        second, restored_pet = self.panel()
        self.assertEqual((second.width(), second.height()), (1310, 970))
        self.assertEqual(second.findChild(QStackedWidget, 'pageStack').currentWidget().objectName(), 'resourcesPage')
        self.assertEqual(second.audio_resource_controls.tabs.currentIndex(), 1)
        self.assertEqual(second.audio_resource_controls.w('audioSearchEdit', QLineEdit).text(), '疑问')
        self.assertFalse(restored_pet.isVisible())

    def test_incomplete_connection_fields_survive_and_can_be_fixed_next_time(self):
        first, _ = self.panel(runtime=True)
        first.findChild(QLineEdit, 'baseUrlEdit').setText('https:')
        first.close()
        second, _ = self.panel(runtime=True)
        self.assertTrue(second.session_controls.loaded)
        self.assertEqual(second.findChild(QLineEdit, 'baseUrlEdit').text(), 'https:')
        with self.assertRaises(ValueError):
            second.test_ai.snapshot().options.validate()

    def test_bad_file_is_preserved_and_subsequent_settings_use_recovery_file(self):
        first, _ = self.panel()
        path = first.session_controls.file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'broken fixture')
        second, _ = self.panel()
        self.assertFalse(second.session_controls.loaded)
        second.findChild(QLineEdit, 'userNameEdit').setText('恢复后的称呼')
        second.close()
        self.assertEqual(path.read_bytes(), b'broken fixture')
        third, _ = self.panel()
        self.assertEqual(third.findChild(QLineEdit, 'userNameEdit').text(), '恢复后的称呼')

    def test_invalid_audio_editor_is_restored_as_a_draft(self):
        first, _ = self.panel()
        audio = first.audio_resource_controls
        audio.tabs.setCurrentIndex(1)
        audio.w('audioNicknameEdit', QLineEdit).setText('保留草稿')
        audio.w('audioPromptEdit', QPlainTextEdit).setPlainText('')
        audio.mark_dirty()
        first.close()
        second, _ = self.panel()
        restored = second.audio_resource_controls
        self.assertEqual(restored.w('audioNicknameEdit', QLineEdit).text(), '保留草稿')
        self.assertEqual(restored.w('audioPromptEdit', QPlainTextEdit).toPlainText(), '')
        self.assertTrue(restored._dirty)

    def test_missing_saved_portrait_falls_back_without_losing_other_ui_values(self):
        first, _ = self.panel()
        first.session_controls.save()
        document = first.session_controls.file.read()
        document['pages']['characterPage']['expressionCombo'] = '已移除的神态'
        document['pages']['dialoguePage']['userNameEdit'] = '保留我'
        first.session_controls.file.write(document)
        second, _ = self.panel()
        self.assertTrue(second.session_controls.loaded)
        self.assertEqual(second.findChild(QLineEdit, 'userNameEdit').text(), '保留我')
        self.assertEqual(second.findChild(QComboBox, 'expressionCombo').currentText(), second.resource_controls.library.base.default)
