import unittest
from dataclasses import replace
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace

from app.core.components import prepare_optional_voice, voice_status
from app.core.voice_settings import VoiceSettings
from config import Settings
from tests.test_pipeline import TestUI, TestOutput
from app.core.pipeline import Pipeline
from app.core.models import SpeechPart, CaptionPart
from app.audio.play import AudioPlayer


class OptionalVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreadable_voice_component_degrades_to_text_mode(self):
        voices = VoiceSettings(Settings())
        with patch('app.core.components.check_files', side_effect=PermissionError('cannot read voice manifest')):
            self.assertFalse(prepare_optional_voice(voices))
        self.assertFalse(voices.snapshot().tts.auto_read)

    async def test_invalid_local_voice_port_cannot_crash_core_startup(self):
        voices = VoiceSettings(Settings())
        voices.set_tts(replace(voices.snapshot().tts, url='http://localhost:invalid/tts'))
        self.assertFalse(prepare_optional_voice(voices))
        self.assertFalse(voices.snapshot().tts.auto_read)
    async def test_missing_voice_still_generates_caption_and_portrait_without_audio(self):
        voices = VoiceSettings(Settings())
        with TemporaryDirectory() as directory:
            self.assertFalse(voice_status(Path(directory))['installed'])
            self.assertFalse(prepare_optional_voice(voices, Path(directory)))
        self.assertFalse(voices.snapshot().tts.auto_read)
        async def events(*args, **kwargs):
            yield SpeechPart(0, 'こんにちは', '平常')
            yield CaptionPart(0, '你好')
        ui = TestUI()
        player = AudioPlayer(Settings(), TestOutput)
        pipeline = Pipeline(Settings(), None, SimpleNamespace(events=events), None, player, ui, voices=voices)
        await pipeline.process_text('hello')
        self.assertIn('你好', ui.messages)
        self.assertEqual(ui.expression, '平常')
        self.assertFalse(pipeline.last_metrics['spoken'])
        await player.close()
