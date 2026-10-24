"""当前人设：界面整体写入，LLM每轮读取一份不可变快照。"""
from dataclasses import dataclass, replace
from threading import Lock


REPLY_LANGUAGES = ('简体中文', '英文', '日文')


@dataclass(frozen=True, slots=True)
class PersonaProfile:
    character_name: str = '茉子'
    user_name: str = ''
    reply_language: str = '简体中文'
    persona_prompt: str = ''
    stream_reply: bool = True
    switch_expression: bool = True
    context_turns: int = 20


class PersonaStore:
    def __init__(self):
        self._lock = Lock()
        self._profile = PersonaProfile()

    def snapshot(self):
        with self._lock:
            return self._profile

    def update(self, *, character_name, user_name, reply_language, persona_prompt,
               stream_reply=None, switch_expression=None, context_turns=None):
        if reply_language not in REPLY_LANGUAGES:
            raise ValueError('回复语言只支持简体中文、英文、日文')
        changes = dict(character_name=character_name.strip() or '茉子', user_name=user_name.strip(),
                       reply_language=reply_language, persona_prompt=persona_prompt.strip())
        if stream_reply is not None:
            changes['stream_reply'] = bool(stream_reply)
        if switch_expression is not None:
            changes['switch_expression'] = bool(switch_expression)
        if context_turns is not None:
            if type(context_turns) is not int or not 1 <= context_turns <= 500:
                raise ValueError('对话记忆轮数须为1–500轮')
            changes['context_turns'] = context_turns
        with self._lock:
            self._profile = replace(self._profile, **changes)

