"""只读运行控制台：接收print、logging、Qt消息和未捕获异常。"""
import io
import logging
import sys
import threading
import traceback
from collections import deque

from PySide6.QtCore import QEvent, QObject, Qt, QtMsgType, QTimer, Signal, Slot, qInstallMessageHandler
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QCheckBox, QDockWidget, QPlainTextEdit, QPushButton

from config import redact


class StartupLogBuffer(logging.Handler):
    """界面创建前暂存最近200条日志，交给日志侧栏后立即卸载。"""
    def __init__(self):
        super().__init__()
        self.records = deque(maxlen=200)

    def emit(self, record):
        self.records.append(record)

    def drain(self):
        logging.getLogger().removeHandler(self)
        with self.lock:
            records = tuple(self.records)
            self.records.clear()
        self.close()
        return records


class ConsoleStream(io.TextIOBase):
    """把Python文本输出转交给Qt信号，同时保留原控制台输出。"""
    def __init__(self, console, original, level):
        super().__init__()
        self.console = console
        self.original = original
        self.level = level

    @property
    def encoding(self):
        return getattr(self.original, 'encoding', None) or 'utf-8'

    def writable(self):
        return True

    def isatty(self):
        return False

    def write(self, text):
        if not isinstance(text, str):
            raise TypeError('控制台只能写入字符串')
        length = len(text)
        text = redact(text)
        if text and self.console.active:
            self.console.output.emit(text, self.level)
        if self.original is not None and not getattr(self.original, 'closed', False):
            self.original.write(text)
        return length

    def flush(self):
        if self.original is not None and not getattr(self.original, 'closed', False):
            self.original.flush()


class ConsoleLogHandler(logging.Handler):
    """logging可以来自后台线程；这里不直接操作Qt控件。"""
    def __init__(self, console):
        super().__init__(logging.DEBUG)
        self.console = console
        self.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)-7s %(message)s', '%H:%M:%S'))

    def emit(self, record):
        if self.console.active:
            # Formatter会把logging.exception携带的异常堆栈一并格式化。
            self.console.output.emit(self.format(record) + '\n', record.levelno)


