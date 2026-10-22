"""Qt、麦克风线程与asyncio之间的单轮输入协调；所有待处理输入合计最多一条。"""
import asyncio
from dataclasses import dataclass, replace
from queue import Empty, Full, Queue
from threading import Condition, Lock
from time import perf_counter

from app.audio.record import TurnGate
from app.core.models import AudioSegment
from app.core.audio_input import AudioStatus, CaptureState, RecordingOptions


@dataclass(frozen=True, slots=True)
class InputRequest:
    payload: str | AudioSegment
    submitted_at: float
    revision: int


@dataclass(frozen=True, slots=True)
class InputState:
    recording: bool
    capture_active: bool
    ready: bool
    busy: bool
    message: str
    can_interrupt: bool = False


class ConversationInput:
    def __init__(self, on_change=None, audio_options=None):
        self.gate = TurnGate()
        self.pending = Queue(maxsize=1)
        self.on_change = on_change
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._recording = True
        self._revision = 0
        self._capture_active = False
        self._services = set()
        self._blocked = set()
        self._active = 0
        self._closed = False
        self._loop = self._changed = None
        self._wake_pending = False
        self._audio_options = audio_options or RecordingOptions()
        self._testing = self._manual_active = False
        self._manual_token = 0
        self._level = self._test_peak = self._test_frames = 0
        self._audio_error = self._scan_error = ''
        self._devices = ()
        self._scan_requested = self._scanning = False
        self._scan_version = 0
        self._auto_read = self._auto_send = True
        self._interrupt = False
        self._playing = False
        self._review_pending = False

    def reply_ready(self):
        with self._lock:
            return not self._closed and ({'LLM', 'TTS'} if self._auto_read else {'LLM'}) <= self._services

    def set_review_pending(self, pending):
        with self._lock:
            self._review_pending = pending
        self.publish()

    def set_voice_preferences(self, *, auto_read, auto_send, interrupt):
        with self._lock:
            self._auto_read, self._auto_send, self._interrupt = auto_read, auto_send, interrupt
            if auto_send:
                self._review_pending = False
        self.publish()

    def _can_interrupt(self):
        return self._interrupt and self._playing and self._active <= 1 and self.pending.empty() and not self._testing and not self._closed

    def can_interrupt(self):
        with self._lock:
            return self._can_interrupt()

    def playback_active(self):
        with self._lock:
            return self._playing

    def set_playback_active(self, active):
        with self._lock:
            changed = self._playing != active
            self._playing = active
        if changed:
            self.publish()

    def _capture_state(self):
        return CaptureState((self._recording or self._testing) and not self._closed, self._revision,
                            self._audio_options, self._testing, self._manual_active, self._manual_token)

    def capture_state(self):
        with self._lock:
            return self._capture_state()

    def audio_status(self):
        with self._lock:
            return AudioStatus(self._capture_state(), self._capture_active, self._level, self._test_peak,
                               self._test_frames, self._audio_error, self._devices, self._scanning,
                               self._scan_version, self._scan_error)

    def configure_audio(self, **changes):
        with self._lock:
            options = replace(self._audio_options, **changes)
            options.validate()
            if options == self._audio_options or self._closed:
                return
            restart = replace(options, volume=self._audio_options.volume) != self._audio_options
            self._audio_options = options
            if restart:
                self._revision += 1
                self._manual_active = False
                self._audio_error = ''
                self._discard_pending_audio()
        self.publish()

    def set_manual_active(self, active):
        with self._lock:
            if active and (self._closed or not self._recording or self._testing
                           or self._audio_options.mode == 'vad' or (self.gate.busy and not self._can_interrupt()) or not self._ready()):
                return False
            if active == self._manual_active:
                return True
            self._manual_active = active
            if active:
                self._manual_token += 1
        self.publish()
        return True

    def set_testing(self, active):
        with self._lock:
            if self._closed or self._testing == active:
                return
            self._testing = active
            self._manual_active = False
            self._revision += 1
            self._discard_pending_audio()
            if active:
                self._test_peak = self._test_frames = 0
                self._audio_error = ''
        self.publish()

    def report_level(self, level):
        with self._lock:
            self._level = level
            if self._testing:
                self._test_frames += 1
                self._test_peak = max(self._test_peak, level)

    def set_audio_error(self, message):
        with self._lock:
            self._audio_error = message

    def request_device_scan(self):
        with self._lock:
            if self._closed or self._scanning:
                return
            self._scan_requested = self._scanning = True
            self._scan_error = ''
        self.wake()

    def take_device_scan(self):
        with self._lock:
            requested, self._scan_requested = self._scan_requested, False
            return requested

    def finish_device_scan(self, devices=(), error=''):
        with self._lock:
            self._devices = tuple(devices)
            self._scan_error = error
            self._scanning = False
            self._scan_version += 1

    def recording_state(self):
        with self._lock:
            return self._recording and not self._closed, self._revision

    def _ready(self):
        if self._recording and self._review_pending:
            return False
        required = set() if self._recording and not self._auto_send else {'LLM'}
        if self._auto_read and not (self._recording and not self._auto_send):
            required.add('TTS')
        if self._recording:
            required.add('ASR')
        return not self._closed and required <= self._services

    def snapshot(self):
        with self._lock:
            ready, busy = self._ready(), self.gate.busy
            if self._closed:
                message = '程序正在关闭'
            elif self._testing:
                message = '正在测试麦克风，测试声音不会触发对话'
            elif self._review_pending and self._recording and not busy:
                message = '识别完成，请在ASR确认框发送或丢弃本次文字'
            elif busy:
                message = '正在播放回复，可以开口打断' if self._can_interrupt() else '正在回复，请等待本轮完成'
            elif not {'LLM', *({'TTS'} if self._auto_read else set())} <= self._services and self._auto_send:
                message = 'LLM或TTS尚未就绪，请查看运行日志'
            elif self._recording and 'ASR' not in self._services:
                message = 'ASR尚未就绪；可关闭录音，改用文字对话'
            elif self._recording:
                mode = self._audio_options.mode
                if self._audio_error:
                    message = self._audio_error
                elif not self._capture_active:
                    message = '正在打开麦克风，请查看运行日志'
                elif mode == 'vad':
                    message = '录音已开启，等待开口'
                else:
                    message = ('正在录音，松开快捷键或点击结束后发送' if self._manual_active
                               else '等待按住录音快捷键' if mode == 'hold' else '等待点击开始录音')
            else:
                message = '正在释放麦克风，可输入文字对话' if self._capture_active else '录音已关闭，可输入文字对话'
            return InputState(self._recording, self._capture_active, ready, busy, message, self._can_interrupt())

    def publish(self):
        if self.on_change is not None:
            self.on_change(self.snapshot())
        self.wake()

    def wake(self):
        # 高频切换只保留一次事件循环唤醒，状态始终读取最新值。
        with self._condition:
            self._condition.notify_all()
            loop, event = self._loop, self._changed
            if loop is None or self._wake_pending:
                return
            self._wake_pending = True
        try:
            loop.call_soon_threadsafe(self._deliver_wake, event)
        except RuntimeError:
            pass  # 后台循环正在退出；下一次bind会重置唤醒状态。

    def _deliver_wake(self, event):
        with self._lock:
            if event is not self._changed:
                return
            self._wake_pending = False
        event.set()

    def bind_loop(self):
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._changed = asyncio.Event()
            self._wake_pending = False
            self._services.clear()
            self._blocked.clear()
            self._revision += 1
            self._discard_pending_audio()
        self.publish()

    def unbind_loop(self):
        with self._lock:
            self._loop = self._changed = None
            self._wake_pending = False
            self._services.clear()
        self.publish()

    def clear_wake(self):
        self._changed.clear()

    async def wait_changed(self):
        await self._changed.wait()

    def wait_capture_change(self, revision, stop_event, timeout=None):
        with self._condition:
            self._condition.wait_for(lambda: self._revision != revision or self._scan_requested
                                     or self._closed or stop_event.is_set(), timeout)

    def set_service_ready(self, name, ready=True):
        with self._lock:
            before = name in self._services
            if ready:
                self._services.add(name)
            else:
                self._services.discard(name)
        if before != ready:
            self.publish()

    def service_ready(self, name):
        with self._lock:
            return name in self._services

    def block_service(self, name):
        with self._lock:
            self._services.discard(name)
            self._blocked.add(name)
        self.publish()

    def invalidate_service(self, name):
        with self._lock:
            self._services.discard(name)
            self._blocked.discard(name)
            if name == 'ASR':
                self._revision += 1
                self._manual_active = False
                self._discard_pending_audio()
        self.publish()

    def service_blocked(self, name):
        with self._lock:
            return name in self._blocked

    def set_capture_active(self, active):
        with self._lock:
            changed = active != self._capture_active
            self._capture_active = active
            if not active:
                self._level = 0
        if changed:
            self.publish()

    def set_recording(self, enabled):
        with self._lock:
            if self._closed or self._recording == enabled:
                return
            self._recording = enabled
            self._manual_active = False
            if not enabled:
                self._testing = False
            self._revision += 1
            # 未开始的旧录音作废；已经接受的文字和正在播放的回复继续完成。
            self._discard_pending_audio()
        self.publish()

    def _discard_pending_audio(self):
        try:
            request = self.pending.get_nowait()
        except Empty:
            return
        self.pending.task_done()
        if isinstance(request.payload, str):
            self.pending.put_nowait(request)
        else:
            if not self._active:
                self.gate.release()

    def submit_text(self, text, from_asr=False):
        text = text.strip()
        with self._lock:
            if not text or len(text) > 2000:
                return False, '请输入1–2000字的对话内容'
            if self._recording and not from_asr:
                return False, '请先关闭录音，再使用文字输入'
            required = {'LLM', *({'TTS'} if self._auto_read else set())}
            if self._closed or not required <= self._services:
                return False, 'LLM或TTS尚未就绪，请查看运行日志后重试'
            claimed = not self.gate.busy
            if not (self.gate.claim() if claimed else self._can_interrupt()):
                return False, '本轮尚未完成，文字已保留，请稍后发送'
            try:
                self.pending.put_nowait(InputRequest(text, perf_counter(), self._revision))
            except Full:
                if claimed:
                    self.gate.release()
                return False, '输入队列已满，请稍后发送'
        self.publish()
        return True, '已发送，正在生成回复'

    def offer_audio(self, segment, revision):
        with self._lock:
            if not self._recording or self._testing or revision != self._revision or not self._ready():
                return False
            claimed = not self.gate.busy
            if not (self.gate.claim() if claimed else self._can_interrupt()):
                return False
            self._manual_active = False
            try:
                self.pending.put_nowait(InputRequest(segment, perf_counter(), revision))
            except Full:
                if claimed:
                    self.gate.release()
                return False
        self.publish()
        return True

    def take_next(self):
        with self._lock:
            try:
                request = self.pending.get_nowait()
            except Empty:
                return None
            self._active += 1
        return request

    def finish_turn(self):
        with self._lock:
            if self._active:
                self.pending.task_done()
                self._active -= 1
            if not self._active and self.pending.empty():
                self.gate.release()
        self.publish()

    def close(self):
        with self._lock:
            self._closed = True
            self._recording = False
            self._testing = self._manual_active = False
            self._revision += 1
            try:
                self.pending.get_nowait()
            except Empty:
                pass
            else:
                self.pending.task_done()
            if not self._active:
                self.gate.release()
        self.publish()
