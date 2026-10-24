"""角色人设控件只更新配置，不在Qt主线程发起LLM请求。"""
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QPushButton, QLabel, QMessageBox

from app.core.persona import PersonaStore


class PersonaControls(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.profiles = PersonaStore()
        self.character_name = panel.findChild(QLineEdit, 'characterNameEdit')
        self.user_name = panel.findChild(QLineEdit, 'userNameEdit')
        self.language = panel.findChild(QComboBox, 'replyLanguageCombo')
        self.persona = panel.findChild(QPlainTextEdit, 'personaEdit')
        self.streaming = panel.findChild(QCheckBox, 'streamReplyCheck')
        self.expressions = panel.findChild(QCheckBox, 'expressionLinkCheck')
        self.context = panel.findChild(QComboBox, 'contextTurnsCombo')
        for index, value in enumerate((20, 10, 5)):
            self.context.setItemData(index, value)
        for value in (50, 100, 200, 500, *(n for n in range(1, 501) if n not in (5, 10, 20, 50, 100, 200, 500))):
            self.context.addItem(f'最近 {value} 轮', value)
        self.context.setMaxVisibleItems(12)
        self.history = None
        layout = self.context.parentWidget().layout()
        self.clear_memory = QPushButton('清空对话记忆', self.context.parentWidget())
        self.clear_memory.setObjectName('clearMemoryButton')
        self.clear_memory.setEnabled(False)
        self.memory_status = QLabel('本机最多加密保存500轮；退出重开保留', self.context.parentWidget())
        self.memory_status.setWordWrap(True)
        layout.addWidget(self.clear_memory, 3, 1)
        layout.addWidget(self.memory_status, 4, 0, 1, 2)
        self.clear_memory.clicked.connect(self.clear_history)
        self.memory_timer = QTimer(self)
        self.memory_timer.setInterval(1000)
        self.memory_timer.timeout.connect(self.refresh_memory)
        self.memory_timer.start()
        self.character_name.setToolTip('修改后从下一轮对话生效；留空使用茉子。')
        self.user_name.setToolTip('留空不指定称呼；填写后让角色使用此称呼。')
        self.language.setToolTip('控制AI气泡的文字语言；配音继续使用日语。下一轮生效。')
        self.persona.setPlaceholderText('留空使用 config.py 的 PROMPT；填写后优先使用这里的人设与说话方式。下一轮生效。')
        self.streaming.setToolTip('开启：随模型生成更新气泡；关闭：完整回复生成后一次显示。下一轮生效。')
        self.expressions.setToolTip('关闭后每轮固定使用平常.png；不改变配音的情绪参考。下一轮生效。')
        self.context.setToolTip('一轮为一次输入和一次完整回复。选1–500轮用于下一轮上下文；本机最多保存500轮。减少上下文不删除其余记忆；更大上下文增加API用量，并受模型上下文上限限制。')
        self.character_name.textChanged.connect(self.update_profile)
        self.user_name.textChanged.connect(self.update_profile)
        self.language.currentTextChanged.connect(self.update_profile)
        self.persona.textChanged.connect(self.update_profile)
        self.streaming.toggled.connect(self.update_profile)
        self.expressions.toggled.connect(self.update_profile)
        self.context.currentIndexChanged.connect(self.update_profile)
        self.update_profile()

    def bind_profiles(self, profiles):
        self.profiles = profiles
        self.update_profile()

    def update_profile(self):
        self.profiles.update(character_name=self.character_name.text(), user_name=self.user_name.text(),
                             reply_language=self.language.currentText(), persona_prompt=self.persona.toPlainText(),
                             stream_reply=self.streaming.isChecked(), switch_expression=self.expressions.isChecked(),
                             context_turns=self.context.currentData())

    def bind_history(self, history):
        self.history = history
        self.parent().closing.connect(history.save)
        self.clear_memory.setEnabled(True)
        self.refresh_memory()

    def refresh_memory(self):
        if self.history is not None:
            self.memory_status.setText(self.history.last_error or
                f'已保留 {self.history.count}/500 轮 · 下一轮使用最近 {self.context.currentData()} 轮 · 退出重开保留')

    def clear_history(self):
        if self.history is None:
            return
        if QMessageBox.question(self.clear_memory, '清空对话记忆', '清空本机保存的全部对话记忆？角色设置和API配置不会改变。') != QMessageBox.StandardButton.Yes:
            return
        self.history.clear()
        self.refresh_memory()

