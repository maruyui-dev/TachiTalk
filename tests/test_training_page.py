"""训练页仅供预览：先展示开发提示，关闭后切页，所有训练操作均不可执行。"""
import unittest

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QProgressBar, QPushButton, QStackedWidget

from app.ui.control_panel import load_window


class TrainingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.panel = load_window()
        self.stack = self.panel.findChild(QStackedWidget, 'pageStack')
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def enter_training(self, close_with_x=False):
        button = self.panel.findChild(QPushButton, 'navTraining')
        self.assertIsNotNone(button, '侧边栏应提供模型训练入口')
        previous = self.stack.currentWidget()
        nav_names = ('navCharacter', 'navChat', 'navAudio', 'navAI', 'navAssets', 'navTraining')
        before = [name for name in nav_names if self.panel.findChild(QPushButton, name).isChecked()]
        observed = {}

        def close_notice():
            dialog = self.app.activeModalWidget()
            observed['dialog'] = isinstance(dialog, QMessageBox)
            observed['page_before_close'] = self.stack.currentWidget()
            observed['selected_before_close'] = [
                name for name in nav_names if self.panel.findChild(QPushButton, name).isChecked()]
            if isinstance(dialog, QMessageBox):
                observed['message'] = dialog.text()
                if close_with_x:
                    dialog.close()
                else:
                    dialog.accept()

        QTimer.singleShot(0, close_notice)
        button.click()
        self.assertTrue(observed.get('dialog'), '点击入口应先弹出真实提示窗口')
        self.assertIs(observed['page_before_close'], previous, '提示关闭前应保留原页面')
        self.assertEqual(observed['selected_before_close'], before, '提示关闭前应保留原页面高亮')
        self.assertIn('正在开发中', observed['message'])
        self.assertIn('暂不支持训练', observed['message'])
        self.assertEqual(self.stack.currentWidget().objectName(), 'trainingPage')
        selected = [item.objectName() for item in self.panel.findChildren(QPushButton)
                    if item.objectName() in ('navCharacter', 'navChat', 'navAudio', 'navAI',
                                              'navAssets', 'navTraining') and item.isChecked()]
        self.assertEqual(selected, ['navTraining'], '只能高亮当前页面入口')
        self.assertIsNone(self.app.activeModalWidget())

    def test_notice_precedes_navigation_and_reappears_on_each_click(self):
        self.enter_training()
        self.assertEqual(self.panel.findChild(QLabel, 'pageTitle').text(), '模型训练')
        self.assertTrue(self.panel.findChild(QPushButton, 'navTraining').isChecked())
        self.enter_training(close_with_x=True)
        self.panel.findChild(QPushButton, 'navAI').click()
        self.assertEqual(self.stack.currentWidget().objectName(), 'aiPage')
        self.enter_training(close_with_x=True)

    def test_training_actions_stay_disabled_and_existing_footer_restores(self):
        self.enter_training()
        for name in ('trainingBrowseButton', 'trainingImportButton', 'trainingPrepareButton',
                     'trainingReviewButton', 'trainingPreviewButton', 'trainingApplyButton',
                     'trainingDetectButton', 'trainingStopButton', 'trainingStartButton'):
            with self.subTest(button=name):
                button = self.panel.findChild(QPushButton, name)
                self.assertIsNotNone(button)
                self.assertFalse(button.isEnabled(), '尚未实现的操作不能执行')
        self.assertEqual(self.panel.findChild(QProgressBar, 'trainingProgress').value(), 0)
        self.assertIn('开发中', self.panel.findChild(QLabel, 'trainingNotice').text())
        # 全局配置新需求：开发中的训练页也提供页内重置与全局保存/加载。
        for name in ('resetButton', 'saveButton', 'loadSettingsButton'):
            self.assertFalse(self.panel.findChild(QPushButton, name).isHidden())
            self.assertTrue(self.panel.findChild(QPushButton, name).isEnabled())
        self.assertTrue(self.panel.findChild(QPushButton, 'trainingStartButton').isVisible())
        self.panel.findChild(QPushButton, 'navAssets').click()
        self.assertEqual(self.stack.currentIndex(), 4, '保留已有页面编号')
        self.assertFalse(self.panel.findChild(QPushButton, 'saveButton').isHidden())
        self.assertFalse(self.panel.findChild(QPushButton, 'resetButton').isHidden())
        self.assertFalse(self.panel.findChild(QPushButton, 'trainingStartButton').isVisible())

    def test_training_navigation_keeps_existing_log_sidebar_open(self):
        log_button = self.panel.findChild(QPushButton, 'navRuntimeLog')
        log_button.click()
        self.assertTrue(self.panel.runtime_console.dock.isVisible())
        self.enter_training()
        self.assertTrue(self.panel.runtime_console.dock.isVisible())
        self.assertTrue(log_button.isChecked())
