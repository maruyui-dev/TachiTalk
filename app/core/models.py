"""各模块之间传递的数据；不操作设备、不发起网络请求。"""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING
import wave

if TYPE_CHECKING:
    from app.core.audio_library import AudioReference


class StageError(Exception):
    """可展示给用户的环节错误；status 用于区别鉴权、限流和网络故障。"""

    def __init__(self, stage: str, message: str, status: int | None = None):
        super().__init__(message)
        self.stage = stage
        self.status = status

    @classmethod
    def http(cls, stage: str, status: int):
        descriptions = {
            400: "请求参数不正确，请检查模型与接口配置",
            401: "鉴权失败，Key无效、过期或不属于该服务",
            402: "账户余额不足，请在服务控制台检查余额",
            403: "服务拒绝访问，请检查Key权限、模型权限或账户状态",
            404: "接口或模型不存在，请检查地址和模型名",
            422: "请求字段不被服务支持，请检查配置",
            429: "服务限流，本轮停止；稍后再试",
        }
        return cls(stage, descriptions.get(status, "服务请求失败，请检查服务状态"), status)


@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate: int
    channels: int = 1
    sample_width: int = 2

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * self.sample_width


@dataclass(frozen=True, slots=True)
class AudioSegment:
    pcm: bytes
    format: AudioFormat
    last_speech_at: float
    reason: str = "silence"

    @property
    def duration(self) -> float:
        return len(self.pcm) / self.format.bytes_per_second

    def to_wav(self) -> bytes:
        buffer = BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(self.format.channels)
            output.setsampwidth(self.format.sample_width)
            output.setframerate(self.format.sample_rate)
            output.writeframes(self.pcm)
        return buffer.getvalue()


@dataclass(frozen=True, slots=True)
class SpeechPart:
    part_id: int
    japanese: str
    expression: str
    voice_expression: str | None = None  # 调度层锁定整轮语音参考；expression仍控制本句立绘。
    audio_reference: AudioReference | None = None  # 不可变参考；不再用立绘名查找可编辑音频。


@dataclass(frozen=True, slots=True)
class CaptionPart:
    part_id: int
    chinese: str  # 兼容既有流式协议：内容为用户所选语言的气泡文本。


@dataclass(frozen=True, slots=True)
class AudioChunk:
    pcm: bytes
    format: AudioFormat
    part_id: int | None = None
    expression: str | None = None
