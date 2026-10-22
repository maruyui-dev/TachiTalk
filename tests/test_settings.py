"""页面重置与全局配置文件：使用隔离目录和测试密钥，不连接设备或在线服务。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QLineEdit, QSpinBox
from PySide6.QtGui import QColor, QImage

from config import Settings
from app.core.ai_settings import AISettings
from app.core.conversation_input import ConversationInput
from app.core.voice_settings import VoiceSettings
from app.ui import control_panel
from app.ui.desktop import DesktopSignals
from app.ui.desktop_pet import DesktopPetWindow


class SettingsTests(unittest.TestCase):
    def test_old_configuration_without_reply_length_loads_with_default(self):
        document = self.panel.settings_controls.snapshot()
        document['pages']['aiPage'].pop('replyLengthSpin')
        for profile in document['profiles']['ai'].values():
            profile.pop('reply_length')
        self.panel.settings_controls.prepare(document)
        self.assertEqual(document['pages']['aiPage']['replyLengthSpin'], 0)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'assets').mkdir()
        (self.root / 'bubbles').mkdir()
        self.patches = [
            patch.object(control_panel, 'DATA_ROOT', self.root / 'runtime'),
            patch.object(control_panel, 'RESOURCE_STATE', self.root / 'library.json'),
            patch.object(control_panel, 'RESOURCE_DIRECTORY', self.root / 'assets'),
            patch.object(control_panel, 'RESOURCE_BUBBLE_DIRECTORY', self.root / 'bubbles'),
            patch.object(QMessageBox, 'warning'),
        ]
        for item in self.patches:
            item.start()
        self.pet = DesktopPetWindow()
        self.panel = control_panel.load_window(pet=self.pet)
        self.inputs, self.signals = ConversationInput(), DesktopSignals()
        self.ai, self.voices = AISettings(Settings()), VoiceSettings(Settings())
        self.panel.conversation_controls.bind_inputs(self.inputs, self.signals)
        self.panel.audio_controls.bind_inputs(self.inputs)
        self.panel.voice_controls.bind_runtime(self.voices, self.inputs)
        self.panel.ai_controls.bind_runtime(self.ai, self.inputs)
        self.panel.ai_controls.w('apiKeyEdit').setText('sk-test-ai-backup')
        self.panel.ai_controls.save()
        self.panel.voice_controls.w('asrApiKeyEdit').setText('sk-test-asr-backup')
        self.panel.voice_controls.save_asr()

    def tearDown(self):
        self.panel.close()
        self.pet.shutdown()
        self.panel.deleteLater()
        self.pet.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def click(self, name):
        button = self.panel.findChild(QPushButton, name)
        self.assertIsNotNone(button, f'缺少操作入口：{name}')
        button.click()

    def test_dialogue_reset_restores_screenshot_defaults_without_touching_other_pages(self):
        persona = self.panel.persona_controls
        persona.character_name.setText('测试角色')
        persona.user_name.setText('测试称呼')
        persona.language.setCurrentText('英文')
        persona.streaming.setChecked(False)
        persona.context.setCurrentIndex(2)
        self.panel.audio_controls.volume.setValue(23)
        self.panel.ai_controls.w('temperatureSpin').setValue(.2)
        self.click('navChat')
        self.click('resetButton')
        result = persona.profiles.snapshot()
        self.assertEqual((result.character_name, result.user_name, result.reply_language), ('茉子', '', '简体中文'))
        self.assertEqual((result.context_turns, result.stream_reply, result.switch_expression), (20, True, True))
        self.assertEqual(self.inputs.capture_state().options.volume, 23)
        self.assertEqual(self.ai.snapshot().options.temperature, .2)

    def test_character_reset_shows_the_pet_and_preserves_dialogue_settings(self):
        self.panel.persona_controls.user_name.setText('保留称呼')
        self.pet.set_scale_percent(120)
        self.pet.set_display_percent(100)
        self.pet.set_anchor(0, 0)
        self.pet.set_stays_on_top(False)
        self.pet.set_position_fixed(False)
        self.pet.hide()
        self.click('resetButton')
        self.assertTrue(self.pet.isVisible())
        self.assertEqual((self.pet.scale_percent, self.pet.display_percent, self.pet.anchor), (180, 50, (2, 2)))
        self.assertTrue(self.pet.position_fixed)
        self.assertEqual(self.panel.persona_controls.user_name.text(), '保留称呼')

    def test_global_save_and_load_restore_multiple_pages_and_their_runtime_keys(self):
        self.assertIsNotNone(self.panel.findChild(QPushButton, 'loadSettingsButton'), '应提供全局加载配置按钮')
        saved = self.root / 'full.tachitalk.json'
        persona = self.panel.persona_controls
        persona.user_name.setText('备份称呼')
        self.panel.audio_controls.volume.setValue(42)
        self.panel.ai_controls.w('apiKeyEdit').setText('sk-test-restored-ai')
        self.panel.ai_controls.w('temperatureSpin').setValue(.4)
        self.pet.set_scale_percent(140)
        self.panel.resource_controls.kind.setCurrentIndex(2)
        self.click('navChat')
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(saved), 'JSON')):
            self.click('saveButton')
        self.assertTrue(saved.is_file())
        self.assertIn('sk-test-restored-ai', saved.read_text(encoding='utf-8'))
        persona.user_name.setText('后来更改')
        self.panel.audio_controls.volume.setValue(13)
        self.panel.ai_controls.w('apiKeyEdit').setText('sk-test-changed-ai')
        self.panel.ai_controls.w('temperatureSpin').setValue(.9)
        self.pet.set_scale_percent(200)
        self.panel.resource_controls.scope.setCurrentIndex(0)
        self.click('navAudio')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(saved), 'JSON')):
            self.click('loadSettingsButton')
        self.assertEqual(persona.profiles.snapshot().user_name, '备份称呼')
        self.assertEqual(self.inputs.capture_state().options.volume, 42)
        self.assertEqual(self.ai.snapshot().options.api_key, 'sk-test-restored-ai')
        self.assertEqual(self.ai.snapshot().options.temperature, .4)
        self.assertEqual(self.pet.scale_percent, 140)
        self.assertEqual(self.panel.resource_controls.scope.currentIndex(), 1)
        self.assertEqual(self.panel.resource_controls.kind.currentData(), 'blue')

    def test_audio_reset_clears_keys_and_preserves_other_pages(self):
        self.panel.persona_controls.user_name.setText('保留称呼')
        self.panel.ai_controls.w('temperatureSpin').setValue(.3)
        self.panel.audio_controls.volume.setValue(12)
        c = self.panel.voice_controls
        c.w('interruptSpeechCheck').setChecked(True)
        c.w('asrAutoSendCheck').setChecked(False)
        c.w('trimSilenceCheck').setChecked(False)
        c.w('asrApiKeyEdit').setText('sk-test-keep-during-reset')
        self.click('navAudio')
        self.click('resetButton')
        self.assertEqual(self.inputs.capture_state().options.volume, 77)
        self.assertEqual(self.voices.snapshot().output.volume, 80)
        self.assertEqual(self.voices.snapshot().asr.model, 'FunAudioLLM/SenseVoiceSmall')
        self.assertEqual(self.voices.snapshot().asr.api_key, '')
        self.assertTrue(all(not item.api_key for item in c._asr_cache.values()))
        self.assertTrue(all(not item.api_key for item in c._tts_cache.values()))
        self.assertEqual(self.ai.snapshot().options.api_key, 'sk-test-ai-backup')
        self.assertTrue(self.voices.snapshot().asr.auto_send)
        self.assertTrue(self.voices.snapshot().asr.trim_silence)
        self.assertFalse(self.voices.snapshot().tts.interrupt)
        self.assertEqual(self.ai.snapshot().options.temperature, .3)
        self.assertEqual(self.panel.persona_controls.user_name.text(), '保留称呼')

    def test_ai_reset_clears_all_ai_provider_keys(self):
        c = self.panel.ai_controls
        c.w('aiProviderCombo').setCurrentIndex(2)
        c.w('apiKeyEdit').setText('sk-test-custom-only')
        c.w('temperatureSpin').setValue(.2)
        self.click('navAI')
        self.click('resetButton')
        options = self.ai.snapshot().options
        self.assertEqual((options.provider, options.base_url, options.model),
                         ('deepseek', 'https://api.deepseek.com', 'deepseek-flash'))
        self.assertEqual(options.api_key, '')
        self.assertTrue(all(not item.api_key for item in c._cache.values()))
        c.w('aiProviderCombo').setCurrentIndex(2)
        self.assertEqual(c.w('apiKeyEdit').text(), '')
        self.assertEqual(self.voices.snapshot().asr.api_key, 'sk-test-asr-backup')
        self.assertEqual(options.temperature, .7)
        self.assertFalse(self.pet.isVisible(), 'AI页恢复默认不能改变角色显示状态')

    def test_bad_file_is_rejected_before_any_page_changes(self):
        manager = self.panel.settings_controls
        before = manager.snapshot()
        for field, value in (('scaleSlider', 500), ('topCheck', 'false')):
            document = deepcopy(before)
            document['pages']['characterPage'][field] = value
            file = self.root / 'invalid.json'
            file.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
            with patch.object(QMessageBox, 'warning'):
                self.assertFalse(manager.load_from(file))
            self.assertEqual(manager.snapshot(), before)
        document = deepcopy(before)
        document['pages']['aiPage']['baseUrlEdit'] = 'file:///invalid'
        file.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        with patch.object(QMessageBox, 'warning'):
            self.assertFalse(manager.load_from(file))
        self.assertEqual(manager.snapshot(), before)

    def test_valid_backup_can_repair_current_incomplete_service_input(self):
        manager = self.panel.settings_controls
        file = self.root / 'repair.json'
        self.assertTrue(manager.save_to(file))
        self.panel.ai_controls.w('baseUrlEdit').setText('not-a-url')
        self.panel.ai_controls.save()
        self.assertTrue(manager.load_from(file))
        self.assertNotEqual(self.ai.snapshot().options.base_url, 'not-a-url')

    def test_apply_failure_rolls_back_already_changed_widgets(self):
        manager = self.panel.settings_controls
        before = manager.snapshot()
        document = deepcopy(before)
        document['pages']['characterPage']['scaleSlider'] = 140
        file = self.root / 'rollback.json'
        file.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        put = manager.values.put
        calls = []
        def interrupted(values):
            put(values)
            calls.append(1)
            if len(calls) == 1:
                raise ValueError('test-apply-failure')
        with patch.object(manager.values, 'put', side_effect=interrupted), patch.object(QMessageBox, 'warning'):
            self.assertFalse(manager.load_from(file))
        self.assertEqual(manager.snapshot(), before)

    def test_cancelling_save_or_load_keeps_all_configuration(self):
        before = self.panel.settings_controls.snapshot()
        with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
            self.click('saveButton')
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('', '')):
            self.click('loadSettingsButton')
        self.assertEqual(self.panel.settings_controls.snapshot(), before)

    def test_resource_mapping_backup_and_reset_keep_imported_images(self):
        source = self.root / 'portrait-source'
        source.mkdir()
        for name, color in (('平常', '#ff2040'), ('开心', '#2040ff')):
            image = QImage(80, 160, QImage.Format.Format_ARGB32)
            image.fill(QColor(color))
            self.assertTrue(image.save(str(source / (name + '.png')), 'PNG'))
        c = self.panel.resource_controls
        key = c.library.import_pack(source, '测试角色')
        c.library.set_mapping('平常', 'file:开心.png')
        c.refresh()
        c.apply()
        manager = self.panel.settings_controls
        file = self.root / 'resources.json'
        self.assertTrue(manager.save_to(file))
        c.library.set_mapping('平常', 'file:平常.png')
        self.assertTrue(manager.load_from(file))
        self.assertEqual(c.library.active_id, key)
        self.assertEqual(c.library.catalog().paths['平常'].name, '开心.png')
        imported = list(c.library.directory.glob('*.png'))
        c.kind.setCurrentIndex(2)
        self.click('navAssets')
        self.click('resetButton')
        self.assertEqual(c.library.active_id, 'default')
        self.assertEqual(c.scope.currentIndex(), 0)
        self.assertEqual(c.kind.currentData(), 'portrait')
        self.assertTrue(all(path.is_file() for path in imported))
        self.assertIn(key, c.library.packs)

    def test_training_page_reset_changes_only_preview_parameters(self):
        self.panel.persona_controls.user_name.setText('保留称呼')
        with patch.object(self.panel.training_page, 'show_notice'):
            self.click('navTraining')
        epochs = self.panel.findChild(QSpinBox, 'trainingGPTEpochsSpin')
        name = self.panel.findChild(QLineEdit, 'trainingProjectNameEdit')
        epochs.setValue(66)
        name.setText('测试工程')
        self.click('resetButton')
        self.assertEqual((epochs.value(), name.text()), (15, '茉子_新声音'))
        self.assertFalse(self.panel.findChild(QPushButton, 'trainingStartButton').isEnabled())
        self.assertEqual(self.panel.persona_controls.user_name.text(), '保留称呼')

    def test_inactive_service_profiles_and_keys_survive_global_backup(self):
        ai, voice = self.panel.ai_controls, self.panel.voice_controls
        ai.w('aiProviderCombo').setCurrentIndex(2)
        ai.w('baseUrlEdit').setText('http://localhost/v1')
        ai.w('apiKeyEdit').setText('sk-test-private-custom')
        ai.w('llmModelCombo').setCurrentText('test-custom-model')
        ai.save()
        ai.w('aiProviderCombo').setCurrentIndex(0)
        voice.w('asrProviderCombo').setCurrentIndex(1)
        voice.w('asrModelCombo').setCurrentText('whisper-1')
        voice.w('asrApiKeyEdit').setText('sk-test-private-asr-openai')
        voice.save_asr()
        voice.w('asrProviderCombo').setCurrentIndex(0)
        file = self.root / 'profiles.json'
        self.assertTrue(self.panel.settings_controls.save_to(file))
        ai.w('aiProviderCombo').setCurrentIndex(2)
        ai.w('apiKeyEdit').setText('sk-test-later-key')
        ai.save()
        ai.w('aiProviderCombo').setCurrentIndex(0)
        self.assertTrue(self.panel.settings_controls.load_from(file))
        ai.w('aiProviderCombo').setCurrentIndex(2)
        self.assertEqual(self.ai.snapshot().options.api_key, 'sk-test-private-custom')
        voice.w('asrProviderCombo').setCurrentIndex(1)
        self.assertEqual(self.voices.snapshot().asr.api_key, 'sk-test-private-asr-openai')

    def test_loading_configuration_invalidates_older_model_list_results(self):
        file = self.root / 'models.json'
        c = self.panel.voice_controls
        self.assertTrue(self.panel.settings_controls.save_to(file))
        c.request_models()
        old_id = c._requested['models']
        self.assertTrue(self.panel.settings_controls.load_from(file))
        self.voices.complete('models', old_id, value=('old-obsolete-model',))
        c.refresh()
        self.assertNotEqual(c.w('asrModelCombo').currentText(), 'old-obsolete-model')

    def test_config_file_cannot_grant_delete_ownership_to_an_existing_image(self):
        path = self.root / 'assets' / '手动放入.png'
        image = QImage(80, 160, QImage.Format.Format_ARGB32)
        image.fill(QColor('#00a080'))
        self.assertTrue(image.save(str(path), 'PNG'))
        library = self.panel.resource_controls.library
        library.refresh()
        document = self.panel.settings_controls.snapshot()
        document['resources']['packs']['default']['state']['files'][path.name] = {'kind': 'portrait', 'owned': True}
        file = self.root / 'ownership.json'
        file.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        self.assertTrue(self.panel.settings_controls.load_from(file))
        self.assertFalse(library.records['file:' + path.name].owned)
        library.remove('file:' + path.name)
        self.assertTrue(path.is_file())

    def test_storage_rejects_duplicate_fields_and_non_finite_numbers(self):
        from app.core.configuration_file import read_config
        file = self.root / 'bad-json.json'
        for payload in ('{"version":1,"version":1}', '{"number":NaN}', '[' * 1200 + '0' + ']' * 1200):
            file.write_text(payload, encoding='utf-8')
            with self.assertRaises(ValueError):
                read_config(file)

    def test_failed_file_commit_does_not_replace_the_existing_backup(self):
        from app.core import configuration_file
        file = self.root / 'atomic.json'
        original = self.panel.settings_controls.snapshot()
        configuration_file.write_config(file, original)
        before = file.read_bytes()
        real_save_file = configuration_file.QSaveFile
        class InterruptedSave:
            def __init__(self, filename):
                self.target = real_save_file(filename)
            def open(self, mode):
                return self.target.open(mode)
            def write(self, data):
                return self.target.write(data)
            def commit(self):
                return False
            def cancelWriting(self):
                self.target.cancelWriting()
        with patch.object(configuration_file, 'QSaveFile', InterruptedSave):
            with self.assertRaises(OSError):
                configuration_file.write_config(file, original)
        self.assertEqual(file.read_bytes(), before)

    def test_reimported_same_named_pack_can_use_its_existing_configuration_backup(self):
        source = self.root / 'same-name-source'
        source.mkdir()
        image = QImage(80, 160, QImage.Format.Format_ARGB32)
        image.fill(QColor('#4050ff'))
        self.assertTrue(image.save(str(source / '平常.png'), 'PNG'))
        c = self.panel.resource_controls
        old = c.library.import_pack(source, '同名角色')
        c.refresh()
        c.apply()
        file = self.root / 'same-name.json'
        self.assertTrue(self.panel.settings_controls.save_to(file))
        c.library.remove_pack(old)
        new = c.library.import_pack(source, '同名角色')
        self.assertNotEqual(old, new)
        c.refresh()
        c.apply()
        self.assertTrue(self.panel.settings_controls.load_from(file))
        self.assertEqual(c.library.active_id, new)
        cached = c.library._loaded_libraries[new]
        with patch.object(c.library, '_commit_manifest', side_effect=OSError('test-save-failure')):
            with self.assertRaises(OSError):
                c.library.remove_pack(new)
        self.assertIs(c.library._loaded_libraries.get(new), cached)
