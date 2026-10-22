"""界面配置项的白名单、读写和范围校验；不触发录音、网络或资源操作。"""
from contextlib import ExitStack
import math

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QKeySequenceEdit, QLineEdit,
                               QPlainTextEdit, QPushButton, QSlider, QSpinBox)

from app.core.settings_defaults import DATA_COMBOS, KEY_FIELDS, PAGE_DEFAULTS, TEXT_COMBOS
from app.ui.recording_hotkey import shortcut_virtual_keys


class ConfigurationWidgets:
    def __init__(self, panel):
        self.fields = {page: tuple(values) + KEY_FIELDS.get(page, ()) for page, values in PAGE_DEFAULTS.items()}
        self.widgets = {name: panel.findChild(QObject, name) for names in self.fields.values() for name in names}
        if any(widget is None for widget in self.widgets.values()):
            raise RuntimeError('全局配置白名单中有缺失的界面控件')

    def read(self, name):
        widget = self.widgets[name]
        if isinstance(widget, (QCheckBox, QPushButton)):
            return widget.isChecked()
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        if isinstance(widget, QLineEdit):
            return widget.text()
        if isinstance(widget, QKeySequenceEdit):
            return widget.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if isinstance(widget, QComboBox):
            if name in TEXT_COMBOS:
                return widget.currentText()
            if name in DATA_COMBOS:
                return (widget.currentData() or '') if name == 'systemVoiceCombo' else widget.currentData()
            return widget.currentIndex()
        return widget.value()

    def capture(self):
        return {page: {name: self.read(name) for name in names} for page, names in self.fields.items()}

    def validate(self, pages):
        if not isinstance(pages, dict) or set(pages) != set(self.fields):
            raise ValueError('配置必须包含全部六个页面')
        for page, names in self.fields.items():
            values = pages[page]
            if page == 'aiPage' and isinstance(values, dict) and 'replyLengthSpin' not in values:
                values['replyLengthSpin'] = 0  # 旧版配置按默认短回复载入。
            if not isinstance(values, dict) or set(values) != set(names):
                raise ValueError('页面配置字段缺失或含有未知字段')
            for name, value in values.items():
                widget = self.widgets[name]
                if isinstance(widget, (QCheckBox, QPushButton)):
                    valid = type(value) is bool
                elif isinstance(widget, (QSlider, QSpinBox, QDoubleSpinBox)):
                    types = (int, float) if isinstance(widget, QDoubleSpinBox) else (int,)
                    valid = type(value) in types and widget.minimum() <= value <= widget.maximum() and math.isfinite(value)
                elif isinstance(widget, QComboBox) and name not in TEXT_COMBOS | DATA_COMBOS:
                    valid = type(value) is int and 0 <= value < widget.count()
                elif name in ('microphoneCombo', 'speakerCombo'):
                    minimum = -1 if name == 'microphoneCombo' else 0
                    valid = value is None or type(value) is int and minimum <= value <= 65535
                else:
                    valid = isinstance(value, str) and len(value) <= 16384 and '\x00' not in value
                if not valid:
                    raise ValueError(f'配置项{name}的类型或范围不正确')
                if name in ('asrApiKeyEdit', 'ttsApiKeyEdit', 'apiKeyEdit') and ('\n' in value or '\r' in value):
                    raise ValueError('API Key不能含有换行')
                if name == 'sampleRateCombo' and value not in ('8000 Hz', '16000 Hz', '32000 Hz', '48000 Hz'):
                    raise ValueError('录音采样率不受支持')
                if name == 'importResourceKind' and value not in ('portrait', 'pink', 'blue'):
                    raise ValueError('资源类型不正确')
        shortcut_virtual_keys(QKeySequence(pages['audioPage']['recordingShortcut']))

    def put(self, values):
        with ExitStack() as blockers:
            for name in values:
                blockers.enter_context(QSignalBlocker(self.widgets[name]))
            for name, value in values.items():
                widget = self.widgets[name]
                if isinstance(widget, (QCheckBox, QPushButton)):
                    widget.setChecked(value)
                elif isinstance(widget, QPlainTextEdit):
                    widget.setPlainText(value)
                elif isinstance(widget, QLineEdit):
                    widget.setText(value)
                elif isinstance(widget, QKeySequenceEdit):
                    widget.setKeySequence(QKeySequence(value))
                elif isinstance(widget, QComboBox):
                    if name in TEXT_COMBOS:
                        widget.setCurrentText(value)
                    elif name in DATA_COMBOS:
                        index = widget.findData(value)
                        if index < 0:
                            text = f'配置的设备 #{value} · 请重新获取并确认' if isinstance(value, int) else str(value or '默认')
                            widget.addItem(text, value)
                            index = widget.count() - 1
                        widget.setCurrentIndex(index)
                    else:
                        widget.setCurrentIndex(value)
                else:
                    widget.setValue(value)
