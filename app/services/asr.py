"""SiliconFlow及兼容文件转录接口：内存WAV、复用Session、校验有效文字。"""
import json
import unicodedata

import aiohttp

from config import Settings, get_api_key
from app.core.models import AudioSegment, StageError


def validated_text(text):
    if not isinstance(text, str):
        raise StageError('ASR', '识别响应缺少字符串类型的text字段')
    text = text.strip()
    if len(text) > 5000:
        raise StageError('ASR', '识别文字超过5000字符上限')
    # 保留“嗯”“好”等单字，过滤只有空白或标点的结果。
    return text if any(unicodedata.category(c)[0] in 'LN' for c in text) else ''


class ASRClient:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings, options=None):
        self.session = session
        self.settings = settings
        self.options = options
        if options is not None:
            options.validate()
        self.key = options.api_key if options is not None else get_api_key("asr")

    async def transcribe(self, segment: AudioSegment) -> str:
        data = aiohttp.FormData()
        data.add_field("model", self.options.model if self.options is not None else self.settings.asr_model)
        if self.options is not None and self.options.provider != 'silicon' and self.options.language != 'auto':
            data.add_field('language', self.options.language)
        data.add_field("file", segment.to_wav(), filename="speech.wav", content_type="audio/wav")
        try:
            async with self.session.post(self.options.url if self.options is not None else self.settings.asr_url,
                                         headers={"Authorization": f"Bearer {self.key}"} if self.key else {}, data=data,
                                         allow_redirects=False,
                                         timeout=aiohttp.ClientTimeout(total=self.options.timeout) if self.options is not None else self.session.timeout) as response:
                if response.status != 200:
                    raise StageError.http("ASR", response.status)
                body = bytearray()
                async for block in response.content.iter_chunked(4096):
                    body.extend(block)
                    if len(body) > 65536:
                        raise StageError("ASR", "识别响应超过64KiB上限")
                result = json.loads(body)
                text = result.get("text") if isinstance(result, dict) else None
                return validated_text(text)
        except StageError:
            raise
        except (aiohttp.ClientError, TimeoutError) as error:
            raise StageError("ASR", f"网络连接失败或超时（{type(error).__name__}）") from error
        except (ValueError, UnicodeError) as error:
            raise StageError("ASR", "服务返回了无法解析的JSON") from error
