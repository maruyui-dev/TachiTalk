"""常驻麦克风线程；静音不入下游队列，播放时按打断开关接受一个候选片段。"""
import asyncio
from dataclasses import replace
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import perf_counter

import pyaudio
import webrtcvad

from config import Settings
from app.core.models import AudioSegment
from app.audio.vad import SpeechSegmenter
from app.audio.devices import apply_input_volume, enumerate_inputs


class TurnGate:
    """先预约再提交，防止调度线程尚未取走片段时重复触发。"""

    def __init__(self):
        self._busy = False
        self._lock = Lock()

    @property
    def busy(self):
        with self._lock:
            return self._busy

    def claim(self) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def release(self):
        with self._lock:
            self._busy = False


class AudioCapture:
    def __init__(self, settings: Settings, gate: TurnGate, controls=None):
        self.settings = settings
        self.gate = gate
        self.controls = controls
        self.segments: Queue[AudioSegment] = Queue(maxsize=settings.segment_queue_size)
        self.notices: Queue[tuple[str, str]] = Queue(maxsize=8)
        self.segmenter = SpeechSegmenter(
            sample_rate=settings.sample_rate, frame_ms=settings.frame_ms,
            pre_roll_ms=settings.pre_roll_ms, start_frames=settings.start_frames,
            silence_ms=settings.silence_ms, max_seconds=settings.max_segment_seconds)
        self.detector = webrtcvad.Vad(settings.vad_mode)
        self.ready = Event()
        self.stop_event = Event()
        self.available = asyncio.Event()
        self.thread: Thread | None = None
        self.loop = None
        self.dropped_segments = 0
        self.overflow_count = 0
        self.queue_high_water = 0
        self._was_busy = False
        self._quiet_frames = 0
        self._manual_active = False
        self._manual_token = 0

    def notice(self, kind, message):
        try:
            self.notices.put_nowait((kind, message))
        except Full:
            try:
                self.notices.get_nowait()
            except Empty:
                pass
            try:
                self.notices.put_nowait((kind, message))
            except Full:
                pass  # 状态通知不阻塞麦克风；队列容量始终为8。

    def accept_frame(self, frame: bytes, *, speech: bool, now: float, revision=None):
        manual = False
        if self.controls is not None:
            state = self.controls.capture_state()
            enabled, current = self.controls.recording_state()
            if (not enabled or state.testing or (revision is not None and revision != current)
                    or not self.controls.snapshot().ready):
                self.segmenter.reset()
                self._manual_active = False
                self._was_busy = True
                self._quiet_frames = 0
                return
            manual = state.options.mode != 'vad'
            if manual:
                if self._manual_active and (not state.manual_active or state.manual_token != self._manual_token):
                    segment = self.segmenter.finish()
                    if segment is not None and (not self.gate.busy or self.controls.can_interrupt()):
                        self._submit_segment(segment, current)
                starting = state.manual_active and (not self._manual_active or state.manual_token != self._manual_token)
                self._manual_active, self._manual_token = state.manual_active, state.manual_token
                if not state.manual_active or (self.gate.busy and not self.controls.can_interrupt()):
                    self.segmenter.reset()
                    return
                if starting:
                    self.segmenter.reset()
                    self._was_busy = False
        interrupting = self.controls is not None and self.controls.can_interrupt()
        if interrupting:
            self._was_busy = False
        if self.gate.busy and not interrupting:
            if not self._was_busy:
                self.segmenter.reset()
            self._was_busy = True
            self._quiet_frames = 0
            return
        if self._was_busy:
            self._quiet_frames = 0 if speech else self._quiet_frames + 1
            if self._quiet_frames * self.settings.frame_ms < self.settings.resume_silence_ms:
                return
            self._was_busy = False
            self.segmenter.reset()

        was_active = self.segmenter.active
        segment = self.segmenter.feed(frame, speech=speech, now=now, auto_finish=not manual)
        if not was_active and self.segmenter.active:
            self.notice("speech", "检测到开口，正在收集本句话")
        if segment is None:
            return
        self._submit_segment(segment, current if self.controls is not None else 0)

    def _submit_segment(self, segment, revision):
        if self.controls is not None:
            if self.controls.offer_audio(segment, revision):
                self.queue_high_water = 1
            return
        if not self.gate.claim():
            return
        try:
            self.segments.put_nowait(segment)
        except Full:
            self.dropped_segments += 1
            self.notice("warning", "语音队列已满，丢弃新片段；保留已预约的对话")
            return
        self.queue_high_water = max(self.queue_high_water, self.segments.qsize())
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.available.set)  # 每句话一次，不是每帧一次。

    def _scan_devices(self, audio=None):
        if self.controls is None or not self.controls.take_device_scan():
            return
        owned = audio is None
        try:
            if owned:
                audio = pyaudio.PyAudio()
            devices = enumerate_inputs(audio)
            self.controls.finish_device_scan(devices)
            self.notice('device', f'已获取{len(devices)}个可用麦克风输入端点')
        except Exception as error:
            message = f'获取麦克风设备失败：{error}'
            self.controls.finish_device_scan(error=message)
            self.notice('error', message)
        finally:
            if owned and audio is not None:
                audio.terminate()

    def _apply_capture_options(self, options):
        self.settings = replace(self.settings, input_device=options.device, sample_rate=options.sample_rate)
        self.segmenter = SpeechSegmenter(
            sample_rate=self.settings.sample_rate, frame_ms=self.settings.frame_ms,
            pre_roll_ms=self.settings.pre_roll_ms, start_frames=self.settings.start_frames,
            silence_ms=self.settings.silence_ms, max_seconds=self.settings.max_segment_seconds,
            trim_silence=options.trim_silence)
        self._manual_active = False
        self._was_busy = True
        self._quiet_frames = 0

    async def next_segment(self) -> AudioSegment:
        while True:
            try:
                return self.segments.get_nowait()
            except Empty:
                self.available.clear()
                await self.available.wait()

    def start(self):
        self.loop = asyncio.get_running_loop()
        self.thread = Thread(target=self._run, name="microphone", daemon=False)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            state = self.controls.capture_state() if self.controls is not None else None
            enabled, revision = (state.enabled, state.revision) if state is not None else (True, 0)
            if not enabled:
                self.segmenter.reset()
                self._scan_devices()
                self.controls.wait_capture_change(revision, self.stop_event)
                continue
            audio = stream = None
            try:
                audio = pyaudio.PyAudio()
                self._scan_devices(audio)
                if state is not None:
                    self._apply_capture_options(state.options)
                    device = state.options.device
                    if device is None:
                        device = int(audio.get_default_input_device_info()['index'])
                    if state.options.device_name and audio.get_device_info_by_index(device)['name'] != state.options.device_name:
                        raise ValueError('所选麦克风已变化，请重新获取设备并选择')
                    audio.is_format_supported(self.settings.sample_rate, input_device=device, input_channels=1,
                                              input_format=pyaudio.paInt16)
                stream = audio.open(
                    format=pyaudio.paInt16, channels=1, rate=self.settings.sample_rate,
                    input=True, frames_per_buffer=self.settings.frame_samples,
                    input_device_index=self.settings.input_device)
                if self.controls is None or self.controls.capture_state().revision == revision:
                    self.ready.set()
                    if self.controls is not None:
                        self.controls.set_capture_active(True)
                        self.controls.set_audio_error('')
                    self.notice("device", "麦克风已打开，保持持续采集")
                while not self.stop_event.is_set():
                    if self.controls is not None:
                        current = self.controls.capture_state()
                        if not current.enabled or current.revision != revision:
                            break
                        self._scan_devices(audio)
                    try:
                        frame = stream.read(self.settings.frame_samples)
                    except OSError as error:
                        if error.args and error.args[0] == pyaudio.paInputOverflowed:
                            self.overflow_count += 1
                            self.segmenter.reset()
                            self.notice("warning", "设备输入缓冲溢出：已丢弃不完整语音并重新分段")
                            continue
                        raise
                    if self.controls is not None:
                        frame, level = apply_input_volume(frame, self.controls.capture_state().options.volume)
                        self.controls.report_level(level)
                    speech = self.detector.is_speech(frame, self.settings.sample_rate)
                    self.accept_frame(frame, speech=speech, now=perf_counter(), revision=revision)
            except Exception as error:
                message = f'麦克风错误：{error}。请检查所选设备、采样率、系统麦克风权限或设备占用，稍后重试'
                if self.controls is not None:
                    self.controls.set_audio_error(message)
                self.notice('error', message)
            finally:
                self.ready.clear()
                self.segmenter.reset()
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        self.notice("warning", "麦克风驱动关闭失败，请检查设备")
                if audio is not None:
                    audio.terminate()
                if self.controls is not None:
                    self.controls.set_capture_active(False)
            if self.controls is None:
                self.stop_event.wait(self.settings.retry_delay)
            else:
                self.controls.wait_capture_change(revision, self.stop_event, self.settings.retry_delay)

    def close(self):
        self.stop_event.set()
        if self.controls is not None:
            self.controls.wake()
        if self.thread is not None:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                raise RuntimeError("麦克风驱动未在3秒内释放，请检查设备占用")
