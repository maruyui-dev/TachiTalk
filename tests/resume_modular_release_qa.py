"""Resume at the first unfinished native voice step using already-signed, verified artifacts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.updates.manifest import atomic_json, load_signed, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--updater', type=Path, required=True)
    args = parser.parse_args()
    work, updater = args.work.resolve(), args.updater.resolve()
    if not work.is_relative_to(ROOT / 'work') or not updater.is_relative_to(ROOT / 'work'):
        raise ValueError('QA must remain inside work')
    install = work / '安装 主程序'
    keys = json.loads((work / 'trust/release_keys.json').read_text(encoding='utf-8'))
    manifest = work / 'voice-package/voice-manifest.json'
    _, payload = load_signed(manifest, keys)
    archive = work / 'voice-package' / f"voice-{payload['version']}.zip"
    if archive.stat().st_size != payload['archive']['size'] or sha256(archive) != payload['archive']['sha256']:
        raise ValueError('previous archive is not intact')
    results = {'checks': [], 'updater': str(updater), 'resumed_from_verified_voice_archive': True}
    def record(name, **fields):
        results['checks'].append({'name': name, **fields})
        atomic_json(work / 'resumed-results.json', results)
        print(name, fields, flush=True)
    env = dict(os.environ, LOCALAPPDATA=str(work / 'user-data'))
    def run(command, timeout=1800):
        started = time.monotonic()
        process = subprocess.run(list(map(str, command)), env=env, timeout=timeout)
        if process.returncode:
            raise RuntimeError(f'exit {process.returncode}: {command}')
        return round(time.monotonic() - started, 2)
    if (install / '.tachitalk-pending.json').exists():
        elapsed = run([updater, '--root', install, '--recover', '--result', work / 'recovery-result.json'])
        record('interrupted_transaction_recovered', seconds=elapsed)
    record('voice_install_start', files=len(payload['files']), archive=payload['archive'], manifest_bytes=manifest.stat().st_size)
    elapsed = run([updater, '--root', install, '--manifest', manifest, '--archive', archive,
                   '--result', work / 'voice-install-result.json'])
    record('native_voice_install', seconds=elapsed, result=json.loads((work / 'voice-install-result.json').read_text()))
    run([install / 'TachiTalk.exe', '--release-check', work / 'tts-downloaded.json'], timeout=480)
    tts = json.loads((work / 'tts-downloaded.json').read_text(encoding='utf-8'))
    if not tts['ok'] or not tts['owned_service_stopped']:
        raise AssertionError(tts)
    record('downloadable_voice_actual_inference', **tts)
    elapsed = run([updater, '--root', install, '--uninstall-voice', '--result', work / 'voice-uninstall-result.json'])
    record('native_voice_uninstall', seconds=elapsed, result=json.loads((work / 'voice-uninstall-result.json').read_text()))
    run([install / 'TachiTalk.exe', '--core-check', work / 'core-after-voice-uninstall.json'], timeout=90)
    core = json.loads((work / 'core-after-voice-uninstall.json').read_text(encoding='utf-8'))
    if not core['ok'] or core['voice']['installed']:
        raise AssertionError(core)
    if (install / 'services/gpt_sovits/user-legacy.dat').read_bytes() != b'legacy runtime sentinel':
        raise AssertionError('unmanaged legacy data lost')
    record('native_voice_uninstall_and_core_usable', **core)
    record('resumed_qa_finished', ok=True)


if __name__ == '__main__':
    main()
