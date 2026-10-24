"""滚轮只能滚动页面/列表，不能误改下拉框或数值框；不启动语音后台。"""
import unittest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QScrollArea,
                               QSpinBox, QStyle, QStyleOptionSpinBox, QVBoxLayout, QWidget)

from app.ui.control_panel import ControlPanelWindow


class WheelControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.window = ControlPanelWindow()
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.combo = QComboBox()
        self.combo.addItems(['一', '二', '三'])
        self.combo.setCurrentIndex(1)
        self.spin = QSpinBox()
        self.spin.setRange(0, 10)
        self.spin.setValue(5)
        self.double = QDoubleSpinBox()
        self.double.setValue(1.5)
        self.double.setSingleStep(.5)
        for widget in (self.combo, self.spin, self.double):
            self.layout.addWidget(widget)
        self.window.setCentralWidget(self.content)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def wheel(self, widget, delta=120):
        point = widget.rect().center()
        event = QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(),
                            QPoint(0, delta), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(widget, event)

    def test_wheel_does_not_change_focused_or_unfocused_values(self):
        for focused in (False, True):
            for widget in (self.combo, self.spin, self.double):
                with self.subTest(widget=type(widget).__name__, focused=focused):
                    widget.setFocus() if focused else widget.clearFocus()
                    read = widget.currentIndex if isinstance(widget, QComboBox) else widget.value
                    before = read()
                    self.wheel(widget)
                    self.assertEqual(read(), before)
                    self.wheel(widget, -120)
                    self.assertEqual(read(), before)

    def test_later_created_combo_is_also_protected(self):
        combo = QComboBox(self.content)
        combo.addItems(['A', 'B', 'C'])
        combo.setCurrentIndex(1)
        self.layout.addWidget(combo)
        combo.setFocus()
        self.wheel(combo)
        self.assertEqual(combo.currentIndex(), 1)

    def test_widgets_outside_control_panel_keep_their_behavior(self):
        combo = QComboBox()
        try:
            combo.addItems(['A', 'B', 'C'])
            combo.setCurrentIndex(1)
            self.wheel(combo)
            self.assertEqual(combo.currentIndex(), 0)
        finally:
            combo.close()
            combo.deleteLater()

    def test_open_dropdown_can_scroll_and_click_to_select(self):
        self.combo.clear()
        self.combo.addItems([str(index) for index in range(100)])
        self.combo.setCurrentIndex(1)
        self.combo.setMaxVisibleItems(5)
        self.combo.showPopup()
        self.app.processEvents()
        try:
            view = self.combo.view()
            before = view.verticalScrollBar().value()
            self.wheel(view.viewport(), -120)
            # Qt 6.12 can continue moving the popup after the wheel event. Read
            # the target row only after scrolling settles, then click its rect.
            QTest.qWait(250)
            self.app.processEvents()
            self.assertGreater(view.verticalScrollBar().value(), before)
            self.assertEqual(self.combo.currentIndex(), 1)
            index = view.indexAt(view.viewport().rect().center())
            self.assertTrue(index.isValid())
            self.assertNotEqual(index.row(), 1)
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                             pos=view.visualRect(index).center())
            self.assertEqual(self.combo.currentIndex(), index.row())
        finally:
            self.combo.hidePopup()

    def test_keyboard_and_spin_buttons_still_work(self):
        QTest.keyClick(self.combo, Qt.Key.Key_Down)
        self.assertEqual(self.combo.currentIndex(), 2)
        QTest.keyClick(self.spin, Qt.Key.Key_Up)
        self.assertEqual(self.spin.value(), 6)
        QTest.keyClick(self.double, Qt.Key.Key_Up)
        self.assertEqual(self.double.value(), 2.0)
        option = QStyleOptionSpinBox()
        self.spin.initStyleOption(option)
        up = self.spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option,
                                              QStyle.SubControl.SC_SpinBoxUp, self.spin)
        QTest.mouseClick(self.spin, Qt.MouseButton.LeftButton, pos=up.center())
        self.assertEqual(self.spin.value(), 7)

    def test_native_wheel_over_combo_scrolls_parent_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.window.takeCentralWidget()
        scroll.setWidget(self.content)
        self.content.setMinimumHeight(1000)
        self.window.setCentralWidget(scroll)
        self.window.resize(320, 240)
        self.app.processEvents()
        bar = scroll.verticalScrollBar()
        bar.setValue(200)
        position = self.combo.mapTo(self.window, self.combo.rect().center())
        before = bar.value()
        QTest.wheelEvent(self.window.windowHandle(), position, QPoint(0, -120))
        self.app.processEvents()
        self.assertEqual(self.combo.currentIndex(), 1)
        self.assertGreater(bar.value(), before)