class RuntimeConsole(QObject):
    output = Signal(str, int)
    MAX_PENDING = 512
    MAX_CHUNK_CHARS = 4096
    MAX_DOCUMENT_CHARS = 256000
    BATCH_SIZE = 64
    COLORS = {
        logging.DEBUG: '#8f9bb1', logging.INFO: '#d5dfef',
        logging.WARNING: '#f1c47b', logging.ERROR: '#f09cae',
        logging.CRITICAL: '#ff7893',
    }

    def __init__(self, window, startup_records=()):
        super().__init__(window)
        self.window = window
        self.dock = window.findChild(QDockWidget, 'runtimeLogDock')
        self.view = window.findChild(QPlainTextEdit, 'runtimeLogView')
        self.button = window.findChild(QPushButton, 'navRuntimeLog')
        self.auto_scroll = window.findChild(QCheckBox, 'runtimeLogAutoScroll')
        self.active = False
        self._collapsed_position = None
        self._pending = deque(maxlen=self.MAX_PENDING)
        self._pending_lock = threading.Lock()
        self._dropped = 0
        # DirectConnection只写Python有界队列，不访问Qt控件、不积压Qt事件。
        self.output.connect(self._enqueue, Qt.ConnectionType.DirectConnection)
        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(25)
        self.flush_timer.timeout.connect(self.flush_pending)
        self.button.toggled.connect(self._set_visible)
        self.dock.visibilityChanged.connect(self._sync_visibility)
        window.findChild(QPushButton, 'runtimeLogClearButton').clicked.connect(self.clear)
        window.findChild(QPushButton, 'runtimeLogCopyButton').clicked.connect(self.copy_all)
        window.installEventFilter(self)

        # 保存原对象，窗口关闭时完整恢复，避免全局输出继续引用已销毁控件。
        self._stdout, self._stderr = sys.stdout, sys.stderr
        self._exception_hook = sys.excepthook
        self._thread_exception_hook = threading.excepthook
        self.root_logger = logging.getLogger()
        self._root_level = self.root_logger.level
        self.handler = ConsoleLogHandler(self)
        self.stdout = ConsoleStream(self, self._stdout, logging.INFO)
        self.stderr = ConsoleStream(self, self._stderr, logging.ERROR)
        self.active = True
        sys.stdout, sys.stderr = self.stdout, self.stderr
        sys.excepthook = self._handle_exception
        threading.excepthook = self._handle_thread_exception
        self.root_logger.addHandler(self.handler)
        self.root_logger.setLevel(logging.DEBUG)
        self._qt_message_handler = qInstallMessageHandler(self._handle_qt_message)
        QApplication.instance().aboutToQuit.connect(self.restore)
        self.flush_timer.start()
        for record in startup_records:
            self.handler.handle(record)
        logging.getLogger('tachitalk.ui').info('运行日志已开启，可查看程序输出、日志与异常堆栈。')

    @property
    def pending_count(self):
        with self._pending_lock:
            return len(self._pending)

    @Slot(str, int)
    def _enqueue(self, text, level):
        text = redact(text)
        if len(text) > self.MAX_CHUNK_CHARS:
            text = text[:self.MAX_CHUNK_CHARS] + '\n[单条日志过长，已截断]\n'
        with self._pending_lock:
            if not self.active:
                return
            if len(self._pending) == self.MAX_PENDING:
                self._dropped += 1
            self._pending.append((text, level))

    @Slot()
    def flush_pending(self):
        with self._pending_lock:
            batch = [self._pending.popleft() for _ in range(min(self.BATCH_SIZE, len(self._pending)))]
            dropped, self._dropped = self._dropped, 0
        if dropped:
            self._append(f'[日志缓冲已满，丢弃{dropped}条较早输出]\n', logging.WARNING)
        for text, level in batch:
            self._append(text, level)

    def clear(self):
        with self._pending_lock:
            self._pending.clear()
            self._dropped = 0
        self.view.clear()

    @Slot(str, int)
    def _append(self, text, level):
        if not self.active:
            return
        scroll = self.view.verticalScrollBar()
        previous = scroll.value()
        cursor = QTextCursor(self.view.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        style = QTextCharFormat()
        style.setForeground(QColor(self.COLORS.get(level, self.COLORS[logging.INFO])))
        # insertText保留print的换行和end参数，也不会把日志当HTML解释。
        cursor.insertText(text, style)
        # 段落数限制无法约束一直没有换行的输出，额外限制字符总数。
        excess = self.view.document().characterCount() - 1 - self.MAX_DOCUMENT_CHARS
        if excess > 0:
            trim = QTextCursor(self.view.document())
            trim.setPosition(0)
            trim.setPosition(excess, QTextCursor.MoveMode.KeepAnchor)
            trim.removeSelectedText()
        if self.auto_scroll.isChecked():
            self.view.setTextCursor(cursor)
            self.view.ensureCursorVisible()
        else:
            scroll.setValue(previous)

    def _handle_exception(self, kind, error, tb):
        self.stderr.write(''.join(traceback.format_exception(kind, error, tb)))
        self.stderr.flush()

    def _handle_thread_exception(self, args):
        name = args.thread.name if args.thread is not None else 'unknown'
        self.stderr.write(f'Exception in thread {name}:\n')
        self._handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    def _handle_qt_message(self, kind, context, message):
        level = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }.get(kind, logging.INFO)
        text = f'[Qt {logging.getLevelName(level)}] {message}\n'
        if self.active:
            self.output.emit(text, level)
        if self._qt_message_handler is not None:
            self._qt_message_handler(kind, context, message)
        elif self._stderr is not None and not getattr(self._stderr, 'closed', False):
            self._stderr.write(text)

    def _set_visible(self, visible):
        if visible and not self.dock.isVisible():
            self._collapsed_position = (self.window.width(), self.window.x())
            area = self.window.screen().availableGeometry()
            width = min(self.window.width() + 370, max(self.window.width(), area.width() - 24))
            self.window.resize(width, self.window.height())
            self.window.move(max(area.left(), min(self.window.x(), area.right()-width+1)), self.window.y())
        self.dock.setVisible(visible)

    def _sync_visibility(self, visible):
        self.button.blockSignals(True)
        self.button.setChecked(visible)
        self.button.blockSignals(False)
        if not visible and self._collapsed_position is not None:
            width, x = self._collapsed_position
            self._collapsed_position = None
            self.window.resize(width, self.window.height())
            self.window.move(x, self.window.y())

    def copy_all(self):
        self.flush_pending()
        QApplication.clipboard().setText(self.view.toPlainText())

    def restore(self):
        if not self.active:
            return
        self.flush_timer.stop()
        with self._pending_lock:
            self.active = False
            self._pending.clear()
        self.window.removeEventFilter(self)
        if sys.stdout is self.stdout:
            sys.stdout = self._stdout
        if sys.stderr is self.stderr:
            sys.stderr = self._stderr
        if sys.excepthook == self._handle_exception:
            sys.excepthook = self._exception_hook
        if threading.excepthook == self._handle_thread_exception:
            threading.excepthook = self._thread_exception_hook
        qInstallMessageHandler(self._qt_message_handler)
        self.root_logger.removeHandler(self.handler)
        if self.root_logger.level == logging.DEBUG:
            self.root_logger.setLevel(self._root_level)
        self.handler.close()

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Type.Close:
            self.restore()
        return super().eventFilter(watched, event)
