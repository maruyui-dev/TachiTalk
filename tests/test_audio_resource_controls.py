from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt

from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QPlainTextEdit, QPushButton, QWidget, QMessageBox
from PySide6.QtGui import QFontDatabase
from app.core.audio_library import AudioLibrary
from app.core.voice_settings import ReferencePreview, VoiceSettings
from app.ui import control_panel
from config import REF_MAP, Settings


class AudioResourceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        library = AudioLibrary(self.root / 'audio.json', REF_MAP)
        self.panel = control_panel.load_window(audio_library=library)
        self.addCleanup(self.panel.deleteLater)
        self.addCleanup(self.panel.close)
        self.controls = self.panel.audio_resource_controls
        self.controls.tabs.setCurrentIndex(1)

    def test_tab_keeps_original_portrait_scroll_and_window_dimensions(self):
        c = self.controls
        self.assertEqual(c.tabs.count(), 2)
        self.assertEqual(c.tabs.widget(0).objectName(), 'resourcesPageScroll')
        self.assertIsNotNone(self.panel.findChild(QWidget, 'expressionMappingCard'))
        self.panel.resize(1200, 920)
        self.panel.findChild(QPushButton, 'navAssets').click()
        self.panel.show()
        self.app.processEvents()
        self.assertEqual((self.panel.width(), self.panel.height()), (1200, 920))
        self.assertLessEqual(c.page.minimumSizeHint().height(), c.page.height())

    def test_save_nickname_changes_runtime_library_without_portrait_mapping(self):
        c = self.controls
        portrait = self.panel.resource_controls.library.catalog()
        ref = c.selected()
        c.w('audioNicknameEdit', QLineEdit).setText('新的音频昵称')
        c.save()
        self.assertIn('新的音频昵称', c.library.snapshot().names)
        self.assertNotIn(ref.name, c.library.snapshot().names)
        self.assertEqual(self.panel.resource_controls.library.catalog().paths, portrait.paths)
        c.w('audioEnabledCheck', QCheckBox).setChecked(False)
        c.w('audioDefaultCheck', QCheckBox).setChecked(False)
        c.save()
        self.assertNotIn('新的音频昵称', c.library.snapshot().names)

    def test_preview_uses_selected_reference_and_current_transcript_without_llm(self):
        c = self.controls
        voices = VoiceSettings(Settings())
        c.bind_runtime(voices)
        c.preview(True)
        command = voices.commands()['preview']
        self.assertIsInstance(command.payload, ReferencePreview)
        self.assertTrue(command.payload.raw)
        self.assertEqual(command.payload.reference, c.selected())
        c.w('audioPromptEdit', QPlainTextEdit).setPlainText('新しい原文です。')
        c.preview(False)
        request = voices.commands()['preview'].payload
        self.assertFalse(request.raw)
        self.assertEqual(request.reference.prompt, '新しい原文です。')
        self.assertNotEqual(request.reference.prompt, c.selected().prompt)
        c.stop()
        self.assertIsNone(voices.commands()['preview'].payload)

    def test_global_backup_includes_audio_and_accepts_older_files(self):
        settings = self.panel.settings_controls
        document = settings.snapshot()
        self.assertIn('audio_resources', document)
        settings.prepare(document)
        del document['audio_resources']
        settings.prepare(document)

    def test_save_while_switching_row_keeps_new_selection_and_clears_empty_form(self):
        c = self.controls
        c.w('audioNicknameEdit', QLineEdit).setText('保存后切行')
        c.mark_dirty()
        key = c.table.item(1, 0).data(Qt.ItemDataRole.UserRole)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save):
            c.table.setCurrentCell(1, 0)
        self.app.processEvents()
        self.assertIn('保存后切行', c.library.snapshot().names)
        self.assertEqual(c.selected().key, key)
        self.assertEqual(c.w('audioNicknameEdit', QLineEdit).text(), c.selected().name)
        c.library.create_pack('空音频库')
        c.refresh()
        self.assertIsNone(c.selected())
        self.assertEqual(c.w('audioNicknameEdit', QLineEdit).text(), '')
        self.assertFalse(c.w('audioSaveButton', QPushButton).isEnabled())

    def test_global_save_commits_pending_audio_editor_before_backup(self):
        c = self.controls
        c.w('audioNicknameEdit', QLineEdit).setText('随设置一起保存')
        c.mark_dirty()
        target = self.root / 'backup.json'
        self.assertTrue(self.panel.settings_controls.save_to(target))
        self.assertIn('随设置一起保存', c.library.snapshot().names)
        data = json.loads(target.read_text(encoding='utf-8'))
        refs = data['audio_resources']['packs']['default']['references']
        self.assertIn('随设置一起保存', [ref['name'] for ref in refs])
