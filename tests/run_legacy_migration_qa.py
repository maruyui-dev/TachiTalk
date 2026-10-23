"""Real frozen-client reuse of a non-default legacy inference directory, without copying it."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--legacy', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    client, legacy, work = args.client.resolve(), args.legacy.resolve(), args.work.resolve()
    if any(not p.is_relative_to(ROOT / 'work') for p in (client, legacy, work)) or work.exists():
        raise ValueError('All migration fixtures must be inside work; output must be fresh')
    work.mkdir(parents=True)
    location = work / 'user-data/TachiTalk/settings/voice_location.json'
    location.parent.mkdir(parents=True)
    location.write_text(json.dumps({'installation': str(legacy)}), encoding='utf-8')
    env = dict(os.environ, LOCALAPPDATA=str(work / 'user-data'))
    if (client / 'services/gpt_sovits/runtime/python.exe').exists():
        raise AssertionError('Fixture already has its own runtime; this would not prove reuse')
    core, tts = work / 'core.json', work / 'tts.json'
    original = (legacy / 'services/gpt_sovits/runtime/python.exe').stat().st_mtime_ns
    subprocess.run([str(client / 'TachiTalk.exe'), '--core-check', str(core)], env=env, check=True, timeout=90)
    if not json.loads(core.read_text(encoding='utf-8'))['voice']['installed']:
        raise AssertionError('Legacy runtime was not detected')
    subprocess.run([str(client / 'TachiTalk.exe'), '--release-check', str(tts)], env=env, check=True, timeout=480)
    actual = json.loads(tts.read_text(encoding='utf-8'))
    if not actual['ok'] or not actual['owned_service_stopped']:
        raise AssertionError(actual)
    if (client / 'services/gpt_sovits/runtime/python.exe').exists() or (legacy / 'services/gpt_sovits/runtime/python.exe').stat().st_mtime_ns != original:
        raise AssertionError('Migration copied or replaced legacy runtime')
    (work / 'result.json').write_text(json.dumps({'ok': True, 'reuse_without_copy': True, 'tts': actual}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Legacy runtime reuse, actual frozen inference, no runtime copy/overwrite: passed.')


if __name__ == '__main__':
    main()
