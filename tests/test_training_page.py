"""Native workbench replaces the former intentionally disabled preview contract."""
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QProgressBar, QStackedWidget
from app.ui.control_panel import load_window


class TrainingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.panel = load_window()
        self.page = self.panel.training_page
        self.page.data_root = Path(self.temp.name)
        self.page.project = None
        self.page.restore_projects()
        self.panel.show()
        self.app.processEvents()
        self.addCleanup(self.panel.close)

    def test_navigation_is_direct_and_footer_and_other_pages_remain_available(self):
        self.panel.findChild(QPushButton, 'navTraining').click()
        self.assertEqual(self.panel.findChild(QStackedWidget, 'pageStack').currentWidget().objectName(), 'trainingPage')
        self.assertEqual(self.panel.findChild(QLabel, 'pageTitle').text(), '模型训练')
        self.assertIsNone(self.app.activeModalWidget())
        self.assertTrue(self.page.actions.isVisible())
        self.panel.findChild(QPushButton, 'navAssets').click()
        self.assertEqual(self.panel.findChild(QStackedWidget, 'pageStack').currentIndex(), 4)
        self.assertFalse(self.page.actions.isVisible())
        self.assertTrue(self.panel.findChild(QPushButton, 'saveButton').isVisible())

    def test_missing_inference_locks_form_and_missing_training_does_not_lock_inference(self):
        with patch('app.ui.training_page.voice_status', return_value={'installed': False}), \
             patch('app.ui.training_page.training_status', return_value={'installed': False}):
            self.page.refresh()
            self.assertFalse(self.page.infer_form.isEnabled())
            self.assertFalse(self.page.gate.isHidden())
            self.assertFalse(self.page.w('trainingStartButton', QPushButton).isEnabled())
        with patch('app.ui.training_page.voice_status', return_value={'installed': True}), \
             patch('app.ui.training_page.training_status', return_value={'installed': False}):
            self.page.refresh()
            self.assertTrue(self.page.infer_form.isEnabled())
            self.assertTrue(self.page.gate.isHidden())
            self.assertFalse(self.page.w('trainingStartButton', QPushButton).isEnabled())

    def test_backend_entry_rechecks_resources_instead_of_trusting_button_state(self):
        with patch('app.ui.training_page.voice_status', return_value={'installed': False}), \
             patch.object(self.page, 'error') as error, patch.object(self.page.job, 'start') as start:
            self.page.run('infer')
            start.assert_not_called()
            self.assertIn('推理资源包', str(error.call_args.args[0]))

    def test_task_running_blocks_exit_and_requests_cooperative_stop(self):
        with patch.object(type(self.page.job), 'running', property(lambda _self: True)), \
             patch.object(self.page.job, 'request_stop') as stop:
            self.assertFalse(self.panel.close())
            self.assertFalse(self.panel._closing)
            self.page.stop()
            stop.assert_called_once()

    def test_start_waits_for_current_reply_without_stopping_its_service(self):
        busy = SimpleNamespace(snapshot=lambda: SimpleNamespace(busy=True))
        with patch.object(self.panel.voice_controls, 'inputs', busy), \
             patch.object(self.page, 'error') as error, patch.object(self.page.job, 'start') as start:
            self.page.run('train')
            start.assert_not_called()
            self.assertIn('正在回复', str(error.call_args.args[0]))

    def test_training_navigation_keeps_runtime_log_open(self):
        button = self.panel.findChild(QPushButton, 'navRuntimeLog')
        button.click()
        self.panel.findChild(QPushButton, 'navTraining').click()
        self.assertTrue(self.panel.runtime_console.dock.isVisible())
        self.assertTrue(button.isChecked())

    def test_finished_task_clears_processing_text_for_success_failure_and_stop(self):
        for result, message in [({'ok': True}, '任务成功'),
                                ({'ok': False, 'error': '测试训练失败'}, '测试训练失败'),
                                ({'ok': True, 'stopped': True}, '已停止，产物和日志保留')]:
            with self.subTest(result=result):
                self.page.on_event({'phase': '正在处理'})
                self.page.on_finished(dict(result, log='fixture/worker.log'))
                self.assertEqual(self.page.w('trainingTaskState', QLabel).text(), message)
                self.assertEqual(self.page.w('trainingEmptyTitle', QLabel).text(), message)
                self.assertEqual(self.page.w('trainingProgressValue', QLabel).text(), message)
                self.assertEqual(self.page.w('trainingProgress', QProgressBar).maximum(), 100)
