"""Build signed file-level component ZIPs; reuse the existing portable packager's filters."""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.updates.manifest import (REPOSITORY, allowed_path, atomic_json, canonical, safe_path,
                                  sha256, validate, MAX_MANIFEST)
from scripts.package_portable import files, MSVC_LIBRARIES

VOICE_VERSION = 'v2ProPlus-cu128-runtime-1'
INFERENCE_DIRS = {'AR', 'BigVGAN', 'configs', 'eres2net', 'f5_tts', 'feature_extractor',
                  'module', 'text', 'TTS_infer_pack'}
INFERENCE_FILES = {'sv.py', 'utils.py', 'process_ckpt.py', 'stream_v2pro.py'}
PRETRAINED = {'chinese-hubert-base', 'chinese-roberta-wwm-ext-large', 'fast_langdetect', 'sv'}
TRAINING_VERSION = 'v2ProPlus-training-2'


def training_entries(root):
    """Only v2ProPlus training additions. Never duplicate the private CUDA runtime."""
    from app.training.project import TRAINING_FILES, training_status
    service = Path(root) / 'services/gpt_sovits'
    status = training_status(service)
    if not status['installed']:
        raise ValueError('训练扩展不完整：' + '; '.join(status['missing']))
    for source, relative in files(service / 'training'):
        name = relative.as_posix()
        if (name in TRAINING_FILES or name in {'LICENSE', 'SOURCE.json', 'training_progress.py',
                                              'ASR-LICENSE.txt', 'UVR-LICENSE.txt', 'README.md'}
                or name.startswith('tools/') and source.suffix in {'.py', '.json'}):
            yield source, Path('services/gpt_sovits/training') / relative


def voice_entries(root):
    root = Path(root)
    service = root / 'services/gpt_sovits'
    distribution = json.loads((service / 'distribution.json').read_text(encoding='utf-8'))
    selected = {distribution['selected_gpt'], distribution['selected_sovits']}
    for value in selected:
        safe_path(value)
    selected.update({'api_v2.py', 'config.py', 'distribution.json', 'LICENSE',
                     'THIRD_PARTY_NOTICES.txt', 'requirements.txt', 'runtime-requirements.txt'})
    seen = set()
    for source, relative in files(service):
        parts = relative.parts
        name = relative.as_posix()
        include = name in selected or parts[0] in {'runtime', 'tools'}
        if parts[0] in {'runtime', 'tools'} and any(part in {'tests', 'test', 'demos', 'examples', 'benchmarks', 'docs', 'notebooks'} for part in parts):
            include = False
        if parts[0] == 'tools' and source.name.startswith(('train', 'test')):
            include = False
        if parts[0] == 'GPT_SoVITS' and len(parts) > 1:
            include = (parts[1] in INFERENCE_DIRS or parts[1] in INFERENCE_FILES
                       or (parts[1] == 'pretrained_models' and len(parts) > 2 and parts[2] in PRETRAINED))
            if any(part in {'prepare_datasets', 'filelists', 'tests', 'test', 'train', 'training', 'examples', 'demo'} for part in parts):
                include = False
            if source.name.startswith(('train', 's1_train', 's2_train')):
                include = False
        if include:
            seen.add(name)
            yield source, Path('services/gpt_sovits') / relative
    for name in selected:
        if name not in seen:
            raise ValueError(f'缺少所选推理文件：{name}')
    for source, relative in files(root / 'assets/audio/tts_reference'):
        yield source, Path('assets/audio/tts_reference') / relative
    for name in MSVC_LIBRARIES:
        if not (service / 'runtime' / name).is_file():
            source = root / 'dist/TachiTalk/_internal/PySide6' / name
            if not source.is_file():
                raise ValueError(f'缺少推理依赖 {name}；请先构建客户端')
            yield source, Path('services/gpt_sovits/runtime') / name


def main_entries(directory):
    for source, relative in files(directory):
        try:
            allowed_path('main', relative.as_posix())
        except ValueError:
            continue  # Assets/voice/user data/version records never enter a main delta.
        yield source, relative


def inventory(entries):
    return [{'path': name.as_posix(), 'size': source.stat().st_size, 'sha256': sha256(source)}
            for source, name in sorted(entries, key=lambda item: item[1].as_posix())]


