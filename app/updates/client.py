"""Release discovery and verified package preparation (worker-thread only)."""
import asyncio
import json
from pathlib import Path
import re
import shutil
import sys

from app.paths import PROJECT_ROOT, DATA_ROOT
from app.version import VERSION
from app.updates.download import Downloader, fetch_small, sources, Paused
from app.updates.modelscope import retired
from app.updates.install import check_space
from app.updates.manifest import REPOSITORY, MAX_MANIFEST, atomic_json, verify, sha256, load_signed, version_tuple

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
                if (isinstance(previous, dict) and previous.get('config_version', 1) in (1, 2, 3, 4)
                        and all(isinstance(previous.get(kind), list) for kind in ('sources', 'api_sources', 'manifest_sources'))):
                    backup = self.directory / 'download_sources.before-modelscope.json'
                    if not backup.exists():
                        shutil.copy2(self.config_path, backup)
                    for kind in ('sources', 'api_sources', 'manifest_sources'):
                        previous[kind] = [s for s in previous[kind] if not retired(s)]
                        for source in defaults[kind]:
                            if not any(s.get('prefix','') == source.get('prefix','') for s in previous[kind]):
                                previous[kind].append(source)
                    previous['config_version'] = defaults['config_version']
                    # Earlier defaults/preferences must not bypass the new routing rule.
                    previous.pop('preferred_download_source', None)
                    atomic_json(self.config_path, previous)
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
            config[kind] = [s for s in config.get(kind, []) if not retired(s)]
            sources(config, kind)
        if config.get('preferred_download_source') not in {s['name'] for s in config['sources']}:
            config.pop('preferred_download_source', None)
        pending = config.get('restart_archives', [])
        if (not isinstance(pending, list) or len(pending) > 64 or
                any(not isinstance(item, str) or not re.fullmatch('[0-9a-f]{64}', item) for item in pending)):
            raise ValueError('待清理下载任务配置无效')
        return config

    async def diagnose(self, envelope=None, *, stop=None, progress=lambda value: None, include_github=False):
        from app.updates.diagnostics import diagnose
        return await diagnose(self, envelope, stop=stop, progress=progress, include_github=include_github)

    def reset_download(self, envelope, stop):
        """Only after the previous worker stops; discard this signed archive's cache."""
        payload = verify(envelope, self.keys)
        downloads = self.directory / 'downloads'
        cache = downloads / payload['archive']['sha256']
        expected = self.directory.resolve() / 'downloads' / payload['archive']['sha256']
        for path in (downloads, cache):
            if path.is_symlink() or path.is_junction():
                raise ValueError('下载缓存是链接，拒绝清理')
        if cache.resolve() != expected:
            raise ValueError('下载缓存路径不符，拒绝清理')
        if stop.is_set():
            raise Paused('已取消切源，未清理缓存')
        if cache.exists():
            if not cache.is_dir() or any(p.is_symlink() or p.is_junction() for p in cache.rglob('*')):
                raise ValueError('下载缓存含链接或类型不符，拒绝清理')
            if stop.is_set():
                raise Paused('已取消切源，未清理缓存')
            shutil.rmtree(cache)
        config = self.configuration()
        if payload['archive']['sha256'] in config.get('restart_archives', []):
            config['restart_archives'] = [item for item in config['restart_archives'] if item != payload['archive']['sha256']]
            atomic_json(self.config_path, config)
        return payload['component']

    async def check(self, progress=lambda value: None):
        """Independent main metadata gate; never loads voice or release APIs."""
        from app.updates import main_feed
        if not main_feed.ENABLED:
            return {'manifests':{},'errors':{},'main':{'state':'disabled','version':None}}
        return await main_feed.check(progress)

    async def voice_manifest(self, progress=lambda value: None, *, stop=None, selected_source=None):
        """Independent signed voice discovery; never request release/version APIs."""
        if stop is not None and stop.is_set():
            raise Paused('已取消读取语音清单')
        config = self.configuration()
        configured = sources(config, 'manifest_sources')
        # First-run discovery need not wait on GitHub. Routing probes the signed
        # attachment separately after this manifest has been verified.
        configured.sort(key=lambda s: s.get('layout') != 'modelscope')
        if selected_source:
            configured = [s for s in configured if s['name'] == selected_source]
        def validate(body):
            payload = verify(json.loads(body), self.keys)
            if payload['component'] != 'voice':
                raise ValueError('不是语音组件清单')
        progress({'status':'正在独立获取并验证语音清单','phase':'preparing'})
        body = await fetch_small(f'https://github.com/{REPOSITORY}/releases/latest/download/voice-manifest.json',
            configured, limit=MAX_MANIFEST, validator=validate)
        validate(body)
        if stop is not None and stop.is_set():
            raise Paused('已取消读取语音清单')
        envelope = json.loads(body)
        atomic_json(self.directory / 'voice-manifest.json', envelope)
        return envelope

    async def main_manifest(self, version, progress=lambda value: None, *, stop=None, selected_source=None):
        """A metadata hint never authorizes writes: independently verify the signed package."""
        if version_tuple(version) <= version_tuple(VERSION):
            raise ValueError('没有高于当前版本的主程序更新')
        if stop is not None and stop.is_set():
            raise Paused('已取消主程序更新检查')
        configured = sources(self.configuration(), 'manifest_sources')
        if selected_source:
            configured = [s for s in configured if s['name'] == selected_source]
        else:
            configured.sort(key=lambda s: s.get('layout') != 'modelscope')
        if not configured:
            raise ValueError('所选主程序更新来源未启用')
        def validate_manifest(body):
            payload = verify(json.loads(body), self.keys)
            if (payload['component'] != 'main' or payload['version'] != version
                    or payload['base_version'] != VERSION):
                raise ValueError('主程序签名清单的组件或版本与当前更新不匹配')
        progress({'status': '正在获取并验证主程序更新清单'})
        body = await fetch_small(f'https://github.com/{REPOSITORY}/releases/download/v{version}/main-from-{VERSION}.json',
            configured, limit=MAX_MANIFEST, validator=validate_manifest)
        validate_manifest(body)
        if stop is not None and stop.is_set():
            raise Paused('已取消主程序更新检查')
        envelope = json.loads(body)
        atomic_json(self.directory / 'main-manifest.json', envelope)
        if selected_source:
            cache = self.directory / 'downloads' / envelope['payload']['archive']['sha256']
            lock = cache / 'source-lock.json'
            if lock.exists():
                if lock.stat().st_size > 16384:
                    raise ValueError('主程序下载来源记录过大，请清理本任务后重试')
                old = json.loads(lock.read_text(encoding='utf-8'))
                selected = next(s for s in configured if s['name'] == selected_source)
                if old != Downloader.source_identity(selected):
                    config = self.configuration()
                    config['restart_archives'] = sorted(set(config.get('restart_archives', [])) |
                        {envelope['payload']['archive']['sha256']})
                    atomic_json(self.config_path, config)
        return envelope

    async def _discover_release(self, progress=lambda value: None):
        """Dormant release discovery retained for a later reopening; no UI callers."""
        config = self.configuration()
        if not self.keys:
            raise ValueError('本构建尚未配置可信发布公钥；安装与更新已安全禁用。维护者需配置 packaging/release_keys.json 后构建。')
        result = {'manifests': {}, 'errors': {}, 'main': {'state': 'unknown', 'version': None}}
        release = None
        def validate_release(body):
            try:
                value = json.loads(body)
                version_tuple(value['tag_name'])
                if (not isinstance(value['assets'], list) or value.get('draft') or value.get('prerelease')
                        or any(not isinstance(item, dict) or not isinstance(item.get('name'), str)
                               for item in value['assets'])):
                    raise ValueError('附件列表无效')
                for field in ('name', 'body', 'published_at'):
                    text = value.get(field)
                    if text is not None and (not isinstance(text, str) or len(text) > 200_000):
                        raise ValueError('更新说明格式无效')
                return value
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise ValueError(f'Release 版本信息无效：{error}') from error
        # API metadata selects a release, never authorizes executable operations.
        # Invalid/unavailable API metadata still permits signed attachment discovery.
        try:
            body = await fetch_small(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',
                sources(config, 'api_sources'), limit=1024 * 1024, validator=validate_release)
            release = validate_release(body)
            result['main']['version'] = release['tag_name'].lstrip('v')
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            result['errors']['api'] = str(error)
        main_name = f'main-from-{VERSION}.json'
        if release:
            if version_tuple(release['tag_name']) <= version_tuple(VERSION):
                result['main']['state'] = 'current'
            elif main_name not in {item['name'] for item in release['assets']}:
                result['main']['state'] = 'no_patch'
                # Full installers are user-opened downloads, never unsigned updater transactions.
                name = f"TachiTalk-{release['tag_name']}-main.zip"
                official = f"https://github.com/{REPOSITORY}/releases/download/{release['tag_name']}/{name}"
                asset = next((a for a in release['assets'] if a['name'] == name
                    and a.get('browser_download_url') == official
                    and type(a.get('size')) is int and a['size'] > 0), None)
                configured = sources(config)
                if asset and configured:
                    from app.updates.download import Policy
                    result['main'].update(installer={'url': Policy().source_url(official,
                        configured[0]), 'size': asset['size']}, title=release.get('name') or '主程序更新',
                        notes=release.get('body') or '', published_at=release.get('published_at') or '')
        for component, name in [('main', f'main-from-{VERSION}.json'), ('voice', 'voice-manifest.json')]:
            if component == 'main' and result['main']['state'] in ('current', 'no_patch'):
                continue
            progress({'status': f'检查 {component} 清单', 'source': 'Release / manifest_sources'})
            def validate_manifest(body):
                try:
                    payload = verify(json.loads(body), self.keys)
                    if payload['component'] != component:
                        raise ValueError('组件清单类型不匹配')
                    if component == 'main':
                        if payload['base_version'] != VERSION:
                            raise ValueError('增量包不适用于当前主程序版本')
                        if release and version_tuple(payload['version']) != version_tuple(release['tag_name']):
                            raise ValueError('增量包版本与 Release 版本不一致')
                except (ValueError, KeyError, TypeError, AttributeError) as error:
                    raise ValueError(f'签名清单验证失败：{error}') from error
            try:
                location = f"download/{release['tag_name']}" if release else 'latest/download'
                body = await fetch_small(f'https://github.com/{REPOSITORY}/releases/{location}/{name}',
                                         sources(config, 'manifest_sources'), limit=MAX_MANIFEST,
                                         validator=validate_manifest)
                validate_manifest(body)
                envelope = json.loads(body)
                payload = verify(envelope, self.keys)
                if payload['component'] != component:
                    raise ValueError('组件清单类型不匹配')
                result['manifests'][component] = envelope
                atomic_json(self.directory / f'{component}-manifest.json', envelope)
                if component == 'main':
                    result['main'] = {'state': 'update_available', 'version': payload['version']}
            except (ValueError, KeyError, TypeError, OSError) as error:
                result['errors'][component] = str(error)
                if component == 'main':
                    result['main']['state'] = 'error' if release else 'unknown'
        return result

    def cached(self, component):
        envelope, _ = load_signed(self.directory / f'{component}-manifest.json', self.keys)
        return envelope

    def import_manifest(self, path):
        envelope, payload = load_signed(path, self.keys)
        atomic_json(self.directory / f"{payload['component']}-manifest.json", envelope)
        return envelope

    async def prepare(self, envelope, progress, stop, *, selected_source=None):
        progress({'status':'正在验证资源签名','phase':'preparing'})
        payload = verify(envelope, self.keys)
        config = self.configuration()
        if payload['component'] == 'voice' and config.get('reset_voice_on_next_install'):
            # Convert a pre-manifest manual source choice into a durable task reset.
            config['restart_archives'] = sorted(set(config.get('restart_archives', [])) | {payload['archive']['sha256']})
            config.pop('reset_voice_on_next_install', None)
            atomic_json(self.config_path, config)
        if payload['archive']['sha256'] in config.get('restart_archives', []):
            self.reset_download(envelope, stop)
        if stop.is_set():
            raise Paused('准备已取消；未开始下载')
        progress({'status':'正在检查安装空间与现有文件；首次准备可能约需 5 分钟','phase':'preparing'})
        check_space(payload, self.root)
        if stop.is_set():
            raise Paused('准备已取消；未开始下载')
        progress({'status':'正在检查下载缓存与磁盘空间','phase':'preparing'})
        cache = self.directory / 'downloads' / payload['archive']['sha256']
        cache.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(cache).free < 2 * payload['archive']['size'] + 32 * 1024 * 1024:
            raise ValueError('下载缓存磁盘空间不足')
        configured = sources(config)
        preferred = config.get('preferred_download_source') if payload['component'] == 'voice' else None
        if payload['component'] == 'main' and selected_source:
            configured = [s for s in configured if s['name'] == selected_source]
            if not configured:
                raise ValueError('所选主程序来源未启用')
            preferred = selected_source
        has_cache = (cache / 'source-lock.json').exists() or any(
            p.is_file() and p.stat().st_size for pattern in ('*.bin','*.bin.part','package.zip') for p in cache.glob(pattern))
        if preferred and not has_cache:
            configured = [source for source in configured if source['name'] == preferred]
            if not configured:
                raise ValueError('所选下载源已禁用或不存在，请切换来源')
            progress({'status':'按用户选择使用来源；切源任务从零开始','source':preferred})
        elif not has_cache and payload['component'] == 'voice':
            from app.updates.diagnostics import select_voice_source
            route = await select_voice_source(payload['parts'][0], stop=stop, progress=progress)
            github = [s for s in configured if not s.get('prefix')]
            mirror = [s for s in configured if s.get('layout') == 'modelscope']
            configured = github + mirror if route['source'] == 'GitHub' else mirror
            if not configured:
                raise ValueError('自动选择的渠道已禁用，请在下载设置中启用 GitHub / 魔搭')
        elif has_cache:
            progress({'status':'继续已有任务；尊重来源记录，不重新测速或清理缓存'})
        downloader = Downloader(configured, progress=progress, stop=stop, source_lock=cache / 'source-lock.json')
        parts = []
        before = 0
        for index, part in enumerate(payload['parts']):
            def aggregate(value, before=before, index=index):
                if 'done' in value:
                    value = dict(value, done=before + value['done'], total=payload['archive']['size'],
                                 remaining=payload['archive']['size'] - before - value['done'])
                progress(dict(value, part=index + 1, parts=len(payload['parts'])))
            downloader.progress = aggregate
            aggregate({'status': '准备下载 / 验证缓存', 'done': 0, 'speed': 0, 'source': ''})
            parts.append(await downloader.download(part, cache / f'{index:04}.bin'))
            before += part['size']
            progress({'status': '分卷校验通过', 'done': before, 'total': payload['archive']['size'],
                      'part': index + 1, 'parts': len(payload['parts'])})
        progress({'status': '正在合并并校验资源包', 'done': before, 'total': payload['archive']['size']})
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
