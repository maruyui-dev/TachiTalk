"""Release discovery and verified package preparation (worker-thread only)."""
import asyncio
import json
from pathlib import Path
import shutil
import sys

from app.paths import PROJECT_ROOT, DATA_ROOT
from app.version import VERSION
from app.updates.download import Downloader, fetch_small, sources, Paused
from app.updates.install import check_space
from app.updates.manifest import REPOSITORY, MAX_MANIFEST, atomic_json, verify, sha256, load_signed

BUNDLE_ROOT = Path(getattr(sys, '_MEIPASS', PROJECT_ROOT))


class UpdateClient:
    def __init__(self, root=PROJECT_ROOT, data=DATA_ROOT):
        self.root, self.data = Path(root), Path(data)
        self.directory = self.data / 'updates'
        self.config_path = self.directory / 'download_sources.json'
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            shutil.copy2(BUNDLE_ROOT / 'packaging/download_sources.json', self.config_path)
        else:
            # Upgrade only the exact earlier vendor defaults. Preserve every customized/disabled source.
            try:
                previous = json.loads(self.config_path.read_text(encoding='utf-8'))
                defaults = json.loads((BUNDLE_ROOT / 'packaging/download_sources.json').read_text(encoding='utf-8'))
                old = {
                    'sources': [{'name': 'GitHub', 'enabled': True, 'priority': 0, 'prefix': '', 'connect_timeout': 8, 'read_timeout': 20, 'retries': 1}],
                    'api_sources': [{'name': 'GitHub API', 'enabled': True, 'priority': 0, 'prefix': '', 'connect_timeout': 6, 'read_timeout': 10, 'retries': 1}],
                    'manifest_sources': [{'name': 'GitHub manifest', 'enabled': True, 'priority': 0, 'prefix': '', 'connect_timeout': 6, 'read_timeout': 10, 'retries': 1}]}
                if previous == old:
                    backup = self.directory / 'download_sources.v1.json'
                    if not backup.exists():
                        shutil.copy2(self.config_path, backup)
                    atomic_json(self.config_path, defaults)
            except (OSError, ValueError):
                pass  # Keep invalid local JSON editable in the resource panel.
        self.keys = json.loads((BUNDLE_ROOT / 'packaging/release_keys.json').read_text(encoding='utf-8'))

    def configuration(self):
        config = json.loads(self.config_path.read_text(encoding='utf-8'))
        for kind in ('sources', 'api_sources', 'manifest_sources'):
            sources(config, kind)
        return config

    async def check(self, progress=lambda value: None):
        config = self.configuration()
        if not self.keys:
            raise ValueError('本构建尚未配置可信发布公钥；安装与更新已安全禁用。维护者需配置 packaging/release_keys.json 后构建。')
        result = {'manifests': {}, 'errors': {}}
        # API discovery is informative only. API failure never disables attachment discovery.
        try:
            await fetch_small(f'https://api.github.com/repos/{REPOSITORY}/releases/latest', sources(config, 'api_sources'), limit=1024 * 1024)
        except ValueError as error:
            result['errors']['api'] = str(error)
        for component, name in [('main', f'main-from-{VERSION}.json'), ('voice', 'voice-manifest.json')]:
            progress({'status': f'检查 {component} 清单', 'source': 'Release / manifest_sources'})
            def validate_manifest(body):
                try:
                    payload = verify(json.loads(body), self.keys)
                    if payload['component'] != component:
                        raise ValueError('组件清单类型不匹配')
                except (ValueError, KeyError, TypeError, AttributeError) as error:
                    raise ValueError(f'签名清单验证失败：{error}') from error
            try:
                body = await fetch_small(f'https://github.com/{REPOSITORY}/releases/latest/download/{name}',
                                         sources(config, 'manifest_sources'), limit=MAX_MANIFEST,
                                         validator=validate_manifest)
                envelope = json.loads(body)
                payload = verify(envelope, self.keys)
                if payload['component'] != component:
                    raise ValueError('组件清单类型不匹配')
                result['manifests'][component] = envelope
                atomic_json(self.directory / f'{component}-manifest.json', envelope)
            except (ValueError, KeyError, TypeError) as error:
                result['errors'][component] = str(error)
        return result

    def cached(self, component):
        envelope, _ = load_signed(self.directory / f'{component}-manifest.json', self.keys)
        return envelope

    def import_manifest(self, path):
        envelope, payload = load_signed(path, self.keys)
        atomic_json(self.directory / f"{payload['component']}-manifest.json", envelope)
        return envelope

    async def prepare(self, envelope, progress, stop):
        payload = verify(envelope, self.keys)
        check_space(payload, self.root)
        cache = self.directory / 'downloads' / payload['archive']['sha256']
        cache.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(cache).free < 2 * payload['archive']['size'] + 32 * 1024 * 1024:
            raise ValueError('下载缓存磁盘空间不足')
        configured = sources(self.configuration())
        downloader = Downloader(configured, progress=progress, stop=stop)
        parts = []
        before = 0
        for index, part in enumerate(payload['parts']):
            def aggregate(value, before=before, index=index):
                if 'done' in value:
                    value = dict(value, done=before + value['done'], total=payload['archive']['size'],
                                 remaining=payload['archive']['size'] - before - value['done'])
                progress(dict(value, part=index + 1, parts=len(payload['parts'])))
            downloader.progress = aggregate
            parts.append(await downloader.download(part, cache / f'{index:04}.bin'))
            before += part['size']
        output = cache / 'package.zip'
        if not (output.exists() and output.stat().st_size == payload['archive']['size']
                and sha256(output) == payload['archive']['sha256']):
            partial = cache / 'package.zip.new'
            with partial.open('wb') as destination:
                for part in parts:
                    with part.open('rb') as source:
                        while block := source.read(1024 * 1024):
                            if stop.is_set():
                                raise Paused('已停止合并，可重试')
                            destination.write(block)
            if partial.stat().st_size != payload['archive']['size'] or sha256(partial) != payload['archive']['sha256']:
                raise ValueError('合并后的资源包校验失败')
            partial.replace(output)
        manifest = cache / 'manifest.json'
        atomic_json(manifest, envelope)
        if stop.is_set():
            raise Paused('校验完成，已按请求暂停；未安装，可稍后继续')
        return {'archive': output, 'manifest': manifest, 'payload': payload}
