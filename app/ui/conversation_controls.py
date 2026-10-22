"""快速预览与正式输入分别绑定；Qt主线程不执行录音或网络请求。"""
from PySide6.QtCore import QObject, QSignalBlocker, Qt, Slot
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QLabel, QPlainTextEdit, QPushButton, QWidget


class ConversationControls(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.inputs = None
        self.quick_edit = panel.findChild(QPlainTextEdit, 'messageEdit')
        self.quick_hint = panel.findChild(QLabel, 'quickPreviewHint')
        self.pink = panel.findChild(QPushButton, 'choosePinkButton')
        self.blue = panel.findChild(QPushButton, 'chooseBlueButton')
        self.colors = QButtonGroup(self)
        self.colors.addButton(self.pink)
        self.colors.addButton(self.blue)
        self.recording = panel.findChild(QCheckBox, 'recordingEnabledCheck')
        self.status = panel.findChild(QLabel, 'conversationStatus')
        self.text_row = panel.findChild(QWidget, 'textConversationRow')
        self.text_edit = panel.findChild(QPlainTextEdit, 'textConversationEdit')
        self.text_send = panel.findChild(QPushButton, 'textConversationSend')
        self.recording.setEnabled(False)
        panel.findChild(QPushButton, 'sendButton').clicked.connect(self.send_preview)
        self.recording.toggled.connect(self.set_recording)
        self.text_send.clicked.connect(self.send_text)

    def send_preview(self):
        text = self.quick_edit.toPlainText().strip()
        if not text or len(text) > 300:
            self.quick_hint.setText('请输入1–300字用于预览测试。')
            return
        color = 'pink' if self.pink.isChecked() else 'blue'
        self.panel.bubble_preview.set_message(color, text)
        self.quick_edit.clear()
        self.quick_hint.setText('已更新' + ('粉色' if color == 'pink' else '蓝色') + '预览气泡。')

    def bind_inputs(self, inputs, signals):
        self.inputs = inputs
        signals.input_state.connect(self.apply_input_state, Qt.ConnectionType.QueuedConnection)
        self.recording.setEnabled(True)
        self.apply_input_state(inputs.snapshot())

    def set_recording(self, enabled):
        if self.inputs is not None:
            self.inputs.set_recording(enabled)
            self.apply_input_state(self.inputs.snapshot())
            if not enabled:
                self.text_edit.setFocus()

    def send_text(self):
        if self.inputs is None:
            return
        accepted, message = self.inputs.submit_text(self.text_edit.toPlainText())
        self.status.setText(message)
        if accepted:
            self.text_edit.clear()
        self.apply_input_state(self.inputs.snapshot())
        if not accepted:
            self.status.setText(message)

    @Slot(object)
    def apply_input_state(self, state):
        with QSignalBlocker(self.recording):
            self.recording.setChecked(state.recording)
        self.text_row.setVisible(not state.recording)
        self.text_send.setEnabled(not state.recording and state.ready and (not state.busy or state.can_interrupt))
        self.text_send.setText('打断并发送' if state.can_interrupt else '回复中…' if state.busy else '发送对话')
        self.status.setText(state.message)
