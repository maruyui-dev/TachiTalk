"""启动入口。常驻模式仅在手动Ctrl+C/终止信号时结束。"""
import argparse
import asyncio
import logging
import signal
import sys
from dataclasses import replace

import aiohttp

from config import REF_MAP, Settings, startup_configuration_errors
from app.core.models import StageError
from app.core.pipeline import check_services, run_application, wait_for_manual_restart
from app.ui.console import ConsoleUI


async def run(settings, ui, check_only=False):
    task = asyncio.current_task()
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: task.cancel())
    if check_only:
        errors = startup_configuration_errors(settings)
        for message in errors:
            ui.error(message)
        if errors:
            return 1
        timeout = aiohttp.ClientTimeout(total=settings.request_timeout, connect=settings.connect_timeout,
                                        sock_read=settings.read_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            results = await check_services(session, settings)
        for name, result in results.items():
            if result is None:
                ui.info(f"{name}检查通过")
            else:
                ui.error(result)
        return int(any(result is not None for result in results.values()))
    while True:
        try:
            await run_application(settings, ui)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            ui.error(f"运行资源发生错误（{type(error).__name__}），{settings.retry_delay}秒后重建运行链路")
            await asyncio.sleep(settings.retry_delay)


def main():
    from time import time
    started_at = time()
    from app.paths import PROJECT_ROOT, DATA_ROOT
    from app.updates.install import InstallLock, InstallBusyError
    from app.updates.cleanup import needs_cleanup
    try:
        # A journal also exists during a healthy installation. Check ownership
        # first; a second launch must never compete with that live transaction.
        if (PROJECT_ROOT / '.tachitalk-update.lock').exists():
            with InstallLock(PROJECT_ROOT):
                pass
        if (PROJECT_ROOT / '.tachitalk-pending.json').exists() or needs_cleanup(PROJECT_ROOT):
            import subprocess
            import shutil
            import os
            import uuid
            directory = DATA_ROOT / 'updates/updaters'
            directory.mkdir(parents=True, exist_ok=True)
            if getattr(sys, 'frozen', False):
                updater = directory / f'{uuid.uuid4().hex}.exe'
                shutil.copy2(PROJECT_ROOT / 'TachiTalkUpdater.exe', updater)
                command = [str(updater)]
            else:
                command = [sys.executable, str(PROJECT_ROOT / 'scripts/update_entry.py')]
            command += ['--root', str(PROJECT_ROOT), '--recover', '--parent-pid', str(os.getpid()),
                        '--result', str(DATA_ROOT / 'updates/install-result.json'), '--restart', '--show-progress']
            subprocess.Popen(command, cwd=directory, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            return 0
    except InstallBusyError:
        message = '语音资源或程序更新正在安装，打开当前事务的只读进度窗口。'
        if getattr(sys, 'frozen', False):
            import subprocess
            import shutil
            import os
            import uuid
            directory = DATA_ROOT / 'updates/updaters'
            directory.mkdir(parents=True, exist_ok=True)
            updater = directory / f'{uuid.uuid4().hex}.exe'
            shutil.copy2(PROJECT_ROOT / 'TachiTalkUpdater.exe', updater)
            subprocess.Popen([str(updater), '--root', str(PROJECT_ROOT), '--observe',
                              '--result', str(DATA_ROOT / 'updates/install-result.json')],
                             cwd=directory, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        else:
            print(message)
            # Source mode also views the original job; no recovery/install arguments.
            from app.updates.progress_window import show_progress
            show_progress(DATA_ROOT / 'updates/install-result.json')
        return 2
    except (OSError, RuntimeError, ValueError) as error:
        # No application DLL is replaced by this startup check. Crash recovery runs first.
        if getattr(sys, 'frozen', False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f'更新事务需要处理：{error}', 'TachiTalk', 0x10)
        else:
            print(f'更新事务需要处理：{error}')
        return 1
    if getattr(sys, 'frozen', False):
        from app.paths import ensure_data_root
        try:
            ensure_data_root(DATA_ROOT)
        except OSError as error:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                f'无法在程序目录保存本机数据：{DATA_ROOT}\n{type(error).__name__}: {error}\n'
                '请将完整程序文件夹放到当前用户可写的位置后重试。未改用旧AppData配置。',
                'TachiTalk 数据目录不可写', 0x10)
            return 1
    if not getattr(sys, 'frozen', False) and sys.prefix == sys.base_prefix:
        print("请先激活项目虚拟环境：Windows .\\.venv\\Scripts\\Activate.ps1；macOS/Linux source .venv/bin/activate")
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    # 窗口版EXE没有stderr；界面安装日志流后，旧Handler也不会自动更新其stream。
    console_handlers = [logging.StreamHandler(sys.stderr)] if sys.stderr is not None else []
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        handlers=console_handlers)
    if getattr(sys, 'frozen', False):
        from logging.handlers import RotatingFileHandler
        from app.paths import DATA_ROOT
        (DATA_ROOT / 'logs').mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(DATA_ROOT / 'logs' / 'TachiTalk.log', maxBytes=2 * 1024 * 1024, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logging.getLogger().addHandler(handler)
    parser = argparse.ArgumentParser(description="TachiTalk持续监听语音链路")
    parser.add_argument("--check", action="store_true", help="仅检查配置与服务后结束；不启动常驻监听")
    parser.add_argument("--list-devices", action="store_true", help="列出PyAudio输入设备索引后结束")
    parser.add_argument("--headless", action="store_true", help="仅用终端运行语音链路，不显示立绘")
    parser.add_argument('--install-voice', action='store_true', help='打开可选语音安装面板；下载失败不影响主程序')
    args = parser.parse_args()
    ui = ConsoleUI()
    if args.list_devices:
        import pyaudio
        audio = pyaudio.PyAudio()
        try:
            for index in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(index)
                if info["maxInputChannels"]:
                    print(index, info["name"], "输入声道", info["maxInputChannels"])
        finally:
            audio.terminate()
        return 0
    startup_logs = None
    if not (args.check or args.headless):
        from app.ui.runtime_console import StartupLogBuffer
        startup_logs = StartupLogBuffer()
        logging.getLogger().addHandler(startup_logs)
        from threading import Timer
        from app.updates.cleanup import cleanup_updater_copies
        housekeeping = Timer(5, cleanup_updater_copies, args=(PROJECT_ROOT, DATA_ROOT, started_at))
        housekeeping.daemon = True
        housekeeping.start()
    try:
        from app.ui.pet.expressions import ExpressionCatalog
        settings = Settings()
        try:
            catalog = ExpressionCatalog(default=settings.default_expression, allowed_names=REF_MAP)
        except ValueError as error:
            ui.error(StageError("配置", str(error)))
            if args.check:
                return 1
            return asyncio.run(wait_for_manual_restart(ui)) or 0
        settings = replace(settings, available_expressions=catalog.names, default_expression=catalog.default)
        ui.info("可用立绘/TTS表情：" + "、".join(catalog.names))
        if args.check or args.headless:
            return asyncio.run(run(settings, ui, args.check)) or 0
        from app.ui.desktop import run_desktop
        return run_desktop(settings, catalog, startup_logs=startup_logs)
    except (KeyboardInterrupt, asyncio.CancelledError):
        ui.info("已按手动停止请求关闭程序")
        return 0
    finally:
        if startup_logs is not None:
            startup_logs.drain()


if __name__ == "__main__":
    raise SystemExit(main())
