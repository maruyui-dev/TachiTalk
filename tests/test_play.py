from io import BytesIO
import struct
import unittest
import wave

from app.core.models import StageError
from app.services.tts import WaveStreamDecoder


def wav_bytes(pcm=b"", rate=32000):
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm)
    return buffer.getvalue()


class WaveDecoderTests(unittest.TestCase):
    def test_zero_length_stream_header_does_not_discard_following_pcm(self):
        pcm = b"\x01\x02" * 1500
        payload = wav_bytes() + pcm
        decoder = WaveStreamDecoder()
        chunks = []
        for number in range(0, len(payload), 7):
            chunks.extend(decoder.feed(payload[number:number+7]))
        chunks.extend(decoder.finish())
        self.assertEqual(b"".join(item.pcm for item in chunks), pcm)
        self.assertTrue(all(len(item.pcm) <= 1280 for item in chunks))
        self.assertEqual(chunks[0].format.sample_rate, 32000)

    def test_normal_wav_survives_every_header_boundary(self):
        pcm = b"\x03\x00" * 1000
        payload = wav_bytes(pcm)
        for boundary in range(1, 45):
            decoder = WaveStreamDecoder()
            chunks = decoder.feed(payload[:boundary]) + decoder.feed(payload[boundary:]) + decoder.finish()
            self.assertEqual(b"".join(item.pcm for item in chunks), pcm)

    def test_invalid_wav_and_unaligned_pcm_are_rejected(self):
        with self.assertRaises(StageError):
            WaveStreamDecoder().feed(b"not audio at all")
        decoder = WaveStreamDecoder()
        decoder.feed(wav_bytes() + b"x")
        with self.assertRaises(StageError):
            decoder.finish()

    def test_oversized_header_and_infinite_tts_output_are_bounded(self):
        with self.assertRaises(StageError):
            WaveStreamDecoder().feed(b"RIFF" + struct.pack("<I", 0) + b"WAVEJUNK" + struct.pack("<I", 1000000))
        decoder = WaveStreamDecoder(max_seconds=1)
        with self.assertRaises(StageError):
            decoder.feed(wav_bytes() + b"\0\0" * 32001)
