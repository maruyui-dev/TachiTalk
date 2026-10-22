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
TTS_REFERENCE_DIR = ASSET_DIR / 'audio' / 'tts_reference'
TTS_SERVICE_DIR = PROJECT_ROOT / 'services' / 'gpt_sovits'
