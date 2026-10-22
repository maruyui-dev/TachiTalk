"""排列可编辑的粉蓝预览气泡，按真实可见轮廓设置间距。"""
from html import escape
from PySide6.QtCore import QEvent, QObject, QRectF
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QLabel, QWidget
from app.ui.bubble_display import bubble_skin_style


class BubblePreview(QObject):
    def __init__(self, panel):
        self.group = panel.findChild(QWidget, 'bubblePreviewGroup')
        super().__init__(self.group)
        self.pink = panel.findChild(QLabel, 'pinkPreview')
        self.blue = panel.findChild(QLabel, 'bluePreview')
        self._options = None
        self._bounds = {}
        self._measuring = False
        self._latest = self.blue
        self._skins = {}
        self.group.installEventFilter(self)

    def set_skins(self, skins, force=False):
        if self._skins == skins and not force:
            return
        self._skins = dict(skins)
        options, self._options = self._options, None
        self.set_options(*options)

    def set_options(self, maximum, gap, ratio):
        if self._options == (maximum, gap, ratio):
            return
        scale_changed = self._options is None or self._options[2] != ratio
        self._options = maximum, gap, ratio
        if scale_changed:
            # grab会分发Resize事件；两条轮廓都量好后再排列，避免使用半更新的数据。
            self._measuring = True
            try:
                borders = ' '.join(f'{max(1, round(value * ratio))}px' for value in (23, 31, 25, 31))
                for label, width in ((self.pink, 225), (self.blue, 205)):
                    label.setWordWrap(True)
                    label.setFixedWidth(round(width * ratio))
                    color = 'pink' if label is self.pink else 'blue'
                    skin = ''
                    if color in self._skins:
                        skin = bubble_skin_style(self._skins[color])
                    label.setStyleSheet(skin + f'border-width: {borders}; padding: 0 {round(3 * ratio)}px; '
                                       f'font-size: {max(1, round(13 * ratio))}px;')
                    label.setMinimumHeight(0)
                    label.setMaximumHeight(16777215)
                    label.setFixedHeight(max(round(75 * ratio), label.heightForWidth(label.width())))
                    pixmap = label.grab()
                    bounds = QRegion(pixmap.mask()).boundingRect()
                    dpr = pixmap.devicePixelRatio()
                    self._bounds[label] = QRectF(bounds.x() / dpr, bounds.y() / dpr,
                                                 bounds.width() / dpr, bounds.height() / dpr).toAlignedRect()
            finally:
                self._measuring = False
        self.arrange()

    def set_message(self, color, text):
        if color not in ('pink', 'blue'):
            raise ValueError('预览气泡颜色必须为pink或blue')
        label = self.pink if color == 'pink' else self.blue
        background, foreground = ('#efd0dd', '#654052') if color == 'pink' else ('#d2e7f5', '#345876')
        safe = escape(text).replace('\n', '<br>')
        label.setText(f'<span style="background-color:{background}; color:{foreground};">{safe}</span>')
        self._latest = label
        options = self._options
        self._options = None  # 正文改变后，重新测量文字与皮肤的可见范围。
        self.set_options(*options)

    def arrange(self):
        if self._options is None or self._measuring:
            return
        maximum, gap, ratio = self._options
        spacing = round(gap * ratio)
        ordered = [self.pink, self.blue] if self._latest is self.blue else [self.blue, self.pink]
        shown = ordered if maximum > 1 else [self._latest]
        top = 0
        for label in ordered:
            label.setVisible(label in shown)
            if label not in shown:
                continue
            bounds = self._bounds[label]
            x = ((self.group.width() - label.width()) // 2 if label is self.pink
                 else max(0, self.group.width() - label.width()))
            label.move(x, top - bounds.top())
            top += bounds.height() + spacing
        self.group.setFixedHeight(top - spacing)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.arrange()
        return super().eventFilter(watched, event)
