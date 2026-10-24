"""Qt主线程显示；原语音asyncio循环在一个可取消的后台线程运行。"""
import asyncio
import signal
import sys
from dataclasses import replace
from functools import partial
from threading import Event, Lock, Thread

from PySide6.QtCore import QObject, QTimer, Qt, Signal, QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox
from app.paths import DATA_ROOT, FROZEN

from app.ui.desktop_pet import DesktopPetWindow
from app.ui.control_panel import load_window, remember_session, RESOURCE_DIRECTORY, RESOURCE_STATE, RESOURCE_BUBBLE_DIRECTORY
from app.core.resources import ResourceLibrary
from app.core.portrait_packs import PackResources
from app.core.pipeline import run_application
from app.core.conversation_input import ConversationInput
from app.core.persona import PersonaStore
from app.core.audio_input import RecordingOptions
from app.core.voice_settings import VoiceSettings
from app.core.ai_settings import AISettings
from app.core.expressions import ExpressionStore
from app.ui.console import ConsoleUI


class DesktopSignals(QObject):
    transcript = Signal(str)
    caption = Signal(int, str)
    expression = Signal(int, str)
    reply_finished = Signal(int)
    backend_stopped = Signal()
    input_state = Signal(object)


class CaptionRelay(QObject):
    """后台只覆盖一条待显示文本，Qt定期取最新值，避免每个token排一个界面事件。"""
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self._lock = Lock()
        self._latest = None
        self._newest_turn = -1
        self._closed = False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.flush)
        self.timer.start()

    def offer(self, turn_id, text):
        with self._lock:
            if not self._closed and turn_id >= self._newest_turn:
                self._newest_turn = turn_id
                self._latest = (turn_id, text)

    def flush(self):
        with self._lock:
            latest, self._latest = self._latest, None
        if latest is not None:
            self.pet.set_reply_text(*latest)

    def close(self):
        self.timer.stop()
        with self._lock:
            self._closed = True
            self._latest = None


class DesktopUI(ConsoleUI):
    def __init__(self, signals, max_parts):
        super().__init__(max_parts)
        self.signals = signals

    def transcript(self, text):
        super().transcript(text)
        self.signals.transcript.emit(text)

    def caption(self, turn_id, part_id, text):
        combined = super().caption(turn_id, part_id, text)
        if combined is not None:
            self.signals.caption.emit(turn_id, combined)

    def part_started(self, turn_id, part_id, expression):
        self.signals.expression.emit(turn_id, expression)

    def end_reply(self, turn_id):
        super().end_reply(turn_id)
        self.signals.reply_finished.emit(turn_id)


class VoiceWorker:
    def __init__(self, settings, ui, signals, application=None, audio=None):
        self.settings, self.ui, self.signals = settings, ui, signals
        self.audio = audio
        self.inputs = ConversationInput(on_change=signals.input_state.emit,
                                        audio_options=RecordingOptions(device=settings.input_device, sample_rate=settings.sample_rate))
        self.profiles = PersonaStore()
        from app.core.history import ConversationHistory
        from app.core.session_file import SessionFile
        self.history = ConversationHistory(SessionFile(DATA_ROOT / 'memory/conversation.dat'), report=self.ui.error)
        self.voices = VoiceSettings(settings)
        self.ai = AISettings(settings)
        self.expressions = ExpressionStore(settings.available_expressions, settings.default_expression)
        self.ui.ai_settings = self.ai
        self.ui.voice_settings = self.voices
        self.application = application if application is not None else partial(
            run_application, inputs=self.inputs, profiles=self.profiles, voices=self.voices, ai=self.ai,
            expressions=self.expressions, audio=self.audio, history=self.history)
        self.stop_event = Event()
        self.lock = Lock()
        self.loop = self.task = None
        self.thread = Thread(target=self._run, name="voice-loop", daemon=False)

    def start(self):
        self.thread.start()

    def request_stop(self):
        self.stop_event.set()
        self.inputs.close()
        with self.lock:
            loop, task = self.loop, self.task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # 后台已完成清理、关闭循环时，不重复发停止请求。

    async def _serve(self):
        with self.lock:
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.current_task()
        from app.services.local_tts import LocalTTSService
        service = LocalTTSService(self.ui)
        self.voices.local_service = service
        try:
            while not self.stop_event.is_set():
                try:
                    await self.application(self.settings, self.ui)
                except asyncio.CancelledError:
                    if self.stop_event.is_set():
                        return
                    raise  # 意外取消交给外层重建循环，不在已取消的任务中继续运行。
                except Exception as error:
                    self.ui.error(f"语音后台错误（{type(error).__name__}），稍后重建链路")
                if not self.stop_event.is_set():
                    await asyncio.sleep(self.settings.retry_delay)
        finally:
            await service.close()
            self.voices.local_service = None

    def _run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    asyncio.run(self._serve())
                except asyncio.CancelledError:
                    if not self.stop_event.is_set():
                        self.ui.error("语音后台循环意外取消，稍后重建")
                except Exception as error:
                    self.ui.error(f"语音循环无法运行（{type(error).__name__}），稍后重试")
                finally:
                    with self.lock:
                        self.loop = self.task = None
                if not self.stop_event.is_set():
                    self.stop_event.wait(self.settings.retry_delay)
        finally:
            self.signals.backend_stopped.emit()


