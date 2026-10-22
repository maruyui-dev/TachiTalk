"""LLM上下文按完整对话轮保存；运行线程内使用，始终有界。"""
from collections import deque


class ConversationHistory:
    MAX_TURNS = 20

    def __init__(self):
        self._turns = deque(maxlen=self.MAX_TURNS)

    def _trim(self, limit):
        if not 0 <= limit <= self.MAX_TURNS:
            raise ValueError('上下文轮数超出上限')
        while len(self._turns) > limit:
            self._turns.popleft()

    def messages(self, limit):
        self._trim(limit)
        messages = []
        for user, assistant in self._turns:
            messages.extend(({'role': 'user', 'content': user}, {'role': 'assistant', 'content': assistant}))
        return messages

    def append(self, user, assistant, limit):
        self._turns.append((user, assistant))
        self._trim(limit)
