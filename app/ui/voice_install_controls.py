"""Detect completed local voice installations and enable replies once per install."""
from dataclasses import replace
import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from app.core import components
from app.paths import TTS_SERVICE_DIR
from app.services.local_tts import LocalTTSService
from app.updates.install import InstallLock, InstallBusyError
from app.updates.manifest import atomic_json

LOG = logging.getLogger('tachitalk.voice')


class VoiceInstallControls(QObject):
    def __init__(self, panel, service_root=TTS_SERVICE_DIR):
        super().__init__(panel)
        self.panel = panel
        self.service_root = Path(service_root)
        self.record = panel.session_controls.file.path.with_name('voice-component.json')
        self.previous = None
        self.activated_generation = None
        self.saved_generation = None
        self.read_error = False
        if self.record.exists():
            try:
                if self.record.stat().st_size > 16384:
                    raise ValueError('语音安装状态文件过大')
                previous = json.loads(self.record.read_text(encoding='utf-8'))
                if (not isinstance(previous, dict) or set(previous) != {'installed', 'generation'}
                        or type(previous['installed']) is not bool
                        or not isinstance(previous['generation'], str)):
                    raise ValueError('语音安装状态格式不正确')
                self.previous = previous
            except (OSError, ValueError, RecursionError) as error:
                self.read_error = True
                LOG.error('语音安装状态无法读取，保留现有朗读选择（%s）', type(error).__name__)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        panel.closing.connect(self.timer.stop)
        self.timer.start()

    def installation_active(self):
        installation = self.service_root.parent.parent
        if (installation / '.tachitalk-pending.json').exists():
            return True
        if (installation / '.tachitalk-update.lock').exists():
            try:
                with InstallLock(installation):
                    pass
            except InstallBusyError:
                return True
        return False

    def refresh(self):
        if self.panel._closing:
            return
        try:
            if self.installation_active():
                return
            status = components.voice_status(self.service_root)
            record = self.service_root / 'component-version.json'
            generation = (f"{status['version']}:{record.stat().st_mtime_ns if record.is_file() else 'legacy'}"
                          if status['installed'] else '')
            current = {'installed': status['installed'], 'generation': generation}
            controls = self.panel.voice_controls
            components.prepare_optional_voice(controls.voices, self.service_root)
            controls.apply_preferences()
            if not current['installed']:
                self.activated_generation = None
                self.saved_generation = None
            if self.read_error or current == self.previous:
                return
            newly_installed = current['installed'] and (
                self.previous is None or not self.previous['installed']
                or current['generation'] != self.previous['generation'])
            if newly_installed and generation != self.saved_generation:
                options = controls._tts_cache['gpt_sovits']
                # Installation is a one-time preference change, not proof that
                # inference is ready. The existing service monitor still loads
                # models and reports transport/playback failures independently.
                if LocalTTSService.local_port(options) is not None:
                    if generation != self.activated_generation:
                        options = replace(options, auto_read=True)
                        controls._tts_cache['gpt_sovits'] = options
                        if controls._tts_provider == 'gpt_sovits':
                            controls.fill_tts(options)
                            controls.save_tts()
                        self.activated_generation = generation
                    if not self.panel.session_controls.save():
                        return  # Retry on next startup; never consume an unsaved activation.
                    # A marker write can fail after the session was saved. Retry
                    # that write without overwriting a subsequent user choice.
                    self.saved_generation = generation
                    LOG.info('已检测到本地语音安装完成，已保存朗读选择；模型就绪由后台继续检查')
            atomic_json(self.record, current)
            self.previous = current
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            LOG.error('语音安装检测失败，未伪造组件或模型就绪（%s）：%s', type(error).__name__, error)
