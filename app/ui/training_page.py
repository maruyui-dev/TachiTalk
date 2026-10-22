"""模型训练的界面预览与开发提示，不导入或启动GPT-SoVITS训练代码。"""
from PySide6.QtCore import QFile, QIODevice, QObject
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QStackedWidget, QWidget


class TrainingPage(QObject):
    def __init__(self, panel, ui_path):
        super().__init__(panel)
        self.panel = panel
        stack = panel.findChild(QStackedWidget, 'pageStack')
        source = QFile(str(ui_path))
        if not source.open(QIODevice.OpenModeFlag.ReadOnly):
            raise FileNotFoundError(f'无法打开模型训练界面：{ui_path}')
        loader = QUiLoader()
        try:
            self.page = loader.load(source, stack)
        finally:
            source.close()
        if self.page is None:
            raise RuntimeError(f'模型训练界面加载失败：{loader.errorString()}')
        stack.addWidget(self.page)
        # 保留Designer中的完整预览布局；运行时将操作栏放入主窗口的固定页脚。
        self.actions = self.page.findChild(QWidget, 'trainingActions')
        self.page.layout().removeWidget(self.actions)
        panel.findChild(QHBoxLayout, 'footerButtonsLayout').insertWidget(0, self.actions)
        self.actions.hide()

    def show_notice(self):
        # 模态对话框关闭后，调用方才继续切页；右上角关闭或Esc也能进入预览。
        dialog = QMessageBox(
            QMessageBox.Icon.Information, '模型训练 · 开发中',
            '此功能正在开发中。\n\n'
            '当前仅供界面预览，暂不支持训练。\n'
            '音频处理、试听和模型应用尚未开放。\n\n'
            '关闭提示后可查看模型训练界面。',
            QMessageBox.StandardButton.Ok, self.panel,
        )
        dialog.setObjectName('trainingNoticeDialog')
        dialog.button(QMessageBox.StandardButton.Ok).setText('知道了，查看界面')
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
