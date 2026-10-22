import unittest

from app.audio.vad import SpeechSegmenter


class SegmenterTests(unittest.TestCase):
    def feed_many(self, detector, count, speech, start=0):
        results = []
        for number in range(count):
            result = detector.feed(b"\x01\x00" * 320, speech=speech,
                                   now=(start + number) * .02)
            if result is not None:
                results.append(result)
        return results

    def test_an_hour_of_silence_has_no_segments_and_bounded_pre_roll(self):
        detector = SpeechSegmenter()
        self.assertEqual(self.feed_many(detector, 180000, False), [])
        self.assertEqual(len(detector.pre_roll), 15)
        self.assertEqual(len(detector.frames), 0)

    def test_isolated_click_does_not_start_a_turn(self):
        detector = SpeechSegmenter()
        self.feed_many(detector, 20, False)
        self.feed_many(detector, 1, True, 20)
        self.assertEqual(self.feed_many(detector, 100, False, 21), [])
        self.assertEqual(len(detector.frames), 0)

    def test_end_of_speech_retains_beginning_and_clears_turn(self):
        detector = SpeechSegmenter()
        self.feed_many(detector, 15, False)
        self.feed_many(detector, 20, True, 15)
        self.assertEqual(self.feed_many(detector, 29, False, 35), [])
        results = self.feed_many(detector, 1, False, 64)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].reason, "silence")
        self.assertGreaterEqual(results[0].duration, .4)
        self.assertAlmostEqual(results[0].last_speech_at, .68)
        self.assertEqual(len(detector.frames), 0)

    def test_sustained_noise_cannot_grow_one_segment_past_limit(self):
        detector = SpeechSegmenter(max_seconds=1)
        results = self.feed_many(detector, 500, True)
        self.assertGreater(len(results), 0)
        self.assertTrue(all(item.duration <= 1 for item in results))
        self.assertLess(len(detector.frames), 50)

    def test_brief_pause_is_kept_in_the_same_utterance(self):
        detector = SpeechSegmenter()
        self.feed_many(detector, 10, True)
        self.assertEqual(self.feed_many(detector, 15, False, 10), [])
        self.feed_many(detector, 10, True, 25)
        self.assertEqual(len(self.feed_many(detector, 30, False, 35)), 1)

    def test_incorrect_frame_size_is_rejected(self):
        with self.assertRaises(ValueError):
            SpeechSegmenter().feed(b"short", speech=False, now=0)
