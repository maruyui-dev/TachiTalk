"""回复与试听共用唯一输出设备；新任务按开关抢占，取消后等待旧流清理。"""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from difflib import SequenceMatcher
from time import perf_counter
import unicodedata


class PlaybackBus:
    def __init__(self, player, voices, inputs):
        self.player, self.voices, self.inputs = player, voices, inputs
        self.lock = asyncio.Lock()
        self.owner = None
        self._spoken = deque(maxlen=8)
        self._echo_until = 0.0

    @asynccontextmanager
    async def lease(self):
        current, previous = asyncio.current_task(), self.owner
        if previous is not None and previous is not current and self.voices.snapshot().tts.interrupt:
            previous.cancel()
            await asyncio.gather(previous, return_exceptions=True)
        async with self.lock:
            self.owner = current
            try:
                yield
            finally:
                self._echo_until = perf_counter() + 2
                self.inputs.set_playback_active(False)
                self.owner = None

    def started(self):
        self.inputs.set_playback_active(True)

    def remember(self, text):
        self._spoken.append(self._normalize(text))

    @staticmethod
    def _normalize(text):
        return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text) if c.isalnum())

    def is_echo(self, text, captured_at):
        if not self.inputs.playback_active() and captured_at > self._echo_until:
            return False
        value = self._normalize(text)
        if not value:
            return False
        for spoken in self._spoken:
            if not spoken:
                continue
            if value == spoken or (len(value) >= 3 and value in spoken):
                return True
            if SequenceMatcher(None, value, spoken).ratio() >= .92:
                return True
        return False