def run_desktop(settings, catalog, startup_logs=None):
    if sys.platform == 'win32':
        import ctypes
        # A stable explicit identity keeps Windows taskbar grouping on the app.
        set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = (ctypes.c_wchar_p,)
        set_id.restype = ctypes.c_long
        set_id('TachiTalk.Desktop')
    app = QApplication([sys.argv[0]])
    from app.ui.control_panel import make_icon
    app.setWindowIcon(make_icon('cat', size=48))
    instance_lock = None
    if FROZEN:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        instance_lock = QLockFile(str(DATA_ROOT / 'running.lock'))
        if not instance_lock.tryLock(0):
            QMessageBox.information(None, 'TachiTalk', 'TachiTalk已经运行，请使用已有控制面板。')
            return 0
    # 控制面板关闭后先取消语音，后台资源收尾后再退出Qt。
    app.setQuitOnLastWindowClosed(False)
    from config import REF_MAP
    library = PackResources(ResourceLibrary(RESOURCE_DIRECTORY, RESOURCE_STATE, catalog=catalog, expressions=REF_MAP),
                            bubble_directory=RESOURCE_BUBBLE_DIRECTORY)
    mapped_catalog = library.catalog()
    # Settings保留启动用的TTS默认值；自定义立绘名通过独立快照动态传给LLM。
    settings = replace(settings, available_expressions=tuple(name for name in mapped_catalog.names if name in REF_MAP),
                       default_expression=mapped_catalog.default)
    window = DesktopPetWindow(catalog=mapped_catalog)
    # 两个窗口共用Qt主线程；保留引用，让控制面板随主程序常驻。
    startup_records = startup_logs.drain() if startup_logs is not None else ()
    control_panel = load_window(startup_records=startup_records, pet=window, library=library)
    signals = DesktopSignals()
    ui = DesktopUI(signals, settings.max_reply_parts)
    worker = VoiceWorker(settings, ui, signals, audio=control_panel.audio_resource_controls.library)
    control_panel.conversation_controls.bind_inputs(worker.inputs, signals)
    control_panel.persona_controls.bind_profiles(worker.profiles)
    control_panel.persona_controls.bind_history(worker.history)
    control_panel.audio_controls.bind_inputs(worker.inputs)
    control_panel.voice_controls.bind_runtime(worker.voices, worker.inputs)
    control_panel.audio_resource_controls.bind_runtime(worker.voices)
    control_panel.ai_controls.bind_runtime(worker.ai, worker.inputs)
    control_panel.resource_controls.bind_expressions(worker.expressions)
    remember_session(control_panel)
    # The last visited download page must not become a forced startup screen.
    from PySide6.QtWidgets import QStackedWidget
    if ('--install-voice' not in sys.argv and
            control_panel.findChild(QStackedWidget, 'pageStack').currentWidget().objectName() == 'deliveryPage'):
        control_panel.select_page(0, show_notice=False)
    from app.core.components import prepare_optional_voice
    if not prepare_optional_voice(worker.voices):
        control_panel.voice_controls.apply_preferences()
        ui.info('本地语音未安装、资源不完整或配置不可用，已启用文字模式；可在“更新与语音资源”中安装或修复。')
    from app.ui.voice_install_controls import VoiceInstallControls
    control_panel.voice_install_controls = VoiceInstallControls(control_panel)
    control_panel.voice_install_controls.refresh()
    queued = Qt.ConnectionType.QueuedConnection
    caption_relay = CaptionRelay(window)
    signals.transcript.connect(window.add_transcript, queued)
    signals.caption.connect(caption_relay.offer, Qt.ConnectionType.DirectConnection)
    signals.expression.connect(window.play_expression, queued)
    signals.reply_finished.connect(window.finish_expression, queued)
    signals.backend_stopped.connect(app.quit, queued)
    control_panel.closing.connect(worker.request_stop)
    control_panel.closing.connect(caption_relay.close)
    control_panel.closing.connect(window.shutdown)

    shutdown_requested = Event()
    previous_handlers = {}
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            sig = getattr(signal, name)
            previous_handlers[sig] = signal.signal(sig, lambda *_: shutdown_requested.set())
    heartbeat = QTimer()
    heartbeat.setInterval(100)
    heartbeat.timeout.connect(lambda: control_panel.close() if shutdown_requested.is_set() else None)
    heartbeat.start()
    worker.start()
    if not control_panel.session_controls.loaded or control_panel.session_controls.pet_visible:
        window.show()
    control_panel.show()
    def check_updates():
        if control_panel._closing:
            return
        controls = control_panel.ensure_update_controls(show='--install-voice' in sys.argv)
        if controls is not None:
            if '--install-voice' in sys.argv:
                controls.install_voice()
            else:
                controls.check(automatic=True)
    from app.updates.main_feed import ENABLED as main_checks_enabled
    if main_checks_enabled or '--install-voice' in sys.argv:
        QTimer.singleShot(1200, check_updates)
    try:
        return app.exec()
    finally:
        heartbeat.stop()
        control_panel.close()
        window.shutdown()
        worker.request_stop()
        worker.thread.join(timeout=8)
        if worker.thread.is_alive():
            ui.error("后台设备尚未退出，请检查音频驱动占用")
        for sig, previous in previous_handlers.items():
            signal.signal(sig, previous)