def create_package(entries, output, component, version, base_version, base_files=None, notes='', title='',
                   tag=None, part_bytes=1900 * 1024 * 1024):
    """Returns an unsigned payload and full inventory; signing is a separate explicit step."""
    output = Path(output)
    if output.exists():
        raise ValueError('输出目录已存在；请使用新目录，保留先前发行产物')
    output.mkdir(parents=True)
    entries = list(entries)
    records = inventory(entries)
    before = {record['path']: record for record in (base_files or [])}
    changed = [record for record in records if before.get(record['path'], {}).get('sha256') != record['sha256']]
    selected = {record['path'] for record in changed}
    delete = sorted(set(before) - {record['path'] for record in records})
    archive = output / f'{component}-{version}.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zipped:
        for index, (source, name) in enumerate(entries):
            if name.as_posix() in selected:
                zipped.write(source, name.as_posix())
            if index % 2000 == 0:
                print(f'{component} ZIP: {index}/{len(entries)}', flush=True)
    parts = []
    # Fixed-size raw parts stay within GitHub's attachment limit; the client verifies each.
    if not 1 <= part_bytes < 2 * 1024**3:
        raise ValueError('分卷必须小于2GiB')
    with archive.open('rb') as stream:
        index = 0
        while block := stream.read(min(part_bytes, 1024 * 1024)):
            name = f'{archive.name}.part{index:03d}'
            part = output / name
            with part.open('xb') as destination:
                remaining = part_bytes
                while block:
                    destination.write(block)
                    remaining -= len(block)
                    if not remaining:
                        break
                    block = stream.read(min(remaining, 1024 * 1024))
            parts.append({'name': name, 'size': part.stat().st_size, 'sha256': sha256(part),
                          'url': f'https://github.com/{REPOSITORY}/releases/download/{tag or "v" + version}/{name}'})
            index += 1
    payload = {'schema': 1, 'component': component, 'version': version, 'base_version': base_version,
        'title': title or f'TachiTalk {component} {version}', 'notes': notes,
        'published_at': datetime.now(timezone.utc).isoformat(), 'files': changed, 'delete': delete,
        'archive': {'size': archive.stat().st_size, 'sha256': sha256(archive)}, 'parts': parts}
    if component == 'voice':
        payload['min_main_version'] = '1.3.0'
    elif component == 'training':
        payload['min_main_version'] = '2.0.0'
    validate(payload)
    atomic_json(output / 'unsigned-payload.json', payload)
    atomic_json(output / 'inventory.json', {'component': component, 'version': version, 'files': records})
    return payload


def sign_payload(payload, key_path, key_id):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    password = os.environ.get('TACHITALK_SIGNING_PASSWORD')
    encoded = Path(key_path).read_bytes()
    if not password and b'ENCRYPTED PRIVATE KEY' in encoded:
        if not sys.stdin.isatty():
            raise ValueError('加密私钥需要密码；请在本机交互终端运行，或通过受保护环境提供 TACHITALK_SIGNING_PASSWORD')
        import getpass
        password = getpass.getpass('签名私钥密码（输入不可见）：')
    key = load_pem_private_key(encoded, password.encode() if password else None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('签名私钥必须为Ed25519')
    envelope = {'key_id': key_id, 'payload': payload,
                'signature': base64.b64encode(key.sign(canonical(payload))).decode('ascii')}
    if len(canonical(envelope)) > MAX_MANIFEST:
        raise ValueError('签名清单超出客户端限制')
    return envelope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--component', choices=('main', 'voice', 'training'), required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--client', type=Path, default=ROOT / 'dist/TachiTalk')
    parser.add_argument('--version', required=True)
    parser.add_argument('--base-version', default='*')
    parser.add_argument('--base-inventory', type=Path)
    parser.add_argument('--full-main', action='store_true', help='完整主程序覆盖包；不带语音/个人数据，不需要旧版inventory')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--notes', type=Path)
    parser.add_argument('--tag')
    parser.add_argument('--key-id', default='release-1')
    parser.add_argument('--inventory-only', action='store_true', help='保存完整基线文件哈希，不构建更新包')
    args = parser.parse_args()
    if args.component == 'main' and (args.client / 'release-version.json').is_file():
        actual = json.loads((args.client / 'release-version.json').read_text(encoding='utf-8'))['version']
        if actual != args.version:
            raise ValueError(f'客户端构建版本 {actual} 与声明版本 {args.version} 不一致，请先构建正确版本')
    if args.inventory_only:
        if args.output.exists():
            raise ValueError('inventory 已存在，拒绝覆盖')
        entries = main_entries(args.client) if args.component == 'main' else training_entries(args.root) if args.component == 'training' else voice_entries(args.root)
        atomic_json(args.output, {'component': args.component, 'version': args.version, 'files': inventory(entries)})
        return
    if args.full_main and args.component != 'main':
        raise SystemExit('--full-main仅适用于主程序')
    if args.component == 'main' and (args.base_version == '*' or not args.full_main and not args.base_inventory):
        raise SystemExit('主程序增量包必须提供基线 inventory 和明确 base-version；首次迁移使用主程序安装器')
    base = json.loads(args.base_inventory.read_text(encoding='utf-8')) if args.base_inventory else None
    if base and (base['component'] != args.component or base['version'] != args.base_version):
        raise ValueError('基线inventory组件或版本不匹配')
    entries = main_entries(args.client) if args.component == 'main' else training_entries(args.root) if args.component == 'training' else voice_entries(args.root)
    payload = create_package(entries, args.output, args.component, args.version, args.base_version,
        base_files=base['files'] if base and not args.full_main else None,
        notes=args.notes.read_text(encoding='utf-8') if args.notes else '', tag=args.tag)
    key_path = os.environ.get('TACHITALK_SIGNING_KEY')
    if not key_path:
        raise SystemExit('已生成未签名包。未配置 TACHITALK_SIGNING_KEY，不能发布；私钥只能从安全环境读取')
    envelope = sign_payload(payload, key_path, args.key_id)
    from app.updates.manifest import verify
    verify(envelope, json.loads((ROOT / 'packaging/release_keys.json').read_text(encoding='utf-8')))
    name = f'main-from-{args.base_version}.json' if args.component == 'main' else f'{args.component}-manifest.json'
    atomic_json(args.output / name, envelope)
    print(f'Signed manifest: {name}', flush=True)


if __name__ == '__main__':
    main()
