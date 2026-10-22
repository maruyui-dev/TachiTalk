"""角色人设控件只更新配置，不在Qt主线程发起LLM请求。"""
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPlainTextEdit

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
        self.character_name.setToolTip('修改后从下一轮对话生效；留空使用茉子。')
        self.user_name.setToolTip('留空不指定称呼；填写后让角色使用此称呼。')
        self.language.setToolTip('控制AI气泡的文字语言；配音继续使用日语。下一轮生效。')
        self.persona.setPlaceholderText('留空使用 config.py 的 PROMPT；填写后优先使用这里的人设与说话方式。下一轮生效。')
        self.streaming.setToolTip('开启：随模型生成更新气泡；关闭：完整回复生成后一次显示。下一轮生效。')
        self.expressions.setToolTip('关闭后每轮固定使用平常.png；不改变配音的情绪参考。下一轮生效。')
        self.context.setToolTip('一轮为你的一次输入和AI的一次完整回复。仅保留最近所选轮数，下一轮生效。')
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
                             context_turns=(20, 10, 5)[self.context.currentIndex()])

