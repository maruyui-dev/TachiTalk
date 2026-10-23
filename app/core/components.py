"""Optional voice detection; never imports torch or starts inference."""
import json
from pathlib import Path
from dataclasses import replace

from app.paths import TTS_SERVICE_DIR
from scripts.start_tts import check_files


def voice_status(root=TTS_SERVICE_DIR):
    try:
        distribution = Path(root) / 'distribution.json'
        if distribution.is_file() and distribution.stat().st_size > 65536:
            raise ValueError('语音发行信息过大')
        missing = check_files(root)
    except (OSError, ValueError, RecursionError) as error:
        missing = [f'语音资源无法检查：{error}']
    version = 'legacy-v2ProPlus-cu128' if not missing else '未安装 / 文件不完整'
    record = Path(root) / 'component-version.json'
    if not missing and record.is_file():
        try:
            version = json.loads(record.read_text(encoding='utf-8'))['version']
        except (OSError, ValueError, KeyError, RecursionError):
            version = '版本记录损坏（请修复）'
    return {'installed': not missing, 'version': version, 'missing': missing}


def prepare_optional_voice(voices, root=TTS_SERVICE_DIR):
    from app.services.local_tts import LocalTTSService
    options = voices.snapshot().tts
    try:
        available = LocalTTSService.local_port(options) is None or voice_status(root)['installed']
    except ValueError:
        available = False
    if not available:
        voices.set_tts(replace(options, auto_read=False))
        return False
    return True
