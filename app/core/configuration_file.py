"""带版本的JSON配置文件；只解析数据，以原子替换方式写入用户选择的位置。

设计依据：docs.python.org/3.12/library/json.html（不可信输入限制大小）；
doc.qt.io/qtforpython-6/PySide6/QtCore/QSaveFile.html（commit成功后替换目标文件）。
"""
import json
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

FORMAT = 'TachiTalk.settings'
VERSION = 1
MAX_BYTES = 8 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('配置文件含有重复字段')
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError('配置含有非有限数字')


def check_envelope(document):
    if (not isinstance(document, dict) or document.get('format') != FORMAT
            or type(document.get('version')) is not int or document['version'] != VERSION):
        raise ValueError('不是受支持的TachiTalk配置文件，或配置版本不兼容')
    expected = {'format', 'version', 'pages', 'profiles', 'desktop', 'resources'}
    if (set(document) not in (expected, expected | {'audio_resources'})
            or any(not isinstance(document[name], dict) for name in set(document) - {'format', 'version'})):
        raise ValueError('配置文件结构不完整或含有未知字段')
    return document


def read_config(filename):
    with Path(filename).open('rb') as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('配置文件超过8MB，无法加载')
    try:
        document = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
        return check_envelope(document)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('配置文件不是有效的UTF-8 JSON，请选择由TachiTalk保存的配置文件') from error


def write_config(filename, document):
    check_envelope(document)
    path = Path(filename)
    if path.suffix.lower() != '.json':
        raise ValueError('配置文件请使用.json扩展名')
    data = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    if len(data) > MAX_BYTES:
        raise ValueError('配置内容超过8MB，无法保存')
    target = QSaveFile(str(path))
    if not target.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError('配置文件无法写入，请检查所选目录的权限')
    if target.write(data) != len(data) or not target.commit():
        target.cancelWriting()
        raise OSError('配置保存失败，原配置文件未替换')
