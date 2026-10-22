"""可用立绘神态：资源页写入，后台每轮读取不可变快照。"""
from dataclasses import dataclass
from threading import Lock


def valid_expression_name(name):
    return (isinstance(name, str) and 0 < len(name) <= 64 and name == name.strip()
            and name not in ('.', '..') and not any(
                char in '/\\:*?"<>|' or ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in name))


@dataclass(frozen=True, slots=True)
class ExpressionSnapshot:
    names: tuple[str, ...]
    default: str


class ExpressionStore:
    def __init__(self, names=('平常',), default='平常'):
        self._lock = Lock()
        self.update(names, default)

    def update(self, names, default):
        names = tuple(dict.fromkeys(name for name in names if valid_expression_name(name)))
        if default not in names:
            raise ValueError('默认神态必须在可用立绘列表中')
        with self._lock:
            self._snapshot = ExpressionSnapshot(names, default)

    def snapshot(self):
        with self._lock:
            return self._snapshot
