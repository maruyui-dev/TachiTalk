"""Exercise the native updater's restart branch with a harmless temporary windowless EXE."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--updater', type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    if work.exists() or not work.is_relative_to(ROOT / 'work'):
        raise ValueError('Use a fresh directory inside work')
    work.mkdir(parents=True)
    source = work / 'probe.py'
    source.write_text("from pathlib import Path\nimport sys\nPath(sys.executable).with_name('restarted.txt').write_text('restarted', encoding='utf-8')\n", encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--windowed', '--onefile', '--name', 'TachiTalk',
        '--distpath', str(work / 'install'), '--workpath', str(work / 'build'), '--specpath', str(work), str(source)], check=True)
    result = work / 'result.json'
    subprocess.run([str(args.updater.resolve()), '--root', str(work / 'install'), '--recover', '--restart',
                    '--result', str(result)], timeout=60, check=True)
    marker = work / 'install/restarted.txt'
    deadline = time.monotonic() + 30
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.1)
    if not marker.exists() or marker.read_text(encoding='utf-8') != 'restarted':
        raise AssertionError('native updater did not relaunch the executable')
    result.write_text(json.dumps({'ok': True, 'native_restart_probe': True}), encoding='utf-8')
    print('Native updater restart branch passed. Probe exits immediately; no microphone or UI opened.')


if __name__ == '__main__':
    main()
