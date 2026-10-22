"""从冻结客户端和私有推理环境生成完整ZIP及GitHub大小限制内的分卷。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ITEMS = ('GPT_SoVITS', 'GPT_weights_v2ProPlus', 'SoVITS_weights_v2ProPlus',
                 'runtime', 'tools', 'api_v2.py', 'config.py', 'distribution.json',
                 'LICENSE', 'THIRD_PARTY_NOTICES.txt', 'requirements.txt', 'runtime-requirements.txt')
EXCLUDED = {'.git', '__pycache__', '.cache', 'cache', 'TEMP', 'scratch', 'logs',
            '_qt_runtime_tmp', 'backups', '.idea', '.venv'}
PART_BYTES = 1900 * 1024 * 1024
MSVC_LIBRARIES = ('MSVCP140.dll', 'MSVCP140_1.dll', 'MSVCP140_2.dll')


def runtime_libraries(root):
    # PyTorch依赖MSVCP；私有Python只带VCRUNTIME，干净Windows可能尚未安装MSVCP。
    # 使用同包Qt附带的MSVC 14.x可再分发库，不复制开发机System32的随机版本。
    for name in MSVC_LIBRARIES:
        if not (root / 'services/gpt_sovits/runtime' / name).is_file():
            source = root / 'dist/TachiTalk/_internal/PySide6' / name
            if not source.is_file():
                raise ValueError(f'完整运行包缺少MSVC依赖：{name}')
            yield source, Path('TachiTalk/services/gpt_sovits/runtime') / name


def files(directory):
    directory = Path(directory)
    for base, directories, names in os.walk(directory, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in EXCLUDED
                                and not (Path(base) / name).is_symlink())
        for name in sorted(names):
            path = Path(base) / name
            if (not path.is_symlink() and name not in ('.env', 'last_session.dat', 'last_session.recovered.dat')
                    and not name.startswith('.env.')
                    and not name.endswith(('.log', '.tmp', '.tachitalk.json'))):
                yield path, path.relative_to(directory)


def entries(root):
    client = root / 'dist/TachiTalk'
    if not (client / 'TachiTalk.exe').is_file():
        raise ValueError('请先构建最新的dist/TachiTalk客户端')
    for source, relative in files(client):
        yield source, Path('TachiTalk') / relative
    service = root / 'services/gpt_sovits'
    for name in SERVICE_ITEMS:
        path = service / name
        if not path.exists():
            raise ValueError(f'完整运行包缺少推理资源：{name}')
        if path.is_dir():
            for source, relative in files(path):
                yield source, Path('TachiTalk/services/gpt_sovits') / name / relative
        else:
            yield path, Path('TachiTalk/services/gpt_sovits') / name
    for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
        yield root / name, Path('TachiTalk') / name
    for source, relative in files(root / 'docs'):
        yield source, Path('TachiTalk/docs') / relative
    yield root / 'packaging/安装说明.txt', Path('TachiTalk/安装说明.txt')
    yield from runtime_libraries(root)


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def split_archive(archive, destination, part_bytes=PART_BYTES):
    if not 1 <= part_bytes < 2 * 1024**3:
        raise ValueError('分卷大小必须小于2GiB')
    destination.mkdir(parents=True, exist_ok=True)
    parts = []
    with archive.open('rb') as source:
        index = 0
        while True:
            block = source.read(min(8 * 1024 * 1024, part_bytes))
            if not block:
                break
            index += 1
            part = destination / f'TachiTalk.zip.part{index:03d}'
            with part.open('xb') as output:
                remaining = part_bytes
                while block:
                    output.write(block)
                    remaining -= len(block)
                    if not remaining:
                        break
                    block = source.read(min(8 * 1024 * 1024, remaining))
            parts.append(part)
    return parts


def package(root, output, release):
    if output.exists():
        raise ValueError(f'目标已存在，请先保留旧包后另选路径：{output}')
    members = list(entries(root))
    names = [name.as_posix() for _, name in members]
    if len(names) != len(set(names)):
        raise ValueError('发行包存在重复路径')
    partial = output.with_suffix('.zip.partial')
    output.parent.mkdir(parents=True, exist_ok=True)
    with partial.open('xb') as raw:
        with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
            for index, (source, name) in enumerate(members, 1):
                archive.write(source, name.as_posix())
                if index % 500 == 0:
                    print(f'ZIP {index}/{len(members)}', flush=True)
    print('Checking archive CRC...', flush=True)
    with zipfile.ZipFile(partial) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f'发行包CRC校验失败：{bad}')
    partial.rename(output)
    release_assets(root, output, release, len(members))


def release_assets(root, output, release, file_count):
    release.mkdir(parents=True, exist_ok=True)
    parts = split_archive(output, release)
    checksums = [(sha256(output), output.name)] + [(sha256(path), path.name) for path in parts]
    (release / 'SHA256SUMS.txt').write_text(''.join(f'{digest}  {name}\n' for digest, name in checksums), encoding='utf-8')
    command = ['@echo off', 'setlocal', 'cd /d "%~dp0"',
               'if exist "TachiTalk.zip" (echo TachiTalk.zip already exists. Keep or rename it first. & pause & exit /b 1)']
    for path in parts:
        command.append(f'if not exist "{path.name}" (echo Missing {path.name} & pause & exit /b 1)')
    command += ['copy /b ' + '+'.join(f'"{path.name}"' for path in parts) + ' "TachiTalk.zip"',
                'if errorlevel 1 (echo Merge failed. & pause & exit /b 1)',
                'echo Verify SHA256 below against SHA256SUMS.txt:',
                'certutil -hashfile "TachiTalk.zip" SHA256',
                r'echo Extract the complete ZIP, then run TachiTalk\TachiTalk.exe.', 'pause']
    (release / 'Merge-TachiTalk.cmd').write_bytes(('\r\n'.join(command) + '\r\n').encode('ascii'))
    manifest = {'archive': output.name, 'bytes': output.stat().st_size, 'files': file_count,
                'sha256': checksums[0][0], 'parts': [p.name for p in parts],
                'runtime': json.loads((root / 'services/gpt_sovits/distribution.json').read_text(encoding='utf-8'))}
    (release / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from scripts.build_release import check_credentials, check_release_data
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--release-dir', required=True, type=Path)
    args = parser.parse_args()
    check_credentials()
    check_release_data()
    package(ROOT, args.output.resolve(), args.release_dir.resolve())
