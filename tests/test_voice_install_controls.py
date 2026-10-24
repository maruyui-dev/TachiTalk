"""One-time voice preference activation, including partial persistence failures."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.core.voice_settings import VoiceSettings, default_voice_profiles
from app.ui.voice_install_controls import VoiceInstallControls
from config import Settings


class Panel(QObject):
    closing = Signal()


class VoiceInstallControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory(prefix='voice-install-control-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.panel = Panel()
        self.panel._closing = False
        self.saved = []
        self.panel.session_controls = SimpleNamespace(
            file=SimpleNamespace(path=self.root / 'settings/last_session.dat'),
            save=self.save_session)
        self.voices = VoiceSettings(Settings())
        _, cache = default_voice_profiles(Settings())
        cache['gpt_sovits'] = replace(cache['gpt_sovits'], auto_read=False)
        self.voices.set_tts(cache['gpt_sovits'])
        self.controls = self.panel.voice_controls = SimpleNamespace(
            voices=self.voices, _tts_cache=cache, _tts_provider='gpt_sovits',
            apply_preferences=lambda: None, fill_tts=self.fill, save_tts=self.save_tts)
        self.displayed = cache['gpt_sovits']

    def fill(self, options):
        self.displayed = options

    def save_tts(self):
        self.controls._tts_cache[self.displayed.provider] = self.displayed
        self.voices.set_tts(self.displayed)

    def save_session(self):
        self.saved.append(self.voices.snapshot().tts.auto_read)
        return True

    def controller(self):
        controller = VoiceInstallControls(self.panel, self.root / 'services/gpt_sovits')
        self.addCleanup(controller.timer.stop)
        return controller

    def test_deeply_nested_corrupt_record_preserves_preference_and_does_not_crash(self):
        record = self.root / 'settings/voice-component.json'
        record.parent.mkdir()
        raw = '[' * 4000 + '0' + ']' * 4000
        record.write_text(raw, encoding='utf-8')
        controller = self.controller()
        with patch('app.core.components.voice_status', return_value={
                'installed': True, 'version': 'fixture', 'missing': []}):
            controller.refresh()
        self.assertFalse(self.voices.snapshot().tts.auto_read)
        self.assertEqual(record.read_text(encoding='utf-8'), raw)
        self.assertEqual(self.saved, [])

    def test_marker_retry_does_not_repeat_successfully_saved_activation(self):
        controller = self.controller()
        with patch('app.core.components.voice_status', return_value={
                'installed': True, 'version': 'fixture', 'missing': []}):
            with patch('app.ui.voice_install_controls.atomic_json', side_effect=PermissionError('fixture marker denied')):
                controller.refresh()
            self.assertTrue(self.voices.snapshot().tts.auto_read)
            self.displayed = replace(self.displayed, auto_read=False)
            self.save_tts()  # A real user preference change after session save succeeded.
            controller.refresh()  # The marker write is now allowed; only it needs retrying.
        self.assertFalse(self.voices.snapshot().tts.auto_read)
        self.assertEqual(self.saved, [True])
        self.assertTrue(json.loads(controller.record.read_text(encoding='utf-8'))['installed'])

    def test_other_provider_is_not_switched_when_local_install_is_detected(self):
        options = replace(self.controls._tts_cache['system'], auto_read=False)
        self.controls._tts_provider = 'system'
        self.voices.set_tts(options)
        controller = self.controller()
        with patch('app.core.components.voice_status', return_value={
                'installed': True, 'version': 'fixture', 'missing': []}):
            controller.refresh()
        self.assertEqual(self.voices.snapshot().tts, options)
        self.assertTrue(self.controls._tts_cache['gpt_sovits'].auto_read)
        self.assertEqual(self.controls._tts_provider, 'system')

    def test_preference_save_retry_preserves_manual_disable_between_checks(self):
        outcomes = iter((False, True))

        def save():
            self.saved.append(self.voices.snapshot().tts.auto_read)
            return next(outcomes)

        self.panel.session_controls.save = save
        controller = self.controller()
        with patch('app.core.components.voice_status', return_value={
                'installed': True, 'version': 'fixture', 'missing': []}):
            controller.refresh()
            self.assertTrue(self.voices.snapshot().tts.auto_read)
            self.assertFalse(controller.record.exists())
            self.displayed = replace(self.displayed, auto_read=False)
            self.save_tts()
            controller.refresh()
        self.assertFalse(self.voices.snapshot().tts.auto_read)
        self.assertEqual(self.saved, [True, False])
        self.assertTrue(json.loads(controller.record.read_text(encoding='utf-8'))['installed'])
