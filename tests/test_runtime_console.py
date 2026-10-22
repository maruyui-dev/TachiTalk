"""运行日志涉及全局输出钩子与后台线程，需要验证捕获和关闭后的恢复。"""
import logging
import sys
import threading
from time import monotonic
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEventLoop, QThread, QTimer, qWarning
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QStackedWidget

from app.ui.control_panel import load_window
from app.ui.runtime_console import ConsoleStream, StartupLogBuffer


class RuntimeConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        if not QFontDatabase.families():
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')

    def setUp(self):
        self.originals = (sys.stdout, sys.stderr, sys.excepthook, threading.excepthook,
                          logging.getLogger().level, tuple(logging.getLogger().handlers))
        self.window = load_window()
        self.window.show()
        self.console = self.window.runtime_console
        self.view = self.console.view
        QTest.qWait(30)
        self.view.clear()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def flush_events(self):
        QTest.qWait(30)
        # 日志现在按25ms批量刷新；等待实际完成，避免把定时器当成精确时钟。
        deadline = monotonic() + 1
        while self.console.pending_count:
            self.assertLess(monotonic(), deadline, '日志缓冲未在主线程及时消费')
            QTest.qWait(10)

    def test_readonly_dock_opens_and_stays_open_across_pages(self):
        self.assertTrue(self.view.isReadOnly())
        self.assertFalse(self.console.dock.isVisible())
        self.assertEqual(self.console.dock.findChildren(QLineEdit), [])
        self.console.button.click()
        self.assertTrue(self.console.dock.isVisible())
        self.window.findChild(QPushButton, 'navAI').click()
        self.assertEqual(self.window.findChild(QStackedWidget, 'pageStack').currentIndex(), 3)
        self.assertTrue(self.console.dock.isVisible())
        self.assertTrue(self.console.button.isChecked())
        self.console.dock.close()
        self.assertFalse(self.console.button.isChecked())

    def test_print_partial_writes_and_stderr_are_visible(self):
        print('stdout-value', end='!')
        print('next-line')
        sys.stderr.write('stderr-value\n')
        self.flush_events()
        text = self.view.toPlainText()
        self.assertIn('stdout-value!next-line\n', text)
        self.assertIn('stderr-value', text)
        error = self.view.document().find('stderr-value')
        self.assertEqual(error.charFormat().foreground().color().name(), '#f09cae')

    def test_logging_levels_and_exception_traceback_are_captured(self):
        logging.debug('debug-output')
        logging.warning('warning-output')
        try:
            raise ValueError('logging-exception-example')
        except ValueError:
            logging.exception('logging-error-output')
        self.flush_events()
        text = self.view.toPlainText()
        self.assertIn('DEBUG', text)
        self.assertIn('debug-output', text)
        self.assertEqual(text.count('warning-output'), 1)
        self.assertIn('Traceback (most recent call last)', text)
        self.assertIn('ValueError: logging-exception-example', text)

    def test_uncaught_main_thread_exception_hook_is_captured(self):
        try:
            raise RuntimeError('main-exception-example')
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        self.flush_events()
        self.assertIn('RuntimeError: main-exception-example', self.view.toPlainText())

    def test_worker_output_and_uncaught_exception_are_captured(self):
        def worker():
            print('worker-output-example')
            raise RuntimeError('worker-exception-example')
        thread = threading.Thread(target=worker, name='console-test-worker')
        thread.start()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.flush_events()
        text = self.view.toPlainText()
        self.assertIn('worker-output-example', text)
        self.assertIn('Exception in thread console-test-worker:', text)
        self.assertIn('RuntimeError: worker-exception-example', text)

    def test_uncaught_qt_callback_exception_is_captured(self):
        def failed_callback():
            raise ValueError('qt-callback-exception-example')
        # exec按实际应用的方式分发回调；qWait会把回调异常直接抛给测试。
        loop = QEventLoop()
        QTimer.singleShot(5, failed_callback)
        QTimer.singleShot(60, loop.quit)
        loop.exec()
        self.flush_events()
        self.assertIn('ValueError: qt-callback-exception-example', self.view.toPlainText())

    def test_stream_wrapper_accepts_console_like_objects(self):
        # IDE的输出对象可能只提供write/flush，而没有TextIOBase的closed属性。
        original = Mock(spec=['write', 'flush'])
        stream = ConsoleStream(self.console, original, logging.INFO)
        self.assertEqual(stream.write('ide-console-example'), 19)
        stream.flush()
        original.write.assert_called_once_with('ide-console-example')
        original.flush.assert_called_once_with()

    def test_qt_warning_is_visible(self):
        qWarning('qt-warning-example')
        self.flush_events()
        self.assertIn('[Qt WARNING] qt-warning-example', self.view.toPlainText())

    def test_copy_and_clear_display_without_touching_real_clipboard(self):
        print('copy-output-example')
        self.flush_events()
        clipboard = Mock()
        with patch('app.ui.runtime_console.QApplication.clipboard', return_value=clipboard):
            self.window.findChild(QPushButton, 'runtimeLogCopyButton').click()
        clipboard.setText.assert_called_once_with(self.view.toPlainText())
        self.window.findChild(QPushButton, 'runtimeLogClearButton').click()
        self.assertEqual(self.view.toPlainText(), '')

    def test_buffer_is_bounded(self):
        self.view.setMaximumBlockCount(8)
        sys.stdout.write(''.join(f'buffer-line-{index:03d}\n' for index in range(30)))
        self.flush_events()
        self.assertLessEqual(self.view.document().blockCount(), 8)
        self.assertNotIn('buffer-line-000', self.view.toPlainText())
        self.assertIn('buffer-line-029', self.view.toPlainText())

    def test_closing_window_restores_streams_hooks_and_logging(self):
        self.window.close()
        self.assertFalse(self.console.active)
        actual = (sys.stdout, sys.stderr, sys.excepthook, threading.excepthook,
                  logging.getLogger().level, tuple(logging.getLogger().handlers))
        self.assertEqual(actual, self.originals)

    def test_api_keys_are_redacted_in_logs_and_print_output(self):
        secret = 'example-private-credential'
        from config import register_runtime_key
        register_runtime_key(secret)
        with patch.object(self.console.stdout, 'original', Mock()):
            print('凭据：' + secret)
            logging.error('请求失败：%s', secret)
            self.flush_events()
        text = self.view.toPlainText()
        self.assertNotIn(secret, text)
        self.assertIn('[KEY已隐藏]', text)

    def test_clear_also_discards_pending_output(self):
        self.console.output.emit('clear-pending-example\n', logging.INFO)
        self.window.findChild(QPushButton, 'runtimeLogClearButton').click()
        self.flush_events()
        self.assertEqual(self.view.toPlainText(), '')

    def test_worker_output_updates_document_only_on_the_gui_thread(self):
        threads = []
        self.view.document().contentsChanged.connect(lambda: threads.append(QThread.currentThread()))
        thread = threading.Thread(target=lambda: self.console.output.emit('thread-safe-log\n', logging.INFO))
        thread.start()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.flush_events()
        self.assertIn('thread-safe-log', self.view.toPlainText())
        self.assertTrue(threads)
        self.assertTrue(all(item == self.app.thread() for item in threads))

    def test_burst_output_is_bounded_before_gui_events_are_processed(self):
        for index in range(10000):
            self.console.output.emit(f'burst-line-{index:05d}\n', logging.INFO)
        self.assertLessEqual(getattr(self.console, 'pending_count', 10000), 512,
                             'Qt主线程尚未处理日志时，待显示日志也必须有界')
        QTest.qWait(300)
        self.assertIn('burst-line-09999', self.view.toPlainText())
        self.assertNotIn('burst-line-00000', self.view.toPlainText())

    def test_output_without_newlines_cannot_grow_the_document_forever(self):
        for _ in range(100):
            self.console.output.emit('x' * 4000, logging.INFO)
        QTest.qWait(300)
        self.assertLessEqual(self.view.document().characterCount(), 256001)

    def test_startup_logs_are_bounded_and_detached_after_replay(self):
        buffer = StartupLogBuffer()
        logging.getLogger().addHandler(buffer)
        try:
            for index in range(300):
                buffer.handle(logging.LogRecord('startup', logging.INFO, '', 0,
                                                f'startup-{index:03d}', (), None))
            records = buffer.drain()
            self.assertEqual(len(records), 200)
            self.assertEqual(records[0].getMessage(), 'startup-100')
            self.assertEqual(records[-1].getMessage(), 'startup-299')
            self.assertNotIn(buffer, logging.getLogger().handlers)
            for record in records:
                self.console.handler.handle(record)
            self.flush_events()
            self.assertIn('startup-299', self.view.toPlainText())
        finally:
            buffer.drain()


if __name__ == '__main__':
    unittest.main()
