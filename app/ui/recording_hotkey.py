"""Windows全局按住说话：查询当前按键状态，不接管或屏蔽系统按键。"""
import ctypes
import sys

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication


def shortcut_virtual_keys(sequence):
    if sequence.count() != 1:
        raise ValueError('请设置一个组合键，例如Ctrl+Space或F8')
    combination = sequence[0]
    key, modifiers = combination.key(), combination.keyboardModifiers()
    keys = []
    for modifier, codes in ((Qt.KeyboardModifier.ControlModifier, (0x11,)),
                            (Qt.KeyboardModifier.ShiftModifier, (0x10,)),
                            (Qt.KeyboardModifier.AltModifier, (0x12,)),
                            (Qt.KeyboardModifier.MetaModifier, (0x5b, 0x5c))):
        if modifiers & modifier:
            keys.append(codes)
    specials = {Qt.Key.Key_Space: 0x20, Qt.Key.Key_Tab: 0x09, Qt.Key.Key_Return: 0x0d,
                Qt.Key.Key_Enter: 0x0d, Qt.Key.Key_Escape: 0x1b, Qt.Key.Key_Backspace: 0x08,
                Qt.Key.Key_Delete: 0x2e, Qt.Key.Key_Insert: 0x2d, Qt.Key.Key_Home: 0x24,
                Qt.Key.Key_End: 0x23, Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22,
                Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26, Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28}
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        code = int(key)
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        code = 0x70 + int(key) - int(Qt.Key.Key_F1)
    elif key in specials:
        code = specials[key]
    else:
        raise ValueError('此快捷键暂不支持，请使用字母、数字、空格或F1–F24组合')
    keys.append((code,))
    return keys


class HoldShortcut(QObject):
    def __init__(self, editor, callback, key_state=None):
        super().__init__(editor)
        self.editor, self.callback = editor, callback
        self.key_state = key_state
        if key_state is None and sys.platform == 'win32':
            self.key_state = ctypes.windll.user32.GetAsyncKeyState
            self.key_state.argtypes = [ctypes.c_int]
            self.key_state.restype = ctypes.c_short
        self.keys = shortcut_virtual_keys(editor.keySequence())
        self._down = False
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)

    def _pressed(self):
        return self.key_state is not None and all(any(self.key_state(code) & 0x8000 for code in group) for group in self.keys)

    def set_sequence(self, sequence):
        keys = shortcut_virtual_keys(sequence)
        self.callback(False)
        self.keys = keys
        self._down = self._pressed()

    def set_enabled(self, enabled):
        if enabled and self.key_state is None:
            raise ValueError('当前全局按住快捷键支持Windows；此系统请使用持续监听或点击录音')
        if enabled == self.timer.isActive():
            return
        self.callback(False)
        self._down = self._pressed()  # 启用时已按住的组合键必须先松开再按，避免误触发。
        self.timer.start() if enabled else self.timer.stop()

    def poll(self):
        down = self._pressed()
        focused = QApplication.focusWidget()
        editing = focused is self.editor or (focused is not None and self.editor.isAncestorOf(focused))
        if editing:
            self.callback(False)
        elif down != self._down:
            self.callback(down)
        self._down = down

    def close(self):
        self.timer.stop()
        self.callback(False)
