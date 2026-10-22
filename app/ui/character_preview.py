"""角色页的窄幅桌面预览；随高度适配，宽窗口把空间留给设置栏。"""
from PySide6.QtCore import QEvent, QObject, QRectF, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget


class PreviewCanvas(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor('#e9edf9'))
        gradient.setColorAt(1, QColor('#fbf0eb'))
        painter.fillRect(self.rect(), gradient)
        floor = round(self.height() * .81)
        painter.fillRect(0, floor, self.width(), self.height() - floor, QColor('#f2e7df'))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor('#e7eaf2'))
        painter.setBrush(QColor(255, 255, 255, 110))
        painter.drawRoundedRect(QRectF(18, 22, self.width() * .34, 58), 6, 6)
        painter.drawRoundedRect(QRectF(18, 90, self.width() * .24, 36), 5, 5)


class PortraitPreview(QObject):
    def __init__(self, panel):
        self.card = panel.findChild(QWidget, 'previewCard')
        super().__init__(self.card)
        self.page = panel.findChild(QWidget, 'characterPage')
        self.layout = panel.findChild(QObject, 'columnsLayout')
        self._fitting = False
        self.page.installEventFilter(self)
        self.card.installEventFilter(self)
        QTimer.singleShot(0, self.fit)

    def fit(self):
        if self._fitting:
            return
        self._fitting = True
        try:
            # 画布约3:5，标题与任务栏另计；气泡仍由原布局排列。
            heading = self.card.findChild(QWidget, 'previewHeading').height()
            taskbar = self.card.findChild(QWidget, 'previewTaskbar').height()
            canvas_height = max(1, self.card.height() - heading - taskbar)
            available = self.page.width() - self.layout.contentsMargins().left() - self.layout.contentsMargins().right()
            width = min(max(320, round(canvas_height * .60)), max(320, round(available * .46)))
            self.card.setFixedWidth(width)
        finally:
            self._fitting = False

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.fit()
        return super().eventFilter(watched, event)
