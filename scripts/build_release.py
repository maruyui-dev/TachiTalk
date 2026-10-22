"""在项目虚拟环境构建：只收集产品文件，不包含本机配置、密钥、测试和IDE缓存。"""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import os
import wave

ROOT = Path(__file__).resolve().parents[1]


def check_credentials():
    for path in [ROOT / 'config.py', *(ROOT / 'app').rglob('*.py')]:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.strip()
                if text.startswith('sk-') and len(text) > 25 and not any(c.isspace() for c in text):
                    raise ValueError(f'发行代码疑似含有密钥，已阻止打包：{path.name}')


def check_release_data():
    from config import REF_MAP
    from scripts.start_tts import check_files
    missing = check_files()
    for name, (filename, _) in REF_MAP.items():
        path = Path(filename)
        if not path.is_file():
            missing.append(f'{name}：{path}')
            continue
        try:
            with wave.open(str(path)) as audio:
                seconds = audio.getnframes() / audio.getframerate()
            if not 3 <= seconds <= 10:
                missing.append(f'{name}参考音频为{seconds:.2f}秒；GPT-SoVITS要求3–10秒：{path}')
        except (OSError, EOFError, wave.Error) as error:
            missing.append(f'{name}参考音频不是有效的PCM WAV：{path}（{error}）')
    if missing:
        raise ValueError('发行资源缺失或无效，已阻止生成最终安装包：\n' + '\n'.join(missing))


def icon():
    from PySide6.QtWidgets import QApplication
    from app.ui.control_panel import make_icon
    from PIL import Image
    app = QApplication.instance() or QApplication([])
    png = ROOT / 'packaging/app.png'
    make_icon('cat', '#ec709d', 256).pixmap(256, 256).save(str(png))
    Image.open(png).save(ROOT / 'packaging/app.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])


def freeze():
    check_credentials()
    icon()
    build_env = os.environ.copy()
    # Qt使用Windows提供的ICU，不能从开发工具(如Poppler)的PATH误收集同名第三方DLL。
    system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    build_env['PATH'] = os.pathsep.join(map(str, (Path(sys.executable).parent, Path(sys.base_prefix), system / 'System32', system)))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
                    '--name', 'TachiTalk', '--icon', str(ROOT / 'packaging/app.ico'),
                    '--specpath', str(ROOT / 'packaging'), '--distpath', str(ROOT / 'dist'),
                    '--workpath', str(ROOT / 'build/pyinstaller'),
                    '--add-data', str(ROOT / 'app/services/system_speech.ps1') + ';app/services',
                    '--hidden-import', 'PySide6.QtUiTools', '--hidden-import', '_cffi_backend',
                    '--additional-hooks-dir', str(ROOT / 'packaging/hooks'),
                    '--exclude-module', 'tkinter', '--exclude-module', 'pytest', str(ROOT / 'main.py')],
                   cwd=ROOT, env=build_env, check=True)
    target = ROOT / 'dist/TachiTalk'
    for folder in ('assets', 'resources/control_panel'):
        shutil.copytree(ROOT / folder, target / folder, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.json'))
    (target / 'scripts').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'scripts/tts_service_entry.py', target / 'scripts/tts_service_entry.py')
    shutil.copy2(ROOT / 'app/services/whisper_worker.py', target / 'scripts/whisper_worker.py')
    shutil.copy2(ROOT / 'requirements.txt', target / 'requirements.txt')
    # 动态链接的Qt/PySide6及其他客户端依赖随包保留许可证。
    from importlib.metadata import distributions
    for distribution in distributions():
        for source in distribution.files or ():
            relative = Path(str(source))
            if (relative.parts and relative.parts[0].endswith('.dist-info')
                    and ('licenses' in relative.parts or relative.name.lower().startswith(('license', 'copying', 'notice')))):
                original = Path(distribution.locate_file(source))
                if original.is_file():
                    destination = target / 'licenses' / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler')
    parser.add_argument('--skip-freeze', action='store_true')
    args = parser.parse_args()
    if sys.prefix == sys.base_prefix:
        raise SystemExit('请使用项目虚拟环境运行构建脚本')
    if not args.skip_freeze:
        freeze()
    if args.compiler:
        check_credentials()
        check_release_data()
        subprocess.run([args.compiler, '/DReleaseDir=' + str(ROOT / 'dist/TachiTalk'),
                        '/DServiceDir=' + str(ROOT / 'services/gpt_sovits'),
                        '/DOutputDirectory=' + str(ROOT / 'dist/installer'),
                        str(ROOT / 'packaging/TachiTalk.iss')], cwd=ROOT, check=True)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    main()
