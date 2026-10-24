"""语音服务的运行配置与有界命令槽；Key只在Python对象中读取和保存。"""
from dataclasses import dataclass, field, replace
from threading import Lock
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import config

if TYPE_CHECKING:
    from app.core.audio_library import AudioReference


def http_url(value, label):
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f'{label}必须是有效HTTP/HTTPS地址，Key请填写到独立输入框')
    return value


@dataclass(frozen=True, slots=True)
class ASROptions:
    provider: str = 'silicon'
    url: str = ''
    models_url: str = ''
    api_key: str = field(default='', repr=False)
    require_key: bool = True
    model: str = ''
    language: str = 'auto'
    auto_send: bool = True
    trim_silence: bool = True
    timeout: int = 60
    local_path: str = ''
    allow_download: bool = False

    def validate(self, for_models=False):
        if self.provider == 'whisper':
            if not (self.model or self.local_path):
                raise ValueError('请选择Whisper模型或填写本地模型目录')
            return
        http_url(self.models_url if for_models else self.url, '模型列表地址' if for_models else 'ASR请求地址')
        if self.require_key and not self.api_key.strip():
            guide = ('请到 https://cloud.siliconflow.cn/account/ak 创建Key，填写本页API Key，'
                     '。' if self.provider == 'silicon'
                     else '请到 https://platform.openai.com/api-keys 点击Create new secret key，填写本页API Key。'
                     if self.provider == 'openai' else '请到所用服务提供商的控制台创建Key，填写本页ASR API Key；无鉴权自建服务可关闭需要Key。')
            raise ValueError('ASR缺少API Key，用于上传音频和获取识别模型。' + guide)
        if not for_models and not self.model.strip():
            raise ValueError('ASR模型为空，请先获取或填写服务支持的识别模型')
        if self.language not in ('auto', 'zh', 'en', 'ja'):
            raise ValueError('识别语言不支持')


@dataclass(frozen=True, slots=True)
class TTSOptions:
    provider: str = 'gpt_sovits'
    url: str = ''
    api_key: str = field(default='', repr=False)
    require_key: bool = False
    model: str = ''
    voice: str = ''
    auto_read: bool = True
    interrupt: bool = False
    timeout: int = 60

    def validate(self):
        if self.provider == 'system':
            if not self.voice:
                raise ValueError('请选择已安装的系统音色；日语回复建议安装并选择日语语音包')
            return
        http_url(self.url, 'TTS请求地址')
        if self.require_key and not self.api_key.strip():
            guide = ('https://platform.openai.com/api-keys → Create new secret key'
                     if self.provider == 'openai' else '所选服务提供商的控制台')
            raise ValueError(f'TTS缺少API Key，用于语音合成。请到{guide}创建，填写本页TTS API Key')
        if self.provider != 'gpt_sovits' and not (self.model.strip() and self.voice.strip()):
            raise ValueError('请填写TTS服务的模型名和音色ID，具体值以该服务文档为准')


def default_voice_profiles(settings):
    asr = {
        'silicon': ASROptions(url=settings.asr_url, models_url=settings.asr_url.rsplit('/audio/', 1)[0] + '/models',
                              model=settings.asr_model),
        'openai': ASROptions(provider='openai', url='https://api.openai.com/v1/audio/transcriptions',
                             models_url='https://api.openai.com/v1/models'),
        'whisper': ASROptions(provider='whisper', model='small', require_key=False),
        'custom': ASROptions(provider='custom'),
    }
    tts = {
        'gpt_sovits': TTSOptions(url=settings.tts_url),
        'system': TTSOptions(provider='system'),
        'openai': TTSOptions(provider='openai', url='https://api.openai.com/v1/audio/speech', require_key=True,
                             api_key=''),
        'custom': TTSOptions(provider='custom', require_key=True),
    }
    return asr, tts


@dataclass(frozen=True, slots=True)
class OutputOptions:
    device: int | None = None
    volume: int = 80


