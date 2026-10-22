"""GPT-SoVITS流式WAV解码；兼容本地服务data长度为0的流式头。"""
import struct
import logging
from dataclasses import replace
import aiohttp

from config import REF_MAP, Settings
from app.core.models import AudioChunk, AudioFormat, StageError


class WaveStreamDecoder:
    def __init__(self, frame_ms=20, max_seconds=45):
        self.frame_ms = frame_ms
        self.max_seconds = max_seconds
        self.pending = bytearray()
        self.pcm = bytearray()
        self.format = None
        self.riff_seen = False
        self.data_seen = False
        self.header_bytes = 0
        self.total_pcm = 0

    def feed(self, data):
        if not self.data_seen:
            self.pending.extend(data)
            if not self.riff_seen:
                if len(self.pending) < 12:
                    return []
                if self.pending[:4] != b"RIFF" or self.pending[8:12] != b"WAVE":
                    raise StageError("TTS", "响应不是RIFF/WAVE音频，请检查本地TTS服务")
                del self.pending[:12]
                self.header_bytes = 12
                self.riff_seen = True
            while not self.data_seen:
                if len(self.pending) < 8:
                    return []
                kind, size = struct.unpack_from("<4sI", self.pending)
                if kind == b"data":
                    if self.format is None:
                        raise StageError("TTS", "WAV缺少音频格式信息")
                    del self.pending[:8]
                    self.data_seen = True
                    break
                length = 8 + size + size % 2
                if self.header_bytes + length > 16384:
                    raise StageError("TTS", "WAV头超过16KiB上限")
                if len(self.pending) < length:
                    return []
                if kind == b"fmt ":
                    if size < 16:
                        raise StageError("TTS", "WAV格式头不完整")
                    encoding, channels, rate, byte_rate, alignment, bits = struct.unpack_from("<HHIIHH", self.pending, 8)
                    if (encoding != 1 or bits != 16 or channels not in (1, 2)
                            or not 8000 <= rate <= 192000 or alignment != channels * 2
                            or byte_rate != rate * alignment):
                        raise StageError("TTS", "只接受8000到192000Hz的16位PCM单/双声道WAV")
                    self.format = AudioFormat(rate, channels, 2)
                del self.pending[:length]
                self.header_bytes += length
            data = bytes(self.pending)
            self.pending.clear()
        self.total_pcm += len(data)
        if self.total_pcm > self.format.bytes_per_second * self.max_seconds:
            raise StageError("TTS", "合成音频超过时长上限，已停止本轮")
        self.pcm.extend(data)
        block_size = self.format.sample_rate * self.frame_ms // 1000 * self.format.channels * 2
        chunks = []
        while len(self.pcm) >= block_size:
            chunks.append(AudioChunk(bytes(self.pcm[:block_size]), self.format))
            del self.pcm[:block_size]
        return chunks

    def finish(self):
        if not self.data_seen or not self.total_pcm:
            raise StageError("TTS", "服务没有返回有效音频")
        if len(self.pcm) % (self.format.channels * 2):
            raise StageError("TTS", "音频在采样帧中途截断")
        chunks = [AudioChunk(bytes(self.pcm), self.format)] if self.pcm else []
        self.pcm.clear()
        return chunks


class TTSClient:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings, options=None):
        self.session = session
        self.settings = settings
        self.options = options

    async def stream(self, part, language='ja'):
        reference_name = part.voice_expression or part.expression
        if part.audio_reference is not None:
            reference, prompt = part.audio_reference.path, part.audio_reference.prompt
        elif reference_name not in REF_MAP:
            reference_name = '平常' if '平常' in REF_MAP else self.settings.default_expression
            if reference_name not in REF_MAP:
                raise StageError('TTS', '缺少默认TTS参考音频，请检查config.py中的REF_MAP')
            logging.getLogger('tachitalk').warning('语音情绪%s没有对应TTS参考音频，使用%s参考；本句立绘仍按%s显示',
                                                  part.voice_expression or part.expression, reference_name, part.expression)
        if part.audio_reference is None:
            reference, prompt = REF_MAP[reference_name]
        mode = self.settings.tts_streaming_mode
        payload = {
            "text": part.japanese, "text_lang": language,
            "prompt_lang": part.audio_reference.language if part.audio_reference is not None else "ja",
            "ref_audio_path": reference, "prompt_text": prompt,
            "streaming_mode": mode, "media_type": "wav",
            "parallel_infer": mode == 1, "split_bucket": False,
            "text_split_method": "cut5", "batch_size": 1,
        }
        decoder = WaveStreamDecoder(self.settings.frame_ms, self.settings.max_tts_seconds)
        try:
            headers = {'Authorization': f'Bearer {self.options.api_key}'} if self.options is not None and self.options.api_key else {}
            async with self.session.post(self.options.url if self.options is not None else self.settings.tts_url,
                                         json=payload, headers=headers, allow_redirects=False,
                                         timeout=aiohttp.ClientTimeout(total=self.options.timeout) if self.options is not None else self.session.timeout) as response:
                if response.status != 200:
                    raise StageError.http("TTS", response.status)
                async for block in response.content.iter_chunked(4096):
                    for chunk in decoder.feed(block):
                        yield replace(chunk, part_id=part.part_id, expression=part.expression)
                for chunk in decoder.finish():
                    yield replace(chunk, part_id=part.part_id, expression=part.expression)
        except StageError:
            raise
        except (aiohttp.ClientError, TimeoutError) as error:
            from app.paths import DATA_ROOT
            raise StageError("TTS", f"语音合成连接失败或等待超时（{type(error).__name__}）；请检查语音与音频页的合成地址、"
                             f"输出设备，并查看后台日志 {DATA_ROOT / 'tts/service.log'}。GPU自检不通过时程序会使用CPU兼容模式") from error
