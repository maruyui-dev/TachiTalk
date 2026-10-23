"""用项目内的独立运行环境启动GPT-SoVITS，不向桌宠venv安装推理依赖。"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

# 直接执行 scripts/start_tts.py 时，也能从项目根目录导入 app。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.paths import TTS_SERVICE_DIR, TTS_REFERENCE_DIR, PROJECT_ROOT, DATA_ROOT


def check_files(root=TTS_SERVICE_DIR, reference_dir=None):
    root = Path(root)
    required = [
        'runtime/python.exe', 'runtime/ffmpeg.exe', 'runtime/ffprobe.exe',
        'api_v2.py', 'GPT_SoVITS/configs/tts_infer.yaml', 'distribution.json',
        'GPT_SoVITS/pretrained_models/chinese-hubert-base/pytorch_model.bin',
        'GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large/pytorch_model.bin',
        'GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt',
    ]
    missing = [str(root / name) for name in required if not (root / name).is_file()]
    manifest = root / 'distribution.json'
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
            for field in ('selected_gpt', 'selected_sovits'):
                path = (root / data[field]).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():
                    missing.append(str(path))
        except (ValueError, KeyError, TypeError) as error:
            missing.append(f'{manifest}（清单格式错误：{error}）')
    references = Path(reference_dir) if reference_dir is not None else TTS_REFERENCE_DIR
    if not any(references.glob('*.wav')):
        missing.append(str(references / '*.wav'))
    return missing


def service_command(port=9880, root=TTS_SERVICE_DIR):
    root = Path(root)
    return [str(root / 'runtime' / 'python.exe'), '-u', '-B', str(PROJECT_ROOT / 'scripts/tts_service_entry.py'),
            '--service-root', str(root), '--state-dir', str(DATA_ROOT / 'tts'), '--port', str(port)]


def service_environment(root=TTS_SERVICE_DIR):
    env = os.environ.copy()
    env['PATH'] = str(Path(root) / 'runtime') + os.pathsep + env.get('PATH', '')
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    # Only our spawned service receives this. Reused external services are untouched.
    from config import REF_MAP
    if not REF_MAP:
        env.setdefault('TACHITALK_TTS_WARMUP', '0')
        return env
    reference, prompt = REF_MAP['平常'] if '平常' in REF_MAP else next(iter(REF_MAP.values()))
    env.setdefault('TACHITALK_TTS_WARMUP', json.dumps({
        'text': '音声の準備ができました。', 'text_lang': 'ja', 'prompt_lang': 'ja',
        'ref_audio_path': reference, 'prompt_text': prompt, 'text_split_method': 'cut5',
        'batch_size': 1, 'parallel_infer': True, 'streaming_mode': False,
        'return_fragment': True, 'split_bucket': False, 'speed_factor': 1.0, 'seed': 12345,
    }, ensure_ascii=True))
    return env


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description='启动项目自带的本地GPT-SoVITS服务')
    parser.add_argument('--check', action='store_true', help='仅检查迁入文件，不加载模型')
    parser.add_argument('--port', type=int, default=9880)
    args = parser.parse_args(argv)
    if sys.prefix == sys.base_prefix:
        print('请先激活TachiTalk虚拟环境：.\\.venv\\Scripts\\Activate.ps1')
        return 2
    if os.name != 'nt':
        print('随项目迁入的GPT-SoVITS运行环境适用于Windows；其他平台需另行安装推理环境。')
        return 2
    if not 1 <= args.port <= 65535:
        parser.error('端口必须在1–65535之间')
    missing = check_files()
    if missing:
        print('本地TTS文件不完整，请补齐：\n' + '\n'.join(missing))
        return 1
    if args.check:
        print(f'本地TTS文件检查通过：{TTS_SERVICE_DIR}')
        return 0
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            print(f'端口{args.port}已有服务；可继续使用现有服务，或通过--port指定其他端口。')
            return 1
    print(f'正在从 {TTS_SERVICE_DIR} 启动TTS，地址：http://127.0.0.1:{args.port}/tts', flush=True)
    process = subprocess.Popen(service_command(args.port), cwd=TTS_SERVICE_DIR, env=service_environment())
    try:
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    raise SystemExit(main())
