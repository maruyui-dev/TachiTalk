"""单条消息的外观：粉蓝皮肤、逐行文字底色、自适应大小。"""
from html import escape
from app.paths import BUBBLE_DIR

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFontMetrics, QRegion
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget
from .ui_bubble import Ui_Form


class BubbleCard(QWidget):
    # 文件名、文字底色、文字颜色；与输入逻辑、消息排列相互独立。
    STYLES = {
        "pink": ("bubble_pink.png", "#efd0dd", "#473c44"),
        "blue": ("bubble_blue.png", "#cfe3f2", "#314957"),
    }
    TEXT_LEFT = 26
    TEXT_TOP = 44
    TEXT_BOTTOM = 44

    def __init__(self, color, text, parent=None, max_text_width=280):
        super().__init__(parent)
        if color not in self.STYLES:
            raise ValueError(f"不支持的气泡颜色：{color}")
        self.setObjectName("bubbleCard")
        self.color = color
        self.text = text
        self.ui = Ui_Form()
        self.ui.setupUi(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.ui.messageLabel.setWordWrap(True)
        self.ui.messageLabel.setTextFormat(Qt.TextFormat.RichText)
        self.ui.messageLabel.setMaximumWidth(max_text_width)
        self.max_text_width = max_text_width

        image_path = BUBBLE_DIR / self.STYLES[color][0]
        if not image_path.is_file():
            raise FileNotFoundError(f"找不到气泡素材：{image_path}")
        self.background_label = QLabel(self)
        # 九宫格：源图切片顺序为上、右、下、左；目标边角按约23%显示。
        self.background_label.setStyleSheet(f"""
            border-image: url("{image_path.as_posix()}") 170 230 180 230 stretch stretch;
            border-width: 39px 53px 41px 53px;
        """)
        self.background_label.lower()
        for label in (self.background_label, self.ui.messageLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.fade_effect = QGraphicsOpacityEffect(self)
        self.fade_effect.setOpacity(1.0)
        self.setGraphicsEffect(self.fade_effect)
        self.set_message(text)

    def set_message(self, text):
        self.text = text
        _, background, foreground = self.STYLES[self.color]
        # 文字中的HTML字符按原样显示，只有我们写的span参与富文本排版。
        safe_text = escape(text).replace("\n", "<br>")
        label = self.ui.messageLabel
        label.setText(
            f'<span style="background-color:{background}; color:{foreground};">'
            f'{safe_text}</span>'
        )
        # 先量出不换行时的文字宽度，再限制上限；高度交给QLabel计算。
        metrics = QFontMetrics(label.font())
        natural_width = max(metrics.horizontalAdvance(line) for line in text.split("\n")) + 4
        width = max(1, min(natural_width, self.max_text_width))
        label.setFixedWidth(width)
        label.setFixedHeight(max(metrics.height(), label.heightForWidth(width)))
        label.move(self.TEXT_LEFT, self.TEXT_TOP)
        self.resize(
            max(label.width() + 2 * self.TEXT_LEFT, 160),
            max(label.height() + self.TEXT_TOP + self.TEXT_BOTTOM, 110),
        )
        self.background_label.setGeometry(self.rect())
        self._measure_visible_rect()

    def _measure_visible_rect(self):
        # 排列时使用实际轮廓，而不是含透明外缘的控件矩形。
        was_enabled = self.fade_effect.isEnabled()
        self.fade_effect.setEnabled(False)  # 测量不受当前淡入透明度影响
        try:
            pixmap = self.grab()
        finally:
            self.fade_effect.setEnabled(was_enabled)
        bounds = QRegion(pixmap.mask()).boundingRect()
        ratio = pixmap.devicePixelRatio()  # 截图是物理像素，定位需要Qt逻辑像素
        self.visible_rect = QRectF(
            bounds.x() / ratio, bounds.y() / ratio,
            bounds.width() / ratio, bounds.height() / ratio,
        ).toAlignedRect()

    def set_max_text_width(self, width):
        self.max_text_width = width
        self.ui.messageLabel.setMaximumWidth(width)
        self.set_message(self.text)
