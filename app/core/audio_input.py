"""录音运行设置及跨线程快照；不操作音频驱动。"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecordingOptions:
    device: int | None = None
    sample_rate: int = 16000
    volume: int = 77
    mode: str = 'vad'
    device_name: str = ''
    trim_silence: bool = True

    def validate(self):
        if self.sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError('VAD采样率必须为8000、16000、32000或48000 Hz')
        if not 0 <= self.volume <= 100 or self.mode not in ('vad', 'hold', 'toggle'):
            raise ValueError('录音方式或输入音量不正确')


@dataclass(frozen=True, slots=True)
class InputDevice:
    index: int
    name: str
    host_api: str

    @property
    def label(self):
        return f'{self.name} · {self.host_api} [#{self.index}]'


@dataclass(frozen=True, slots=True)
class CaptureState:
    enabled: bool
    revision: int
    options: RecordingOptions
    testing: bool
    manual_active: bool
    manual_token: int


@dataclass(frozen=True, slots=True)
class AudioStatus:
    state: CaptureState
    capture_active: bool
    level: int
    test_peak: int
    test_frames: int
    error: str
    devices: tuple[InputDevice, ...]
    scanning: bool
    scan_version: int
    scan_error: str

