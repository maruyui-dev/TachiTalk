"""已选ASR/TTS适配：共享HTTP连接，本地模型和系统音色进程常驻复用。"""
from dataclasses import replace
from contextlib import aclosing
import re

import aiohttp

from app.core.models import StageError
from app.services.asr import ASRClient
from app.services.local_whisper import LocalWhisper
from app.services.system_speech import SystemSpeech
from app.services.tts import TTSClient, WaveStreamDecoder


def preview_language(text):
    if re.search(r'[\u3040-\u30ff]', text):
        return 'ja'
    if re.search(r'[\u3400-\u9fff]', text):
        return 'zh'
    return 'en'


class SpeechServices:
    def __init__(self, session, settings, voices):
        self.session, self.settings, self.voices = session, settings, voices
        self.whisper = LocalWhisper()
        self.system = SystemSpeech()

    async def transcribe(self, segment, options=None):
        options = options or self.voices.snapshot().asr
        options.validate()
        if options.provider == 'whisper':
            return await self.whisper.transcribe(segment, options)
        return await ASRClient(self.session, self.settings, options).transcribe(segment)

    async def stream(self, part, options=None, language='ja'):
        options = options or self.voices.snapshot().tts
        options.validate()
        if options.provider == 'gpt_sovits':
            service = getattr(self.voices, 'local_service', None)
            if service is not None:
                await service.ensure(options)
            async with aclosing(TTSClient(self.session, self.settings, options).stream(part, language)) as stream:
                async for chunk in stream:
                    yield chunk
            return
        decoder = WaveStreamDecoder(self.settings.frame_ms, self.settings.max_tts_seconds)
        if options.provider == 'system':
            data = await self.system.audio(part.japanese, options, 24000 * 2 * self.settings.max_tts_seconds + 16384)
            for index in range(0, len(data), 4096):
                for chunk in decoder.feed(data[index:index + 4096]):
                    yield replace(chunk, part_id=part.part_id, expression=part.expression)
        else:
            headers = {'Authorization': f'Bearer {options.api_key}'} if options.api_key else {}
            payload = {'model': options.model, 'input': part.japanese, 'voice': options.voice, 'response_format': 'wav'}
            try:
                async with self.session.post(options.url, headers=headers, json=payload, allow_redirects=False,
                                             timeout=aiohttp.ClientTimeout(total=options.timeout)) as response:
                    if response.status != 200:
                        raise StageError.http('TTS', response.status)
                    async for block in response.content.iter_chunked(4096):
                        for chunk in decoder.feed(block):
                            yield replace(chunk, part_id=part.part_id, expression=part.expression)
            except (aiohttp.ClientError, TimeoutError) as error:
                raise StageError('TTS', f'合成服务连接失败或超时（{type(error).__name__}），请检查所选服务地址和Key') from error
        for chunk in decoder.finish():
            yield replace(chunk, part_id=part.part_id, expression=part.expression)

    async def close(self):
        await self.whisper.close()
        await self.system.close()
