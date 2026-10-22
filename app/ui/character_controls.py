"""连接角色显示控件；所有状态均从实际桌面立绘回读。"""
import logging
from functools import partial

from PySide6.QtCore import QObject, QSignalBlocker, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton, QSlider, QSpinBox, QStackedWidget, QWidget


ANCHOR_NAMES = (('左上角', '顶部居中', '右上角'),
                ('左侧居中', '屏幕中央', '右侧居中'),
                ('左下角', '底部居中', '右下角'))


class CharacterControls(QObject):
    """控件发出操作，状态始终从实际立绘窗口回读。"""

    def __init__(self, panel, pet):
        super().__init__(panel)
        self.pet = pet
        self.hide_button = panel.findChild(QPushButton, 'hideButton')
        self.top_check = panel.findChild(QCheckBox, 'topCheck')
        self.fixed_check = panel.findChild(QCheckBox, 'fixedCheck')
        self.status = panel.findChild(QLabel, 'visibleStatus')
        self.scale_slider = panel.findChild(QSlider, 'scaleSlider')
        self.scale_value = panel.findChild(QLabel, 'scaleValue')
        self.range_combo = panel.findChild(QComboBox, 'rangeCombo')
        self.range_slider = panel.findChild(QSlider, 'rangeSlider')
        self.range_row = panel.findChild(QWidget, 'customRangeRow')
        self.range_caption = panel.findChild(QLabel, 'customRangeCaption')
        self.range_value = panel.findChild(QLabel, 'rangeValue')
        self.position_value = panel.findChild(QLabel, 'positionValue')
        self.preview_position = panel.findChild(QLabel, 'previewPosition')
        self._range_mode = 0
        self._custom_percent = 50
        self.max_bubbles_spin = panel.findChild(QSpinBox, 'maxBubblesSpin')
        self.bubble_gap_spin = panel.findChild(QSpinBox, 'bubbleGapSpin')
        self.bubble_preview = panel.bubble_preview
        self.panel = panel
        self.anchor_buttons = {}
        for row in range(3):
            for column in range(3):
                button = panel.findChild(QPushButton, f'anchor{row}{column}')
                button.setAutoExclusive(False)  # 手动拖动后，允许清除全部九宫格选中状态。
                button.clicked.connect(partial(self.select_anchor, row, column))
                button.setToolTip(ANCHOR_NAMES[row][column])
                self.anchor_buttons[row, column] = button
        self.hide_button.clicked.connect(self.toggle_visible)
        self.top_check.toggled.connect(self.set_stays_on_top)
        self.fixed_check.toggled.connect(self.set_position_fixed)
        self.scale_slider.valueChanged.connect(pet.set_scale_percent)
        self.range_combo.currentIndexChanged.connect(self.set_range_mode)
        self.range_slider.valueChanged.connect(self.set_custom_percent)
        self.max_bubbles_spin.valueChanged.connect(pet.set_max_bubbles)
        self.bubble_gap_spin.valueChanged.connect(pet.set_bubble_gap)
        panel.findChild(QPushButton, 'resetPositionButton').clicked.connect(self.reset_position)
        panel.preview_image.render_scale_changed.connect(self.resize_preview_bubbles)
        pet.display_changed.connect(self.sync)
        for widget in (self.hide_button, self.top_check, self.fixed_check):
            widget.setEnabled(True)
        self.sync()

    def toggle_visible(self):
        self.pet.setVisible(not self.pet.isVisible())
        logging.getLogger('tachitalk.ui').info('角色：%s', '已显示' if self.pet.isVisible() else '已隐藏')

    def set_stays_on_top(self, enabled):
        self.pet.set_stays_on_top(enabled)
        logging.getLogger('tachitalk.ui').info('角色置顶：%s', '开启' if enabled else '关闭')

    def set_position_fixed(self, enabled):
        self.pet.set_position_fixed(enabled)
        logging.getLogger('tachitalk.ui').info('固定位置：%s', '开启' if enabled else '关闭')

    def set_range_mode(self, index):
        self._range_mode = index
        percent = (50, 100, self._custom_percent)[index]
        self.pet.set_display_percent(percent)
        self.sync()  # 从50%切到“自定义50%”时数值不变，也需要显示滑块。

    def set_custom_percent(self, value):
        self._custom_percent = value
        if self._range_mode == 2:
            self.pet.set_display_percent(value)
        self.sync()

    def select_anchor(self, row, column, _checked=False):
        self.pet.set_anchor(row, column)
        logging.getLogger('tachitalk.ui').info('桌面位置：%s', ANCHOR_NAMES[row][column])

    def reset_position(self):
        if self.panel.findChild(QStackedWidget, 'pageStack').currentIndex() == 0:
            self.select_anchor(2, 2)

    def resize_preview_bubbles(self, ratio):
        self.bubble_preview.set_options(self.pet.MAX_BUBBLES, self.pet.bubble_gap, ratio)

    def sync(self):
        visible = self.pet.isVisible()
        top = bool(self.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.hide_button.setText('隐藏角色' if visible else '显示角色')
        self.status.setText('●  角色已显示' if visible else '●  角色已隐藏')
        if self.status.property('roleHidden') != (not visible):
            self.status.setProperty('roleHidden', not visible)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            self.status.update()
        self.status.setToolTip(' · '.join((
            '已置顶' if top else '未置顶',
            '位置已固定' if self.pet.position_fixed else '可拖动立绘',
        )))
        # 回填控件不能再发一次操作信号，否则会重复隐藏/显示窗口。
        for widget, checked in ((self.top_check, top), (self.fixed_check, self.pet.position_fixed)):
            with QSignalBlocker(widget):
                widget.setChecked(checked)
        self.scale_value.setText(f'{self.pet.scale_percent}%')
        with QSignalBlocker(self.scale_slider):
            self.scale_slider.setValue(self.pet.scale_percent)
        if self._range_mode != 2 and self.pet.display_percent != (50, 100)[self._range_mode]:
            self._range_mode = 2
        if self._range_mode == 2:
            self._custom_percent = self.pet.display_percent
        with QSignalBlocker(self.range_combo):
            self.range_combo.setCurrentIndex(self._range_mode)
        with QSignalBlocker(self.range_slider):
            self.range_slider.setValue(self._custom_percent)
        self.range_value.setText(f'{self._custom_percent}%')
        self.range_row.setVisible(self._range_mode == 2)
        self.range_caption.setVisible(self._range_mode == 2)
        position = '自定义位置' if self.pet.anchor is None else ANCHOR_NAMES[self.pet.anchor[0]][self.pet.anchor[1]]
        self.position_value.setText(position)
        self.preview_position.setText('桌面' + position)
        for anchor, button in self.anchor_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(anchor == self.pet.anchor)
        for widget, value in ((self.max_bubbles_spin, self.pet.MAX_BUBBLES),
                              (self.bubble_gap_spin, self.pet.bubble_gap)):
            with QSignalBlocker(widget):
                widget.setValue(value)
        self.panel.preview_image.set_display_options(self.pet.scale_percent, self.pet.display_percent)
        self.resize_preview_bubbles(self.panel.preview_image.preview_ratio)
