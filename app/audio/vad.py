"""人声检测与有界语音分段。"""
from collections import deque
from app.core.models import AudioFormat, AudioSegment


class SpeechSegmenter:
    def __init__(self, *, sample_rate=16000, frame_ms=20, pre_roll_ms=300,
                 start_frames=5, silence_ms=600, max_seconds=20, trim_silence=True):
        self.pre_roll = deque(maxlen=pre_roll_ms // frame_ms)
        self.pre_speech = deque(maxlen=self.pre_roll.maxlen)
        self.trim_silence = trim_silence
        self.frames = []
        self.format = AudioFormat(sample_rate)
        self.frame_bytes = sample_rate * frame_ms // 1000 * 2
        self.start_frames = start_frames
        self.end_frames = silence_ms // frame_ms
        self.max_frames = int(max_seconds * 1000 / frame_ms)
        self.tail_frames = max(1, 100 // frame_ms)
        if (self.pre_roll.maxlen < start_frames or self.end_frames < 1
                or self.max_frames < start_frames):
            raise ValueError("预录长度、结束静音和单段上限不匹配")
        self.max_frames_seen = 0
        self.reset()

    def feed(self, frame: bytes, *, speech: bool, now: float, auto_finish=True) -> AudioSegment | None:
        if len(frame) != self.frame_bytes:
            raise ValueError("音频帧必须是指定长度的16位单声道PCM")
        if not self.active:
            self.pre_roll.append(frame)
            self.pre_speech.append(speech)
            self.speech_frames = self.speech_frames + 1 if speech else 0
            if self.speech_frames < self.start_frames:
                return None
            self.active = True
            beginning = list(self.pre_roll)
            if self.trim_silence:
                first = next((i for i, voiced in enumerate(self.pre_speech) if voiced), 0)
                beginning = beginning[max(0, first - self.tail_frames):]
            self.frames.extend(beginning)  # 保留约100ms起音保护，避免切掉首字。
            self.pre_roll.clear()
            self.pre_speech.clear()
        else:
            self.frames.append(frame)

        if speech:
            self.last_speech_at = now
            self.silence_frames = 0
        else:
            self.silence_frames += 1
        self.max_frames_seen = max(self.max_frames_seen, len(self.frames))
        limited = len(self.frames) >= self.max_frames
        if not limited and (not auto_finish or self.silence_frames < self.end_frames):
            return None

        return self.finish('limit' if limited else 'silence')

    def finish(self, reason='manual'):
        if not self.active:
            self.reset()
            return None

        # 判定句尾需要600ms静音，上传只保留末尾100ms；句中停顿不删除。
        keep = len(self.frames)
        if self.trim_silence and reason != 'limit':
            keep -= max(0, self.silence_frames - self.tail_frames)
        segment = AudioSegment(b"".join(self.frames[:keep]), self.format,
                               self.last_speech_at, reason)
        self.reset()
        return segment

    def reset(self):
        self.pre_roll.clear()
        self.pre_speech.clear()
        self.frames.clear()
        self.active = False
        self.speech_frames = 0
        self.silence_frames = 0
        self.last_speech_at = 0.0
