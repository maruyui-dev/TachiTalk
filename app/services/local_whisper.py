"""本地Whisper进程适配；取消、超时和退出会终止子进程。"""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import sys

from app.core.models import StageError
from app.services.asr import validated_text
from app.paths import FROZEN, PROJECT_ROOT, TTS_SERVICE_DIR


class LocalWhisper:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()
        self.stderr_task = None

    async def _start(self):
        if self.process is None or self.process.returncode is not None:
            if self.stderr_task is not None:
                await self.stderr_task
            command = ([str(TTS_SERVICE_DIR / 'runtime/python.exe'), '-u', '-B', str(PROJECT_ROOT / 'scripts/whisper_worker.py')]
                       if FROZEN else [sys.executable, '-u', '-B', '-m', 'app.services.whisper_worker'])
            self.process = await asyncio.create_subprocess_exec(
                *command, cwd=str(PROJECT_ROOT), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=65536,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            self.stderr_task = asyncio.create_task(self._drain_stderr(self.process))

    async def _drain_stderr(self, process):
        while await process.stderr.read(4096):
            pass  # 下载进度不进入协议；错误由worker以有界JSON返回。

    async def request(self, payload, timeout=60):
        async with self.lock:
            try:
                async with asyncio.timeout(timeout):
                    await self._start()
                    self.process.stdin.write(json.dumps(payload).encode() + b'\n')
                    await self.process.stdin.drain()
                    line = await self.process.stdout.readline()
                    if not line:
                        raise StageError('ASR', '本地Whisper进程意外结束，请检查依赖和模型')
                    result = json.loads(line)
                    if result.get('error'):
                        raise StageError('ASR', result['error'])
                    return result
            except (asyncio.CancelledError, TimeoutError):
                await self.close()
                raise

    async def transcribe(self, segment, options):
        options.validate()
        try:
            result = await self.request({'operation': 'transcribe', 'model': options.model, 'path': options.local_path,
                                         'download': options.allow_download, 'language': None if options.language == 'auto' else options.language,
                                         'wav': base64.b64encode(segment.to_wav()).decode()}, options.timeout)
            return validated_text(result.get('text'))
        except TimeoutError as error:
            raise StageError('ASR', '本地Whisper识别超时，已终止进程；可换较小模型或增加超时') from error

    async def close(self):
        if self.process is not None and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()
        if self.stderr_task is not None:
            await self.stderr_task
        self.process = self.stderr_task = None
