"""本地TTS生命周期：隐藏启动、确认模型加载完成、只关闭自己拥有的服务。"""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
from time import monotonic
from urllib.parse import urlsplit

import aiohttp

from app.paths import DATA_ROOT, PROJECT_ROOT, TTS_SERVICE_DIR
from app.services.owned_process import spawn_hidden
from scripts.start_tts import check_files, service_environment


class LocalTTSService:
    def __init__(self, ui, root=TTS_SERVICE_DIR, state_dir=None, startup_timeout=300):
        self.ui, self.root = ui, Path(root)
        self.state_dir = Path(state_dir) if state_dir is not None else DATA_ROOT / 'tts'
        self.startup_timeout = startup_timeout
        self.process = self.job = self.log = None
        self.endpoint = None
        self.lock = asyncio.Lock()
        self.ready = False
        self.model_signature = None
        self.suspended = False
        self.loop = None

    def configuration_signature(self):
        record = self.state_dir.parent / 'settings/active_voice_model.json'
        try:
            status = record.stat()
            return status.st_mtime_ns, status.st_size
        except FileNotFoundError:
            return None

    async def suspend(self):
        self.suspended = True
        try:
            async with self.lock:
                await self.close()
        except BaseException:
            self.suspended = False
            raise

    @staticmethod
    def local_port(options):
        parsed = urlsplit(options.url)
        if (options.provider == 'gpt_sovits' and parsed.scheme == 'http'
                and parsed.hostname in ('127.0.0.1', 'localhost') and parsed.path.rstrip('/') == '/tts'):
            return parsed.port or 80
        return None

    async def probe(self, url):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1)) as session:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status != 200:
                        return False
                    body = await response.content.read(1024 * 1024 + 1)
                    if len(body) > 1024 * 1024:
                        return False
                    data = json.loads(body)
                    return isinstance(data, dict) and 'post' in data.get('paths', {}).get('/tts', {})
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
            return False

    def port_in_use(self, port):
        with socket.socket() as probe:
            probe.settimeout(.3)
            return probe.connect_ex(('127.0.0.1', port)) == 0

    def launch(self, port):
        missing = check_files(self.root)
        if missing:
            raise ValueError('本地GPT-SoVITS文件不完整：' + '; '.join(missing[:4]))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / 'runtime_status.json').unlink(missing_ok=True)
        log_path = self.state_dir / 'service.log'
        if log_path.exists() and log_path.stat().st_size > 2 * 1024 * 1024:
            log_path.replace(self.state_dir / 'service.previous.log')
        self.log = log_path.open('ab', buffering=0)
        env = service_environment(self.root)
        for name in ('TEMP', 'TMP', 'HF_HOME', 'NUMBA_CACHE_DIR', 'MPLCONFIGDIR', 'TORCH_HOME'):
            path = self.state_dir / name.lower()
            path.mkdir(exist_ok=True)
            env[name] = str(path)
        command = [str(self.root / 'runtime/python.exe'), '-u', '-B',
                   str(PROJECT_ROOT / 'scripts/tts_service_entry.py'), '--service-root', str(self.root),
                   '--state-dir', str(self.state_dir), '--port', str(port)]
        record = self.state_dir.parent / 'settings/active_voice_model.json'
        if record.is_file():
            command += ['--model-record', str(record)]
        try:
            self.process, self.job = spawn_hidden(command, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                                  stdout=self.log, stderr=subprocess.STDOUT)
        except Exception:
            self.log.close()
            self.log = None
            raise

    async def ensure(self, options):
        self.loop = asyncio.get_running_loop()
        port = self.local_port(options)
        if port is None:
            return
        url = f'http://127.0.0.1:{port}/openapi.json'
        async with self.lock:
            if self.suspended:
                raise ValueError('模型训练 / 试听正在使用本地环境，完成后自动恢复桌宠朗读')
            signature = self.configuration_signature()
            if self.model_signature != signature:
                await self.close()
                self.model_signature = signature
            if self.endpoint != url:
                await self.close()
                self.endpoint = url
            if self.ready and (self.process is None or self.process.poll() is None):
                return
            self.ready = False
            if self.process is not None and self.process.poll() is not None:
                code = self.process.returncode
                await self.close()
                raise RuntimeError(f'GPT-SoVITS后台已退出（{code}），请查看 {self.state_dir / "service.log"}')
            if self.process is None:
                if await self.probe(url):
                    self.ready = True
                    self.ui.info('检测到已有GPT-SoVITS，复用服务；退出时不会关闭它')
                    return
                if self.port_in_use(port):
                    raise ValueError(f'TTS端口{port}被其他或尚未就绪的服务占用，未启动或关闭任何现有进程')
                self.ui.status('正在后台启动GPT-SoVITS并加载模型，请稍候')
                launch_task = asyncio.create_task(asyncio.to_thread(self.launch, port))
                try:
                    await asyncio.shield(launch_task)
                except asyncio.CancelledError:
                    await launch_task
                    await self.close()
                    raise
            deadline = monotonic() + self.startup_timeout
            while monotonic() < deadline:
                if self.process.poll() is not None:
                    code = self.process.returncode
                    await self.close()
                    raise RuntimeError(f'GPT-SoVITS启动失败（{code}），请查看 {self.state_dir / "service.log"}')
                if await self.probe(url):
                    self.ready = True
                    self.report_runtime()
                    self.ui.info('GPT-SoVITS后台模型加载完成，语音合成已就绪')
                    return
                await asyncio.sleep(.5)
            await self.close()
            raise RuntimeError(f'GPT-SoVITS启动等待超时，请查看 {self.state_dir / "service.log"}')

    def report_runtime(self):
        path = self.state_dir / 'runtime_status.json'
        try:
            if path.stat().st_size > 16384:
                return
            runtime = json.loads(path.read_text(encoding='utf-8'))
            if runtime.get('device') == 'cpu':
                self.ui.info('TTS兼容提示：正在使用CPU，合成速度取决于处理器。' + str(runtime.get('reason', ''))[:400])
            elif runtime.get('device') == 'cuda':
                self.ui.info('TTS GPU自检通过：' + str(runtime.get('gpu', ''))[:100])
        except (OSError, ValueError, AttributeError):
            return  # 外部服务和旧启动器可能不提供设备报告。

    async def close(self):
        self.ready = False
        process, job = self.process, self.job
        self.process = self.job = None
        if job:
            job.close()
        if process:
            if not job and process.poll() is None:
                process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=3)
        if self.log:
            self.log.close()
            self.log = None