@dataclass(frozen=True, slots=True)
class VoiceSnapshot:
    asr: ASROptions
    tts: TTSOptions
    output: OutputOptions
    asr_revision: int
    tts_revision: int


@dataclass(frozen=True, slots=True)
class Command:
    id: int
    payload: object = None


@dataclass(frozen=True, slots=True)
class ReferencePreview:
    reference: 'AudioReference'
    raw: bool = False
    text: str = '今日はいい天気ですね。少し休みましょう。'


@dataclass(frozen=True, slots=True)
class CommandResult:
    id: int = 0
    value: object = None
    error: str = ''
    running: bool = False


class VoiceSettings:
    COMMANDS = ('models', 'speakers', 'preview', 'voices')

    def __init__(self, settings):
        self._lock = Lock()
        self._asr = ASROptions(url=settings.asr_url, models_url=settings.asr_url.rsplit('/audio/', 1)[0] + '/models',
                               model=settings.asr_model)
        self._tts = TTSOptions(url=settings.tts_url)
        self._unavailable_tts = None
        self._output = OutputOptions(device=settings.output_device)
        self._asr_revision = self._tts_revision = self._serial = 0
        self._commands = {}
        self._results = {name: CommandResult() for name in self.COMMANDS}
        self._draft = ('', 0)

    def snapshot(self):
        with self._lock:
            tts = self._tts
            # Component availability is temporary; keep the user's preference in
            # the UI/profiles so installing voice does not persist text-only mode.
            if self._unavailable_tts == (tts.provider, tts.url):
                tts = replace(tts, auto_read=False)
            return VoiceSnapshot(self._asr, tts, self._output, self._asr_revision, self._tts_revision)

    def set_local_voice_available(self, available):
        with self._lock:
            unavailable = None if available else (self._tts.provider, self._tts.url)
            if self._unavailable_tts != unavailable:
                self._unavailable_tts = unavailable
                self._tts_revision += 1

    def set_asr(self, options):
        config.register_runtime_key(options.api_key)
        with self._lock:
            if options != self._asr:
                transport_changed = replace(options, auto_send=self._asr.auto_send,
                                            trim_silence=self._asr.trim_silence,
                                            language=self._asr.language) != self._asr
                self._asr = options
                self._asr_revision += int(transport_changed)

    def set_tts(self, options):
        config.register_runtime_key(options.api_key)
        with self._lock:
            if options != self._tts:
                transport_changed = replace(options, auto_read=self._tts.auto_read,
                                            interrupt=self._tts.interrupt) != self._tts
                self._tts = options
                self._tts_revision += int(transport_changed)

    def set_output(self, **changes):
        with self._lock:
            options = replace(self._output, **changes)
            if not 0 <= options.volume <= 100:
                raise ValueError('播放音量必须为0到100')
            self._output = options

    def request(self, name, payload=None):
        if name not in self.COMMANDS:
            raise ValueError('未知语音服务操作')
        with self._lock:
            self._serial += 1
            self._commands[name] = Command(self._serial, payload)
            self._results[name] = CommandResult(self._serial, running=True)
            return self._serial

    def commands(self):
        with self._lock:
            return dict(self._commands)

    def discard_commands(self, *names):
        """载入配置时作废旧模型/音色列表，迟到的响应不能覆盖新选择。"""
        with self._lock:
            for name in names:
                self._commands.pop(name, None)
                self._results[name] = CommandResult()

    def complete(self, name, id, value=None, error=''):
        with self._lock:
            if self._commands.get(name, Command(0)).id == id:
                self._results[name] = CommandResult(id, value, config.redact(error))

    def result(self, name):
        with self._lock:
            return self._results[name]

    def set_draft(self, text):
        with self._lock:
            self._draft = (text, self._draft[1] + 1)

    def draft(self):
        with self._lock:
            return self._draft
