"""有界音频消费；所有设备调用在同一个播放执行器中串行执行。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import math
from time import perf_counter

import sounddevice as sd

from config import Settings
from app.core.models import AudioChunk, StageError
from app.audio.devices import apply_input_volume
from app.core.audio_input import InputDevice


class AudioPlayer:
    def __init__(self, settings: Settings, stream_factory=None):
        self.settings = settings
        self.stream_factory = stream_factory or sd.RawOutputStream
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio-output")
        self.stream = None
        self.format = None
        self.underflows = 0
        self.closed = False
        self.voices = None
        self.output_device = settings.output_device

    async def device_call(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, function, *args)

    def _write(self, chunk: AudioChunk):
        alignment = chunk.format.channels * chunk.format.sample_width
        max_bytes = chunk.format.sample_rate * self.settings.frame_ms // 1000 * alignment
        if not chunk.pcm or len(chunk.pcm) % alignment or len(chunk.pcm) > max_bytes:
            raise StageError("播放", "音频块长度或采样边界不正确")
        options = self.voices.snapshot().output if self.voices is not None else None
        device = options.device if options is not None else self.settings.output_device
        if self.format != chunk.format or self.output_device != device:
            self._close_device()
            self.stream = self.stream_factory(
                samplerate=chunk.format.sample_rate, channels=chunk.format.channels,
                dtype="int16", device=device, latency="low")
            self.format = chunk.format
            self.output_device = device
        if not self.stream.active:
            self.stream.start()
        submitted_at = perf_counter()
        pcm = apply_input_volume(chunk.pcm, options.volume)[0] if options is not None and options.volume != 100 else chunk.pcm
        if self.stream.write(pcm):
            self.underflows += 1
        return submitted_at

    async def output_devices(self):
        def enumerate_devices():
            devices, hosts = sd.query_devices(), sd.query_hostapis()
            return tuple(InputDevice(i, str(d['name']), str(hosts[d['hostapi']]['name']))
                         for i, d in enumerate(devices) if d['max_output_channels'] > 0)
        return await self.device_call(enumerate_devices)

    def _stop_device(self, abort=False):
        if self.stream is not None and self.stream.active:
            if abort:
                self.stream.abort()
            else:
                self.stream.stop()  # 等待设备已有缓冲播完，再解除本轮忙碌。

    def _close_device(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
            self.format = None

    async def play(self, queue: asyncio.Queue, on_first_audio=None, on_part_start=None):
        finished = False
        first = True
        last_part = None
        pre_buffer = []
        count = math.ceil(self.settings.playback_start_ms / self.settings.frame_ms)

        async def write_chunk(chunk):
            nonlocal first, last_part
            submitted_at = await self.device_call(self._write, chunk)
            if first and on_first_audio:
                on_first_audio(submitted_at)
            first = False
            if chunk.part_id is not None and chunk.part_id != last_part:
                if on_part_start:
                    on_part_start(chunk.part_id, chunk.expression, submitted_at)
                last_part = chunk.part_id

        try:
            # 只有首次启动积累少量预缓冲，不等待完整句子合成。
            while len(pre_buffer) < count:
                chunk = await queue.get()
                if chunk is None:
                    finished = True
                    break
                pre_buffer.append(chunk)
            for chunk in pre_buffer:
                await write_chunk(chunk)
            pre_buffer.clear()
            while not finished:
                chunk = await queue.get()
                if chunk is None:
                    finished = True
                    break
                await write_chunk(chunk)
        except StageError:
            raise
        except Exception as error:
            raise StageError("播放", f"音频设备不可用（{type(error).__name__}），请检查输出设备和系统权限") from error
        finally:
            try:
                await self.device_call(self._stop_device, not finished)
            finally:
                if not finished:
                    # 驱动报错后的流状态不再可信，下轮重新打开设备。
                    await self.device_call(self._close_device)

    async def close(self):
        if not self.closed:
            await self.device_call(self._close_device)
            self.executor.shutdown(wait=True)
            self.closed = True
