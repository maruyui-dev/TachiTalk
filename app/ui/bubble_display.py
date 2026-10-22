"""按人物的比例绘制气泡；字号、皮肤边角和留白一起缩放。"""
from html import escape
from pathlib import Path

from PySide6.QtGui import QFont, QFontMetrics, QImageReader
from app.ui.pet.bubble import BubbleCard


def bubble_skin_style(path):
    """九宫格切片按原皮肤1086×724的比例换算，兼容不同尺寸的PNG。"""
    path = Path(path).resolve()
    size = QImageReader(str(path)).size()
    slices = (max(1, round(170 * size.height() / 724)), max(1, round(230 * size.width() / 1086)),
              max(1, round(180 * size.height() / 724)), max(1, round(230 * size.width() / 1086)))
    # QSS的图片地址使用本地路径；转义引号避免文件名成为样式语句。
    url = path.as_posix().replace('"', '\\"')
    return (f'border-image: url("{url}") {" ".join(map(str, slices))} stretch stretch;'
            f' /* resource-version:{path.stat().st_mtime_ns} */')


class ScaledBubbleCard(BubbleCard):
    def __init__(self, color, text, parent, max_text_width, scale_ratio):
        self.scale_ratio = scale_ratio
        self._base_font = None
        self._skin = None
        super().__init__(color, text, parent, max_text_width)

    def set_skin(self, path):
        self._skin = bubble_skin_style(path)
        self._apply_scale()
        self.set_message(self.text)

    def _scaled(self, value):
        return max(1, round(value * self.scale_ratio))

    def _apply_scale(self):
        label = self.ui.messageLabel
        if self._base_font is None:
            self._base_font = QFont(label.font())
            self._skin = self.background_label.styleSheet()
        font = QFont(self._base_font)
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * self.scale_ratio)
        else:
            font.setPixelSize(self._scaled(font.pixelSize()))
        label.setFont(font)
        borders = ' '.join(f'{self._scaled(value)}px' for value in (39, 53, 41, 53))
        self.background_label.setStyleSheet(self._skin + f'\nborder-width: {borders};')

    def set_display_scale(self, ratio, max_text_width):
        if self.scale_ratio == ratio and self.max_text_width == max_text_width:
            return
        self.scale_ratio = ratio
        self._apply_scale()
        self.set_max_text_width(max_text_width)

    def set_message(self, text):
        # 父类构造器也会调用这里；先缓存原始字体，反复缩放不累积误差。
        if self._base_font is None:
            self._apply_scale()
        self.text = text
        _, background, foreground = self.STYLES[self.color]
        safe = escape(text).replace('\n', '<br>')
        label = self.ui.messageLabel
        label.setText(f'<span style="background-color:{background}; color:{foreground};">{safe}</span>')
        metrics = QFontMetrics(label.font())
        natural = max(metrics.horizontalAdvance(line) for line in text.split('\n')) + self._scaled(4)
        label.setFixedWidth(max(1, min(natural, self.max_text_width)))
        # setFixedHeight会留下旧的最小高度；重新量字前先解除，缩小时才能变矮。
        label.setMinimumHeight(0)
        label.setMaximumHeight(16777215)
        label.setFixedHeight(max(metrics.height(), label.heightForWidth(label.width())))
        left, top, bottom = (self._scaled(value) for value in (self.TEXT_LEFT, self.TEXT_TOP, self.TEXT_BOTTOM))
        label.move(left, top)
        self.resize(max(label.width() + 2 * left, self._scaled(160)),
                    max(label.height() + top + bottom, self._scaled(110)))
        self.background_label.setGeometry(self.rect())
        self._measure_visible_rect()
