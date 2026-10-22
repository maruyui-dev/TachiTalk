"""发行前拒绝GPT-SoVITS无法使用的参考音频。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

from scripts.build_release import check_release_data


class ReleaseResourceTests(unittest.TestCase):
    def check_audio(self, duration):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reference.wav'
            with wave.open(str(path), 'wb') as audio:
                audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0\0' * round(duration * 16000))
            with patch('config.REF_MAP', {'悠闲': (str(path), 'test')}), patch('scripts.start_tts.check_files', return_value=[]):
                check_release_data()

    def test_short_and_long_references_block_release_with_expression_name(self):
        for duration in (2.89, 10.1):
            with self.subTest(duration=duration):
                with self.assertRaisesRegex(ValueError, '悠闲.*3.*10'):
                    self.check_audio(duration)

    def test_valid_duration_including_endpoints_is_accepted(self):
        for duration in (3, 5.2, 10):
            with self.subTest(duration=duration):
                self.check_audio(duration)
