"""完整对话轮：最多500轮，本机加密原子保存；上下文窗口不破坏已存记忆。"""
from collections import deque
import json
import logging
from threading import RLock


class ConversationHistory:
    MAX_TURNS = 500

    def __init__(self, file=None, report=None):
        self._turns = deque(maxlen=self.MAX_TURNS)
        self._lock = RLock()
        self.file = file
        self.report = report or logging.getLogger('tachitalk.memory').warning
        self.revision = 0
        self.last_error = ''
        self.preserve_original = False
        if file is not None:
            self.load()

    def _validate_limit(self, limit):
        if type(limit) is not int or not 0 <= limit <= self.MAX_TURNS:
            raise ValueError('上下文轮数超出上限')

    def messages(self, limit):
        self._validate_limit(limit)
        with self._lock:
            messages = []
            for user, assistant in list(self._turns)[-limit:] if limit else ():
                messages.extend(({'role': 'user', 'content': user}, {'role': 'assistant', 'content': assistant}))
            return messages

    def append(self, user, assistant, limit, *, revision=None):
        self._validate_limit(limit)
        if not isinstance(user, str) or not isinstance(assistant, str):
            raise ValueError('记忆必须为完整的文字对话')
        with self._lock:
            if revision is not None and revision != self.revision:
                return  # Clearing during generation must not resurrect its old turn.
            self._turns.append((user, assistant))
            self.save()

    @property
    def count(self):
        with self._lock:
            return len(self._turns)

    def load(self):
        from app.core.session_file import SessionFile
        for source in (self.file, SessionFile(self.file.path.with_name('conversation.recovered.dat'))):
            try:
                document = source.read()
                if document is None:
                    continue
                if (not isinstance(document, dict) or set(document) != {'format', 'version', 'turns'}
                        or document['format'] != 'TachiTalk.memory' or type(document['version']) is not int
                        or document['version'] != 1 or not isinstance(document['turns'], list)
                        or len(document['turns']) > self.MAX_TURNS
                        or any(not isinstance(pair, list) or len(pair) != 2 or
                               any(not isinstance(text, str) for text in pair) for pair in document['turns'])):
                    raise ValueError('记忆文件结构无效')
                self._turns.extend(tuple(pair) for pair in document['turns'])
                return
            except (OSError, ValueError, TypeError, RecursionError) as error:
                self.preserve_original = True
                self.last_error = f'对话记忆恢复失败（{type(error).__name__}）；原文件保留'
                self.report(self.last_error)

    def save(self):
        with self._lock:
            return self._save()

    def _save(self):
        if self.file is None:
            return True
        from app.core.session_file import SessionFile
        from app.core.configuration_file import MAX_BYTES
        try:
            target = SessionFile(self.file.path.with_name('conversation.recovered.dat')) if self.preserve_original else self.file
            document = {'format': 'TachiTalk.memory', 'version': 1, 'turns': list(self._turns)}
            # Bound encrypted data as well as turn count; large answers must never
            # make future startup allocate unbounded memory.
            sizes = [len(json.dumps(pair, ensure_ascii=False).encode('utf-8')) for pair in document['turns']]
            total = len(json.dumps(dict(document, turns=[]), ensure_ascii=False).encode('utf-8'))
            total += sum(sizes) + max(0, len(sizes)-1)*2
            dropped = 0
            while total > MAX_BYTES and sizes:
                total -= sizes.pop(0) + 2
                document['turns'].pop(0)
                dropped += 1
            target.write(document)
            self._turns = deque(map(tuple, document['turns']), maxlen=self.MAX_TURNS)
            self.last_error = ''
            if dropped:
                self.report(f'对话记忆达到8MB容量上限，已保留最近{len(self._turns)}轮')
            return True
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            self.last_error = f'对话记忆保存失败（{type(error).__name__}）；本次记忆仅保留在内存，原文件未替换'
            self.report(self.last_error)
            return False

    def clear(self):
        with self._lock:
            previous = self._turns
            self._turns = deque(maxlen=self.MAX_TURNS)
            if not self.save():
                self._turns = previous
                return False
            self.revision += 1
            return True
