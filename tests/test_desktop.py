import asyncio
from dataclasses import replace
from threading import Event
from time import monotonic
import json
import subprocess
import sys
import textwrap
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtCore import QThread, Qt, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.ui.pet.expressions import ExpressionCatalog
from app.ui.pet.pet_window import PetWindow

from config import Settings
from app.ui.desktop import DesktopSignals, DesktopUI, VoiceWorker


class DesktopStartupTests(unittest.TestCase):
    def test_main_shows_both_windows_and_panel_close_stops_the_program(self):
        self.check_main_shutdown(close_pet_first=False)

    def test_closing_pet_keeps_the_control_panel_and_backend_running(self):
        self.check_main_shutdown(close_pet_first=True)

    def check_main_shutdown(self, close_pet_first):
        # 用独立Qt进程验证真正的main入口；测试后台不会打开麦克风或调用API。
        script = f'close_pet_first = {close_pet_first!r}\n' + textwrap.dedent('''
            import asyncio
            import json
            from threading import Event
            from PySide6.QtCore import QTimer, Qt
            from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton
            from app.ui.pet.pet_window import PetWindow
            from app.ui import desktop
            import main

            entered, cleaned = Event(), Event()
            workers, result = [], {}
            original_worker = desktop.VoiceWorker

            async def idle_backend(settings, ui):
                entered.set()
                ui.info('后台运行日志联通验证')
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()

            def make_worker(settings, ui, signals, audio=None):
                worker = original_worker(settings, ui, signals, application=idle_backend, audio=audio)
                original_start = worker.start
                def checked_start():
                    panel = next(item for item in QApplication.topLevelWidgets()
                                 if hasattr(item, 'session_controls'))
                    result['restored_before_backend'] = panel.session_controls.restore_attempted
                    original_start()
                    # Functional checks begin once construction/restore finished. The 3s close
                    # watchdog must not fire during cold image/.ui loading under build I/O.
                    app = QApplication.instance()
                    QTimer.singleShot(0, app.check_windows)
                    QTimer.singleShot(3000, app.timeout_exit)
                worker.start = checked_start
                workers.append(worker)
                return worker

            class CheckedApplication(QApplication):
                def __init__(self, args):
                    super().__init__(args)

                def timeout_exit(self):
                    result['forced_exit'] = True
                    self.quit()

                def check_windows(self):
                    windows = self.topLevelWidgets()
                    pet = next((item for item in windows if isinstance(item, PetWindow)), None)
                    panel = next((item for item in windows if item.windowTitle().startswith('TachiTalk · ')), None)
                    result['pet_visible'] = pet is not None and pet.isVisible()
                    result['panel_visible'] = panel is not None and panel.isVisible()
                    result['persona_shared'] = (len(workers) == 1 and panel is not None
                                                and panel.persona_controls.profiles is workers[0].profiles)
                    result['expressions_shared'] = (len(workers) == 1 and panel is not None
                                                    and panel.resource_controls.expressions is workers[0].expressions)
                    result['audio_shared'] = (len(workers) == 1 and panel is not None
                                             and panel.audio_resource_controls.library is workers[0].audio
                                             and panel.audio_resource_controls.voices is workers[0].voices)
                    console = getattr(panel, 'runtime_console', None)
                    # 首次.ui加载可能晚于200ms；等后台就绪及首批日志落到文档再关闭。
                    if console is not None and (not entered.is_set() or console.pending_count):
                        QTimer.singleShot(25, self.check_windows)
                        return
                    result['backend_log_visible'] = console is not None and '后台运行日志联通验证' in console.view.toPlainText()
                    result['startup_log_visible'] = console is not None and '可用立绘/TTS表情' in console.view.toPlainText()
                    result['backend_log_count'] = console.view.toPlainText().count('后台运行日志联通验证') if console is not None else 0
                    hide = panel.findChild(QPushButton, 'hideButton')
                    hide.click()
                    result['hide_button_works'] = not pet.isVisible() and hide.text() == '显示角色'
                    result['hidden_status_correct'] = '已隐藏' in panel.findChild(QLabel, 'visibleStatus').text()
                    panel.findChild(QPushButton, 'navAI').click()
                    panel.findChild(QPushButton, 'navCharacter').click()
                    result['hidden_status_survives_navigation'] = '已隐藏' in panel.findChild(QLabel, 'visibleStatus').text()
                    hide.click()
                    result['show_button_works'] = pet.isVisible() and hide.text() == '隐藏角色'
                    top = panel.findChild(QCheckBox, 'topCheck')
                    top.setChecked(False)
                    result['top_toggle_works'] = not bool(pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) and pet.isVisible()
                    top.setChecked(True)
                    result['pet_remains_tool_window'] = pet.windowType() == Qt.WindowType.Tool
                    panel.findChild(QComboBox, 'rangeCombo').setCurrentIndex(1)
                    image = pet.character.ui.petLable.pixmap()
                    result['full_body_image'] = image.width() / image.height() < 0.4
                    if close_pet_first and pet is not None:
                        pet.close()
                        result['panel_keeps_running'] = panel is not None and panel.isVisible()
                        result['backend_keeps_running'] = len(workers) == 1 and not workers[0].stop_event.is_set()
                    if panel is not None:
                        panel.close()
                    result['pet_closed_with_panel'] = pet is not None and not pet.isVisible()
                    result['stop_requested_by_panel'] = len(workers) == 1 and workers[0].stop_event.is_set()

            desktop.QApplication = CheckedApplication
            desktop.VoiceWorker = make_worker
            result['exit_code'] = main.main()
            result['backend_started'] = entered.is_set()
            result['backend_cleaned'] = cleaned.is_set()
            result['worker_stopped'] = len(workers) == 1 and not workers[0].thread.is_alive()
            print(json.dumps(result))
        ''')
        with TemporaryDirectory() as directory:
            prefix = ('from pathlib import Path\nfrom app.ui import control_panel\n'
                      f'control_panel.DATA_ROOT = Path({directory!r})\n')
            process = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', prefix + script],
                                     capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertTrue(result['pet_visible'])
        self.assertTrue(result['panel_visible'], 'main启动后必须自动显示控制面板')
        self.assertTrue(result['persona_shared'], '界面人设与语音后台必须共用同一份设置')
        self.assertTrue(result['expressions_shared'], '实际main入口必须把资源页神态连接到语音后台')
        self.assertTrue(result['audio_shared'], '音频资源、LLM及试听后台必须共享同一份运行数据')
        self.assertTrue(result['backend_log_visible'], '语音后台的运行日志必须显示在控制面板中')
        self.assertTrue(result['startup_log_visible'], '控制面板初始化前的启动日志也必须保留')
        self.assertEqual(result['backend_log_count'], 1)
        self.assertTrue(result['hide_button_works'], '隐藏按钮必须实际隐藏立绘，并变为显示角色')
        self.assertTrue(result['hidden_status_correct'])
        self.assertTrue(result['hidden_status_survives_navigation'])
        self.assertTrue(result['show_button_works'])
        self.assertTrue(result['top_toggle_works'], '切换置顶不能使已显示的立绘消失')
        self.assertTrue(result['pet_remains_tool_window'], '切换置顶后立绘仍不能占用任务栏')
        self.assertTrue(result['full_body_image'], '立绘应保留全身，半身效果由屏幕边界形成')
        if close_pet_first:
            self.assertTrue(result['panel_keeps_running'])
            self.assertTrue(result['backend_keeps_running'])
        self.assertTrue(result['pet_closed_with_panel'], '关闭控制面板必须同时关闭桌宠')
        self.assertTrue(result['stop_requested_by_panel'])
        self.assertFalse(result.get('forced_exit', False), '关闭控制面板必须自动退出，不依赖超时退出')
        self.assertEqual(result['exit_code'], 0)
        self.assertTrue(result['backend_started'])
        self.assertTrue(result['restored_before_backend'])
        self.assertTrue(result['backend_cleaned'])
        self.assertTrue(result['worker_stopped'])


