"""The signed payload is the sole authority for executable file operations."""
import base64
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPOSITORY = 'maruyui-dev/TachiTalk'
MAX_MANIFEST = 32 * 1024 * 1024  # Private runtime inventory is already ~10 MiB; bounded explicitly.


def canonical(payload):
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def sha256(path, progress=None):
    digest = hashlib.sha256()
    completed = 0
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
            completed += len(block)
            if progress:
                progress(completed)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.new')
    with temp.open('wb') as stream:
        stream.write(canonical(value))
        stream.flush()
        import os
        os.fsync(stream.fileno())
    temp.replace(path)


def safe_path(value):
    if (not isinstance(value, str) or not value or len(value) > 1024 or '\\' in value or ':' in value
            or value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('不安全的文件路径')
    for part in value.split('/'):
        if part.endswith((' ', '.')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?', part):
            raise ValueError('Windows保留文件名')
        if any(ord(c) < 32 or c in '<>"|?*' for c in part):
            raise ValueError('非法文件名')
    return PurePosixPath(value)


def allowed_path(component, value):
    safe_path(value)
    lower = value.lower()
    # Application delivery must never own configuration, imported assets, logs or inference.
    if component == 'main':
        allowed = (lower in {'tachitalk.exe', 'tachitalkupdater.exe', 'readme.md', 'license', 'third_party_notices.md', 'requirements.txt'}
                   or lower.startswith(('_internal/', 'resources/control_panel/', 'licenses/'))
                   or lower in {'scripts/tts_service_entry.py', 'scripts/whisper_worker.py'})
    else:
        allowed = lower.startswith(('services/gpt_sovits/', 'assets/audio/tts_reference/'))
    if not allowed or lower.endswith(('.log', '.tmp', '.tachitalk.json')) or '/__pycache__/' in lower:
        raise ValueError(f'组件无权修改文件：{value}')
    if lower in {'services/gpt_sovits/component-version.json'}:
        raise ValueError('版本记录由安装事务管理')


def official_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment
            or not parsed.path.startswith('/' + REPOSITORY + '/releases/download/')
            or len(parsed.path.split('/')) != 7 or '%' in parsed.path
            or any(part in ('.', '..', '') for part in parsed.path.split('/')[1:])):
        raise ValueError('资源地址必须属于官方仓库的Release附件')
    return value


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('主程序版本必须为数字三段版本')
    return tuple(map(int, value.lstrip('v').split('.')))


def validate(payload):
    if payload.get('schema') != 1 or payload.get('component') not in ('main', 'voice'):
        raise ValueError('未知清单格式或组件')
    component = payload['component']
    if len(payload['files']) > 100000 or len(payload.get('delete', [])) > 100000:
        raise ValueError('清单文件数量超出上限')
    for field, maximum in [('title', 512), ('notes', 65536), ('published_at', 128)]:
        if not isinstance(payload.get(field, ''), str) or len(payload.get(field, '')) > maximum:
            raise ValueError('更新介绍字段过长或格式不正确')
    if not isinstance(payload.get('version'), str) or not payload['version']:
        raise ValueError('组件版本缺失')
    if component == 'main':
        version_tuple(payload['version'])
        version_tuple(payload['base_version'])
        if version_tuple(payload['version']) <= version_tuple(payload['base_version']):
            raise ValueError('主程序更新必须升级版本')
    elif 'min_main_version' in payload:
        version_tuple(payload['min_main_version'])
    paths = set()
    for record in payload['files']:
        name = record['path']
        allowed_path(component, name)
        key = name.casefold()
        if key in paths:
            raise ValueError('重复文件路径')
        paths.add(key)
        validate_digest(record)
    for name in payload.get('delete', []):
        allowed_path(component, name)
        if name.casefold() in paths:
            raise ValueError('重复或冲突的删除操作')
        paths.add(name.casefold())
    for name in paths:
        if any(str(p).casefold() in paths for p in PurePosixPath(name).parents if str(p) != '.'):
            raise ValueError('文件和目录路径冲突')
    validate_digest(payload['archive'])
    if not payload['parts']:
        raise ValueError('缺少下载分卷')
    total = 0
    for part in payload['parts']:
        safe_path(part['name'])
        if '/' in part['name']:
            raise ValueError('分卷必须为文件名')
        official_url(part['url'])
        for alternative in part.get('urls', []):
            official_url(alternative)
        validate_digest(part)
        total += part['size']
    if total != payload['archive']['size']:
        raise ValueError('分卷大小不匹配')
    return payload


def validate_digest(record):
    if (type(record.get('size')) is not int or record['size'] < 0
            or not re.fullmatch('[a-f0-9]{64}', record.get('sha256', ''))):
        raise ValueError('缺少有效的大小或SHA-256')


def verify(envelope, keys):
    if not isinstance(envelope, dict) or envelope.get('key_id') not in keys:
        raise ValueError('没有可信发布公钥；请安装维护者签发的客户端')
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(keys[envelope['key_id']], validate=True))
        key.verify(base64.b64decode(envelope['signature'], validate=True), canonical(envelope['payload']))
    except (InvalidSignature, ValueError, KeyError, TypeError) as error:
        raise ValueError('更新清单签名无效') from error
    return validate(envelope['payload'])


def load_signed(path, keys):
    path = Path(path)
    if path.stat().st_size > MAX_MANIFEST:
        raise ValueError('清单过大')
    envelope = json.loads(path.read_text(encoding='utf-8'))
    return envelope, verify(envelope, keys)
