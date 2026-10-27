"""Native workbench expectations, with no model downloads or daily profile writes."""
from pathlib import Path
import unittest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTabWidget
from app.ui.control_panel import load_window


class TrainingWorkbenchUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_training_is_a_native_workbench_with_inference_and_resource_gate(self):
        panel = load_window()
        self.addCleanup(panel.close)
        self.assertEqual(panel.findChild(QPushButton, 'navTraining').text(), '模型训练')
        tabs = panel.findChild(QTabWidget, 'trainingTabs')
        self.assertIsNotNone(tabs, 'Training is still a disabled preview rather than a native workbench')
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['模型训练', '语音推理'])
        self.assertIsNotNone(panel.findChild(QPushButton, 'trainingDownloadButton'))
        self.assertNotIn('仅供界面预览', panel.findChild(QLabel, 'trainingNotice').text())
