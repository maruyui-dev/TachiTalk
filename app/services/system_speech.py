"""Windows已安装音色合成WAV，仍由统一AudioPlayer选择扬声器和控制音量。"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from app.core.models import StageError


class SystemSpeech:
    def __init__(self):
        self.process = None
        self.stderr_task = None
        self.lock = asyncio.Lock()

    async def _drain(self, process):
        while await process.stderr.read(4096):
            pass

    async def request(self, payload, timeout=60):
        if sys.platform != 'win32':
            raise StageError('TTS', '当前系统语音适配Windows，请选择其他TTS服务')
        async with self.lock:
            try:
                async with asyncio.timeout(timeout):
                    if self.process is None or self.process.returncode is not None:
                        if self.stderr_task is not None:
                            await self.stderr_task
                        self.process = await asyncio.create_subprocess_exec(
                            'powershell.exe', '-NoProfile', '-NonInteractive',
                            '-Command', Path(__file__).with_suffix('.ps1').read_text(encoding='utf-8'),
                            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
                        self.stderr_task = asyncio.create_task(self._drain(self.process))
                    # 用户文字只作为JSON数据传入，不插入PowerShell代码。
                    self.process.stdin.write(json.dumps(payload, ensure_ascii=True).encode() + b'\n')
                    await self.process.stdin.drain()
                    line = await self.process.stdout.readline()
                    if not line:
                        raise StageError('TTS', '系统语音进程退出，请检查Windows语音组件和已安装的语音包')
                    result = json.loads(line.decode('utf-8-sig'))
                    if result.get('error'):
                        raise StageError('TTS', f"系统语音：{str(result['error'])[:300]}；请检查所选音色或安装对应语言的语音包")
                    return result
            except (asyncio.CancelledError, TimeoutError):
                await self.close()
                raise

    async def voices(self):
        return (await self.request({'operation': 'voices'})).get('voices', [])

    async def audio(self, text, options, max_bytes):
        with TemporaryDirectory(prefix='tachitalk-system-speech-') as folder:
            path = Path(folder) / 'speech.wav'
            await self.request({'operation': 'speak', 'text': text, 'voice': options.voice, 'output': str(path)}, options.timeout)
            if not path.is_file() or path.stat().st_size > max_bytes:
                raise StageError('TTS', '系统合成未返回音频或超过时长上限')
            return await asyncio.to_thread(path.read_bytes)

    async def close(self):
        if self.process is not None and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()
        if self.stderr_task is not None:
            await self.stderr_task
        self.process = self.stderr_task = None
