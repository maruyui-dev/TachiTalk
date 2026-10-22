"""模拟窗口版EXE没有标准错误流，但随后启用界面日志的启动顺序。"""
from io import StringIO
import logging
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import bootstrap


class StopStartup(Exception):
    pass


class BootstrapLoggingTests(unittest.TestCase):
    def setUp(self):
        self.root = logging.getLogger()
        self.handlers, self.level = tuple(self.root.handlers), self.root.level
        for handler in self.handlers:
            self.root.removeHandler(handler)

    def tearDown(self):
        for handler in tuple(self.root.handlers):
            self.root.removeHandler(handler)
            handler.close()
        for handler in self.handlers:
            self.root.addHandler(handler)
        self.root.setLevel(self.level)

    def start_logging(self, directory, stderr):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'stderr', stderr), \
                patch('app.paths.DATA_ROOT', Path(directory)), \
                patch.object(bootstrap.argparse.ArgumentParser, 'parse_args', side_effect=StopStartup):
            with self.assertRaises(StopStartup):
                bootstrap.main()

    def test_windowed_startup_keeps_file_and_ui_logs_without_invalid_console_handler(self):
        directory_context = TemporaryDirectory()
        self.addCleanup(directory_context.cleanup)
        directory = directory_context.name
        self.start_logging(directory, None)
        ui_output, error_output = StringIO(), StringIO()
        ui_handler = logging.StreamHandler(ui_output)
        self.root.addHandler(ui_handler)
        # Qt日志面板在启动后替换sys.stderr，此时旧的空stream最容易暴露问题。
        with patch.object(sys, 'stderr', error_output):
            self.root.warning('windowed-log-example')
        self.assertIn('windowed-log-example', ui_output.getvalue())
        self.assertIn('windowed-log-example', (Path(directory) / 'logs/TachiTalk.log').read_text(encoding='utf-8'))
        self.assertEqual(error_output.getvalue(), '')

    def test_existing_console_still_receives_logs(self):
        directory_context = TemporaryDirectory()
        self.addCleanup(directory_context.cleanup)
        directory = directory_context.name
        console = StringIO()
        self.start_logging(directory, console)
        self.root.info('console-log-example')
        self.assertIn('console-log-example', console.getvalue())
