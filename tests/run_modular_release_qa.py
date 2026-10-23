"""Explicit, heavy Windows QA. All installs use QAMode: no registry, shortcuts or stable paths.

The Ed25519 test private key lives only in memory. Never distribute these QA binaries.
"""
import argparse
import base64
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.updates.manifest import atomic_json, canonical, sha256
from scripts.component_release import create_package, voice_entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    work = args.work.resolve()
    if not work.is_relative_to(ROOT / 'work') or work.exists():
        raise ValueError('QA必须使用项目work下全新的目录')
    work.mkdir(parents=True)
    results = {'qa_only': True, 'work': str(work), 'checks': []}
    def record(name, **detail):
        results['checks'].append({'name': name, **detail})
        atomic_json(work / 'results.json', results)
        print(name, detail, flush=True)
    def run(command, timeout=900, env=None):
        print('RUN', subprocess.list2cmdline(list(map(str, command))), flush=True)
        process = subprocess.run(list(map(str, command)), timeout=timeout, env=env, cwd=ROOT)
        if process.returncode:
            raise RuntimeError(f'command exit {process.returncode}')
    key = Ed25519PrivateKey.generate()
    trust = work / 'trust/release_keys.json'
    atomic_json(trust, {'qa-only': base64.b64encode(key.public_key().public_bytes_raw()).decode()})
    client = work / 'TachiTalk'
    run([sys.executable, '-B', ROOT / 'scripts/build_release.py', '--output', client,
         '--work-dir', work / 'freeze', '--trust-keys', trust])
    record('freeze_client_and_updater', ok=True)
    compiler = args.compiler.resolve()
    def compile_setup(output, main_only, voice=None):
        command = [compiler, '/DQAMode=1', f'/DMainOnly={1 if main_only else 0}',
            '/DReleaseDir=' + str(client), '/DOutputDirectory=' + str(output)]
        if voice:
            command += ['/DVoiceDir=' + str(voice)]
        command += [ROOT / 'packaging/TachiTalk.iss']
        run(command, timeout=3600)
        return output / ('TachiTalk_main_setup.exe' if main_only else 'TachiTalk_setup.exe')
    setup = compile_setup(work / 'main-setup', True)
    install = work / '安装 主程序'
    run([setup, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TYPE=main', '/TASKS=', '/DIR=' + str(install)])
    if (install / 'services').exists() or (install / 'assets/audio').exists():
        raise AssertionError('主程序安装包混入了语音资源')
    env = dict(os.environ, LOCALAPPDATA=str(work / 'user-data'))
    def core_check(directory, name):
        destination = work / f'{name}.json'
        run([directory / 'TachiTalk.exe', '--core-check', destination], timeout=60, env=env)
        result = json.loads(destination.read_text(encoding='utf-8'))
        if not result['ok']:
            raise AssertionError(result)
        return result
    record('main_only_installer_and_core_ui', **core_check(install, 'core-main'))
    # Reinstall only the main component into an existing installation; preserve legacy data.
    legacy = install / 'services/gpt_sovits/user-legacy.dat'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'legacy runtime sentinel')
    custom = install / 'assets/user-imported.png'
    shutil.copy2(install / 'assets/平常.png', custom)
    custom_hash = sha256(custom)
    builtin = install / 'assets/平常.png'
    shutil.copy2(install / 'assets/开心.png', builtin)
    builtin_hash = sha256(builtin)
    run([setup, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TYPE=main', '/TASKS=', '/DIR=' + str(install)])
    if legacy.read_bytes() != b'legacy runtime sentinel' or sha256(custom) != custom_hash or sha256(builtin) != builtin_hash:
        raise AssertionError('main migration overwrote legacy resources')
    record('main_installer_preserves_legacy_voice_and_custom_assets', ok=True)
    def signed_package(entries, output, version='1.3.1'):
        payload = create_package(entries, output, 'main', version, '1.3.0')
        envelope = {'key_id': 'qa-only', 'payload': payload,
                    'signature': base64.b64encode(key.sign(canonical(payload))).decode()}
        path = output / 'signed.json'
        atomic_json(path, envelope)
        return payload, path, output / f'main-{version}.zip'
    fixture = work / 'fixtures'
    fixture.mkdir()
    new_readme = fixture / 'README.md'
    new_readme.write_bytes(b'updated by signed QA package')
    _, manifest, archive = signed_package([(install / 'TachiTalk.exe', Path('TachiTalk.exe')),
                                           (new_readme, Path('README.md'))], work / 'success-patch')
    updater = work / 'isolated-updater.exe'
    shutil.copy2(client / 'TachiTalkUpdater.exe', updater)
    parent = subprocess.Popen([str(install / 'TachiTalk.exe'), '--core-check', str(work / 'core-parent.json')], env=env)
    command = [str(updater), '--root', str(install), '--manifest', str(manifest), '--archive', str(archive),
        '--parent-pid', str(parent.pid), '--result', str(work / 'update-success.json')]
    run(command, timeout=120, env=env)
    if parent.wait(timeout=30) != 0:
        raise AssertionError('parent core check failed')
    if (install / 'README.md').read_bytes() != new_readme.read_bytes():
        raise AssertionError('native updater failed')
    record('native_updater_after_parent_exit', result=json.loads((work / 'update-success.json').read_text()))
    core_check(install, 'core-after-update')
    # Reset only this disposable fixture's version, then force failure after replacing the EXE.
    atomic_json(install / 'release-version.json', {'version': '1.3.0'})
    locked = install / '_internal/zz-qa-locked.txt'
    locked.write_bytes(b'original locked data')
    replacement = fixture / 'replacement.txt'
    replacement.write_bytes(b'new locked data')
    original_hash = sha256(install / 'TachiTalk.exe')
    _, manifest, archive = signed_package([(client / 'TachiTalkUpdater.exe', Path('TachiTalk.exe')),
        (replacement, Path('_internal/zz-qa-locked.txt'))], work / 'failure-patch')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateFileW(str(locked), 0x80000000, 1, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        failed = subprocess.run([str(updater), '--root', str(install), '--manifest', str(manifest),
            '--archive', str(archive), '--result', str(work / 'update-failure.json')], timeout=90, env=env)
        if failed.returncode == 0:
            raise AssertionError('occupied file unexpectedly replaced')
    finally:
        kernel.CloseHandle(handle)
    if (install / '.tachitalk-pending.json').exists():
        raise AssertionError('自动回滚未完成')
    if sha256(install / 'TachiTalk.exe') != original_hash or locked.read_bytes() != b'original locked data':
        raise AssertionError('rollback did not restore originals')
    record('native_updater_locked_file_rolls_back', result=json.loads((work / 'update-failure.json').read_text()))
    core_check(install, 'core-after-rollback')
    if args.full:
        voice = work / 'voice-stage'
        entries = list(voice_entries(ROOT))
        for index, (source, relative) in enumerate(entries):
            destination = voice / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if index % 4000 == 0:
                print('VOICE STAGE', index, '/', len(entries), flush=True)
        record('voice_inference_stage', files=len(entries), bytes=sum(p.stat().st_size for p, n in entries))
        from scripts.component_release import inventory, VOICE_VERSION
        atomic_json(voice / 'services/gpt_sovits/component-version.json',
                    {'version': VOICE_VERSION, 'files': inventory(entries)})
        full_setup = compile_setup(work / 'offline-setup', False, voice)
        full_install = work / '安装 完整离线'
        run([full_setup, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TYPE=full', '/TASKS=', '/DIR=' + str(full_install)], timeout=1800)
        record('full_offline_installer', **core_check(full_install, 'core-full'))
        # Existing diagnostic entry starts only an owned service on a free port, then stops it.
        run([full_install / 'TachiTalk.exe', '--release-check', work / 'tts-full.json'], timeout=480, env=env)
        tts = json.loads((work / 'tts-full.json').read_text(encoding='utf-8'))
        if not tts['ok'] or not tts['owned_service_stopped']:
            raise AssertionError(tts)
        record('trimmed_voice_actual_inference', **tts)
        payload = create_package(entries, work / 'voice-package', 'voice', VOICE_VERSION, '*', tag='v1.3.0')
        envelope = {'key_id': 'qa-only', 'payload': payload,
            'signature': base64.b64encode(key.sign(canonical(payload))).decode()}
        atomic_json(work / 'voice-package/voice-manifest.json', envelope)
        from app.updates.manifest import verify
        verify(envelope, json.loads(trust.read_text()))
        record('voice_package_and_signature', archive=payload['archive'], parts=len(payload['parts']))
        if len(canonical(envelope)) > 32 * 1024**2:
            raise AssertionError('voice manifest exceeds supported bound')
        run([updater, '--root', install, '--manifest', work / 'voice-package/voice-manifest.json',
             '--archive', work / 'voice-package' / f'voice-{VOICE_VERSION}.zip',
             '--result', work / 'voice-install-result.json'], timeout=900, env=env)
        record('native_voice_install', result=json.loads((work / 'voice-install-result.json').read_text()))
        run([install / 'TachiTalk.exe', '--release-check', work / 'tts-downloaded.json'], timeout=480, env=env)
        record('downloadable_voice_actual_inference', **json.loads((work / 'tts-downloaded.json').read_text(encoding='utf-8')))
        run([updater, '--root', install, '--uninstall-voice', '--result', work / 'voice-uninstall-result.json'], timeout=600, env=env)
        result = core_check(install, 'core-after-voice-uninstall')
        if result['voice']['installed']:
            raise AssertionError('managed voice still installed after uninstall')
        record('native_voice_uninstall_and_core_usable', **result)
    record('qa_finished', ok=True)


if __name__ == '__main__':
    main()