class CheckedWindow(PetWindow):
    @Slot(str)
    def add_transcript(self, text):
        self.receiver_thread = QThread.currentThread()
        super().add_transcript(text)


class DesktopBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_worker_signals_update_widgets_on_qt_thread_and_cancel_cleanly(self):
        window = CheckedWindow(catalog=ExpressionCatalog())
        window.ANIMATION_MS = 1
        signals = DesktopSignals()
        ui = DesktopUI(signals, 2)
        queued = Qt.ConnectionType.QueuedConnection
        signals.transcript.connect(window.add_transcript, queued)
        signals.caption.connect(window.set_reply_text, queued)
        signals.expression.connect(window.play_expression, queued)
        signals.reply_finished.connect(window.finish_expression, queued)
        entered, cleaned = Event(), Event()

        async def application(settings, output):
            try:
                output.transcript("你好")
                output.begin_reply(1)
                output.caption(1, 0, "回来啦。")
                output.caption(1, 1, "今天怎么样？")
                output.part_started(1, 0, "紧张")
                entered.set()
                await asyncio.Event().wait()
            finally:
                output.end_reply(1)
                cleaned.set()

        worker = VoiceWorker(Settings(), ui, signals, application)
        window.closing.connect(worker.request_stop)
        window.show()
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            deadline = monotonic() + 3
            while len(window.bubbles) < 2 or window.character._switching:
                self.assertLess(monotonic(), deadline)
                QTest.qWait(10)
            self.assertEqual(window.receiver_thread, self.app.thread())
            self.assertEqual([(card.color, card.text) for card in window.bubbles],
                             [("blue", "你好"), ("pink", "回来啦。今天怎么样？")])
            self.assertEqual(window.character.current_expression, "紧张")
            window.close()
            worker.thread.join(2)
            self.assertFalse(worker.thread.is_alive())
            self.assertTrue(cleaned.is_set())
        finally:
            worker.request_stop()
            worker.thread.join(2)
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_stop_requested_before_start_does_not_open_the_voice_chain(self):
        calls = []

        async def application(settings, output):
            calls.append(True)

        signals = DesktopSignals()
        worker = VoiceWorker(Settings(), DesktopUI(signals, 2), signals, application)
        worker.request_stop()
        worker.start()
        worker.thread.join(2)
        self.assertFalse(worker.thread.is_alive())
        self.assertEqual(calls, [])

    def test_unexpected_cancellation_rebuilds_the_backend_instead_of_exiting(self):
        calls = []
        recovered = Event()

        async def application(settings, output):
            calls.append(asyncio.get_running_loop())
            if len(calls) == 1:
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
            recovered.set()
            await asyncio.Event().wait()

        signals = DesktopSignals()
        worker = VoiceWorker(replace(Settings(), retry_delay=.01), DesktopUI(signals, 2), signals, application)
        worker.start()
        try:
            self.assertTrue(recovered.wait(2))
            self.assertTrue(worker.thread.is_alive())
            self.assertEqual(len(calls), 2)
            self.assertIsNot(calls[0], calls[1])
        finally:
            worker.request_stop()
            worker.thread.join(2)
        self.assertFalse(worker.thread.is_alive())
