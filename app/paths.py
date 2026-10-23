"""项目自带文件的唯一路径入口；路径不依赖终端当前工作目录。"""
from pathlib import Path
import os
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
PROJECT_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[1]
DATA_ROOT = (Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'TachiTalk'
             if FROZEN else PROJECT_ROOT / '_qt_runtime_tmp')
ASSET_DIR = PROJECT_ROOT / 'assets'
BUBBLE_DIR = ASSET_DIR / 'bubbles'
def voice_location(project_root=PROJECT_ROOT, data_root=DATA_ROOT):
    """Reuse a user-selected legacy installation without moving its runtime or models."""
    import json
    project_root, data_root = Path(project_root), Path(data_root)
    if (project_root / 'services/gpt_sovits/runtime/python.exe').is_file():
        return project_root
    try:
        record = data_root / 'settings/voice_location.json'
        if record.stat().st_size > 16384:
            return project_root
        selected = Path(json.loads(record.read_text(encoding='utf-8'))['installation']).resolve()
        if (selected / 'services/gpt_sovits/runtime/python.exe').is_file():
            return selected
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return project_root


VOICE_ROOT = voice_location()
TTS_REFERENCE_DIR = VOICE_ROOT / 'assets' / 'audio' / 'tts_reference'
TTS_SERVICE_DIR = VOICE_ROOT / 'services' / 'gpt_sovits'
