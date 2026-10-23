"""发行构建的自检入口：真实界面、模型就绪及PCM输出；不录音、不调用付费API。"""
import asyncio
import json
import socket
from pathlib import Path
from time import monotonic

import aiohttp
from PySide6.QtWidgets import QApplication, QSpinBox, QWidget

from config import Settings
from app.core.models import SpeechPart
from app.core.voice_settings import TTSOptions
from app.paths import PROJECT_ROOT, DATA_ROOT, FROZEN
from app.services.local_tts import LocalTTSService
from app.services.tts import TTSClient
from app.ui.control_panel import load_window
from app.ui.desktop_pet import DesktopPetWindow
from app.ui.console import ConsoleUI


def run_core(destination):
    """Offline QA for the core-only product; no microphone, inference or external APIs."""
    from dataclasses import replace
    from types import SimpleNamespace
    from app.core.components import voice_status
    from app.core.pipeline import Pipeline
    from app.core.models import CaptionPart
    from app.core.voice_settings import VoiceSettings
    from app.ui.desktop import DesktopSignals, DesktopUI
    from PySide6.QtWidgets import QPushButton
    app = QApplication.instance() or QApplication([])
    pet = DesktopPetWindow()
    panel = load_window(pet=pet)
    panel.ensure_update_controls()
    result = {'frozen': FROZEN, 'root': str(PROJECT_ROOT), 'data': str(DATA_ROOT),
              'voice': voice_status(), 'ui_loaded': True,
              'resource_panel': hasattr(panel, 'update_controls'),
              'entry_enabled': panel.findChild(QPushButton, 'navDelivery').isEnabled()}
    signals = DesktopSignals()
    ui = DesktopUI(signals, Settings().max_reply_parts)
    captions, expressions = [], []
    signals.caption.connect(lambda turn, text: (captions.append(text), pet.set_reply_text(turn, text)))
    signals.expression.connect(lambda turn, text: (expressions.append(text), pet.play_expression(turn, text)))
    voices = VoiceSettings(Settings())
    voices.set_tts(replace(voices.snapshot().tts, auto_read=False))
    async def events(*args, **kwargs):
        yield SpeechPart(0, 'こんにちは。', '平常')
        yield CaptionPart(0, '离线验证：文字、立绘和气泡正常。')
    pipeline = Pipeline(Settings(), None, SimpleNamespace(events=events), None, None, ui, voices=voices)
    panel.show()
    pet.show()
    asyncio.run(pipeline.process_text('验证主程序'))
    app.processEvents()
    result.update(captions=captions, expressions=expressions, spoken=pipeline.last_metrics['spoken'])
    panel.grab().save(str(Path(destination).with_suffix('.png')))
    result['ok'] = bool(result['resource_panel'] and result['entry_enabled'] and captions and expressions and not result['spoken'])
    panel.close()
    pet.shutdown()
    app.processEvents()
    Path(destination).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


def run(destination):
    app = QApplication.instance() or QApplication([])
    panel = pet = None
    service = LocalTTSService(ConsoleUI())
    result = {'frozen': FROZEN, 'root': str(PROJECT_ROOT), 'data': str(DATA_ROOT)}
    started = monotonic()
    try:
        pet = DesktopPetWindow()
        panel = load_window(pet=pet)
        panel.show()
        app.processEvents()
        result['ui_loaded'] = True
        length = panel.findChild(QSpinBox, 'replyLengthSpin')
        result['reply_length_range'] = [length.minimum(), length.maximum()]
        panel.resize(1600, 920)
        app.processEvents()
        card = panel.findChild(QWidget, 'previewCard')
        result['preview_aspect_ratio'] = round(card.width() / card.height(), 3)
        async def check():
            # 使用独立空闲端口，必须验证包内环境，不复用用户已有服务。
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            options = TTSOptions(url=f'http://127.0.0.1:{port}/tts', timeout=120)
            loading = monotonic()
            await service.ensure(options)
            result['model_ready_seconds'] = round(monotonic() - loading, 3)
            result['tts_pid'] = service.process.pid if service.process else None
            result['tts_ready'] = service.ready
            async with aiohttp.ClientSession() as session:
                chunks = []
                synthesis = monotonic()
                async for chunk in TTSClient(session, Settings(), options).stream(SpeechPart(0, 'こんにちは。', '平常')):
                    if not chunks:
                        result['first_pcm_seconds'] = round(monotonic() - synthesis, 3)
                    chunks.append(chunk)
                result['synthesis_seconds'] = round(monotonic() - synthesis, 3)
            result['pcm_bytes'] = sum(len(chunk.pcm) for chunk in chunks)
            result['nonzero_pcm'] = any(any(chunk.pcm) for chunk in chunks)
            result['sample_rate'] = chunks[0].format.sample_rate
            runtime = service.state_dir / 'runtime_status.json'
            if runtime.is_file():
                result['runtime'] = json.loads(runtime.read_text(encoding='utf-8'))
        asyncio.run(check())
        result['ok'] = (result['pcm_bytes'] > 0 and result['nonzero_pcm']
                        and result['reply_length_range'] == [0, 2000] and result['preview_aspect_ratio'] < .70)
    except Exception as error:
        result.update(ok=False, error=f'{type(error).__name__}: {error}')
    finally:
        process = service.process
        asyncio.run(service.close())
        result['owned_service_stopped'] = process is None or process.poll() is not None
        result['seconds'] = round(monotonic() - started, 1)
        if panel:
            panel.close()
        if pet:
            pet.shutdown()
        app.processEvents()
        Path(destination).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result.get('ok') and result['owned_service_stopped'] else 1
