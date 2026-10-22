"""人物控件：上半身显示、等比例放大、两层立绘交叉淡化。"""
from pathlib import Path

from PySide6.QtCore import QParallelAnimationGroup, QPropertyAnimation, QRect, Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget
from .petUI import Ui_Form
from .expressions import ExpressionCatalog


class CharacterWidget(QWidget):
    DESIGN_WIDTH = 223
    DESIGN_HEIGHT = 431
    VISIBLE_FRACTION = 0.50  # 保留原图从头顶开始的50%；原始PNG文件不变

    def __init__(self, parent=None, catalog=None):
        super().__init__(parent)
        self.catalog = catalog if catalog is not None else ExpressionCatalog()
        self._pixmaps = {name: QPixmap(str(path)) for name, path in self.catalog.paths.items()}
        self.ui = Ui_Form()
        self.ui.setupUi(self)
        self.setObjectName("characterWidget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._switching = False
        self._pending_expression = None
        self.current_expression = self.catalog.default
        self._current_pixmap = self._load_expression(self.current_expression)
        self._next_pixmap = None

        for label in (self.ui.petLable, self.ui.petLableNext):
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.current_effect = QGraphicsOpacityEffect(self.ui.petLable)
        self.next_effect = QGraphicsOpacityEffect(self.ui.petLableNext)
        self.ui.petLable.setGraphicsEffect(self.current_effect)
        self.ui.petLableNext.setGraphicsEffect(self.next_effect)
        self.current_effect.setOpacity(1.0)
        self.next_effect.setOpacity(0.0)
        self.current_effect.setEnabled(False)  # 静止时直接绘制，动画期间才启用效果

        self.transition = QParallelAnimationGroup(self)
        for effect, start, end in (
            (self.current_effect, 1.0, 0.0),
            (self.next_effect, 0.0, 1.0),
        ):
            animation = QPropertyAnimation(effect, b"opacity")
            animation.setDuration(200)  # 沿用原人物程序的切换速度
            animation.setStartValue(start)
            animation.setEndValue(end)
            self.transition.addAnimation(animation)
        self.transition.finished.connect(self._finish_transition)
        self.set_display_height(self.DESIGN_HEIGHT)

    def _load_expression(self, expression):
        # 神态只允许是文件名，防止把路径误当神态输入。
        if not expression or Path(expression).name != expression or "\\" in expression:
            raise ValueError("神态应为PNG文件名，不包含路径和扩展名")
        expression = self.catalog.normalize(expression)
        path = self.catalog.paths[expression]
        pixmap = self._pixmaps[expression]
        if pixmap.isNull():
            raise ValueError(f"无法加载立绘：{path}")
        return pixmap

    def set_display_height(self, height):
        width = round(height * self.DESIGN_WIDTH / self.DESIGN_HEIGHT / self.VISIBLE_FRACTION)
        self.setFixedSize(max(1, width), height)
        for label, pixmap in (
            (self.ui.petLable, self._current_pixmap),
            (self.ui.petLableNext, self._next_pixmap),
        ):
            label.setGeometry(self.rect())
            if pixmap is not None:
                label.setPixmap(self._fit_upper_body(pixmap))

    def _fit_upper_body(self, pixmap):
        # copy(x, y, 宽, 高)：取上半张，再等比例填入原来的人物显示高度。
        crop_height = max(1, round(pixmap.height() * self.VISIBLE_FRACTION))
        upper_body = pixmap.copy(0, 0, pixmap.width(), crop_height)
        return upper_body.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def image_rect(self):
        """返回图片在人物控件中的矩形；右对齐后，左侧空白不参与定位。"""
        size = self.ui.petLable.pixmap().deviceIndependentSize().toSize()
        return QRect(self.width() - size.width(), 0, size.width(), size.height())

    @Slot(str)
    def change_expression(self, expression):
        expression = self.catalog.normalize(expression)
        try:
            pixmap = self._load_expression(expression)
        except ValueError as error:
            print(error, flush=True)
            return
        if self._switching:
            self._pending_expression = expression  # 连续输入时保留最新神态
            return
        if expression == self.current_expression:
            return
        self._next_pixmap = pixmap
        self._next_expression = expression
        self.ui.petLableNext.setPixmap(self._fit_upper_body(pixmap))
        self._switching = True
        self.current_effect.setEnabled(True)
        self.transition.start()

    def _finish_transition(self):
        self._current_pixmap = self._next_pixmap
        self._next_pixmap = None
        self.current_expression = self._next_expression
        self.ui.petLable.setPixmap(self.ui.petLableNext.pixmap())
        self.current_effect.setOpacity(1.0)
        self.current_effect.setEnabled(False)
        self.next_effect.setOpacity(0.0)
        self._switching = False
        if self._pending_expression is not None:
            expression = self._pending_expression
            self._pending_expression = None
            self.change_expression(expression)
