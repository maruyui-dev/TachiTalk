"""Bounded HTTP requests and durable, conservative Range resumption."""
import asyncio
import json
import logging
from pathlib import Path
import re
import urllib.request
from threading import Event
from time import monotonic
from urllib.parse import urlsplit

import aiohttp

from app.updates.manifest import atomic_json, official_url, sha256

LOG = logging.getLogger('tachitalk.updates')


class Paused(Exception):
    pass


class HTTPDownloadError(ValueError):
    def __init__(self, status):
        super().__init__(f'HTTP {status}')
        self.retryable = status == 429 or status >= 500


class Policy:
    def __init__(self, test_origin=None):
        # Only injectable by tests; never read this from remote manifests or user config.
        self.test_origin = test_origin

    def official(self, url):
        if self.test_origin and url.startswith(self.test_origin + '/'):
            return url
        return official_url(url)

    def source_url(self, url, source):
        from app.updates.modelscope import resolve, retired
        if retired(source):
            raise ValueError('该下载渠道已移除，请切换到 GitHub 或魔搭')
        if source.get('layout') == 'modelscope':
            return resolve(url, source)
        prefix = source.get('prefix', '')
        if prefix:
            parsed = urlsplit(prefix)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment):
                raise ValueError('代理前缀必须是无鉴权HTTPS地址')
        return prefix + url

    def redirect(self, url, initial):
        parsed, start = urlsplit(url), urlsplit(initial)
        if self.test_origin and url.startswith(self.test_origin + '/'):
            return
        from app.updates.modelscope import trusted_redirect
        if trusted_redirect(url, initial):
            return
        hosts = {start.hostname, 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
        if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password
                or parsed.port not in (443, None)):
            raise ValueError('下载重定向地址不受信任')


def sources(config, kind='sources'):
    from app.updates.modelscope import retired
    result = []
    for item in config.get(kind, []):
        if not item.get('enabled', True) or retired(item):
            continue
        item = dict(item)
        for name, default, maximum in [('connect_timeout', 8, 30), ('read_timeout', 20, 60), ('retries', 1, 3)]:
            value = item.get(name, default)
            if type(value) not in (int, float) or not (0 <= value <= maximum):
                raise ValueError('下载源超时/重试配置不正确')
            item[name] = max(1, value) if name != 'retries' else int(value)
        result.append(item)
    return sorted(result, key=lambda item: (bool(item.get('fallback_only', False)), item.get('priority', 0)))


async def _request_chain(session, url, headers, policy):
    initial = url
    from urllib.parse import urljoin
    for _ in range(6):
        policy.redirect(url, initial)
        # Match the system/environment proxy that the diagnostics panel reports.
        # Resolve on every redirect so NO_PROXY/bypass applies to the actual host.
        # Keep trust_env=False: no implicit .netrc credentials are read or sent.
        proxy = system_proxy(url)
        response = await session.get(url, headers=headers, allow_redirects=False,
            **({'proxy': proxy} if proxy else {}))
        if response.status not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get('Location', '')
        response.release()
        if not location:
            raise ValueError('重定向缺少地址')
        url = urljoin(url, location)
    raise ValueError('重定向次数过多')


def system_proxy(url):
    parsed = urlsplit(url)
    if urllib.request.proxy_bypass(parsed.hostname or ''):
        return None
    configured = urllib.request.getproxies()
    proxy = configured.get(parsed.scheme) or configured.get('all')
    if proxy and urlsplit(proxy).scheme not in ('http', 'https'):
        raise ValueError('系统代理协议不支持；请使用 HTTP/HTTPS 代理或系统全局路由')
    return proxy


async def request(session, url, headers, policy):
    # Always start at the stable entry. Never persist/reuse temporary LFS URLs.
    response = await _request_chain(session, url, headers, policy)
    from app.updates.modelscope import ENTRY
    if url.startswith(ENTRY) and response.status in (401,403):
        response.close()
        response = await _request_chain(session, url, dict(headers, **{'Cache-Control':'no-cache'}), policy)
    return response


def session_for(source):
    return aiohttp.ClientSession(auto_decompress=False, trust_env=False,
        timeout=aiohttp.ClientTimeout(total=None, connect=source['connect_timeout'], sock_read=source['read_timeout']),
        headers={'Accept-Encoding': 'identity', 'User-Agent': 'TachiTalk-Updater/1.3'})


async def fetch_small(url, configured, *, limit=8 * 1024 * 1024, policy=None, validator=None):
    policy = policy or Policy()
    failures = []
    for source in configured:
        for _ in range(source['retries'] + 1):
            try:
                async with session_for(source) as session:
                    async with asyncio.timeout(45):
                        response = await request(session, policy.source_url(url, source), {}, policy)
                        async with response:
                            if response.status != 200:
                                raise ValueError(f'HTTP {response.status}')
                            data = bytearray()
                            async for block in response.content.iter_chunked(65536):
                                data.extend(block)
                                if len(data) > limit:
                                    raise ValueError('远程清单超过大小限制')
                            body = bytes(data)
                            if validator is not None:
                                validator(body)  # A 200 error page or invalid signature is a failed source.
                            return body
            except (OSError, ValueError, TimeoutError, aiohttp.ClientError) as error:
                failures.append(f"{source['name']}: {type(error).__name__}: {error}")
    raise ValueError('所有检查源均不可用：' + '; '.join(failures))


class Downloader:
    def __init__(self, configured, *, progress=lambda value: None, stop=None, policy=None, source_lock=None):
        self.configured, self.progress = configured, progress
        self.stop, self.policy = stop or Event(), policy or Policy()
        self.source_lock = Path(source_lock) if source_lock else None
        self.pinned_source = None
        self._pin_recorded = False
        if self.source_lock and self.source_lock.exists():
            if self.source_lock.stat().st_size > 16384:
                raise ValueError('下载来源记录过大，请手动切源后重试')
            try:
                value = json.loads(self.source_lock.read_text(encoding='utf-8'))
                if (not isinstance(value, dict) or set(value) != {'name','prefix','layout'}
                        or any(not isinstance(v,str) for v in value.values())):
                    raise ValueError('格式无效')
            except (ValueError, TypeError) as error:
                raise ValueError('下载来源记录损坏，请手动切源后重试') from error
            self.pinned_source, self._pin_recorded = value, True

    @staticmethod
    def source_identity(source):
        return {key: source.get(key, default) for key, default in
            (('name',''), ('prefix',''), ('layout','prefix'))}

    def pin(self, source):
        identity = self.source_identity(source)
        if self.pinned_source is not None and self.pinned_source != identity:
            raise ValueError('下载已固定来源，请通过切换来源清理旧任务后重试')
        self.pinned_source = identity
        if self.source_lock and not self._pin_recorded:
            atomic_json(self.source_lock, identity)
            self._pin_recorded = True

    async def wait_retry(self, attempt):
        # Short interruptible backoff; a slow but progressing stream is never switched.
        until = monotonic() + min(2 ** attempt, 4)
        while monotonic() < until:
            self.check_stop()
            await asyncio.sleep(min(.1, max(0, until - monotonic())))
        self.check_stop()

    def check_stop(self):
        if self.stop.is_set():
            raise Paused('已停止下载；保留可续传的临时文件')

    async def download(self, artifact, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and destination.stat().st_size == artifact['size'] and sha256(destination) == artifact['sha256']:
            return destination
        partial = destination.with_suffix(destination.suffix + '.part')
        state = destination.with_suffix(destination.suffix + '.state.json')
        self.check_stop()
        # Old versions left the source URL in the resumable part record. Honor it,
        # rather than truncating a user's existing download after a configuration reorder.
        if self.pinned_source is None and partial.is_file() and partial.stat().st_size:
            try:
                saved = json.loads(state.read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError):
                saved = {}
            if (isinstance(saved,dict) and saved.get('sha256') == artifact['sha256']
                    and saved.get('size') == artifact['size'] and isinstance(saved.get('url'),str)):
                old = next((s for s in self.configured if any(self.policy.source_url(u,s)==saved['url']
                    for u in [artifact['url'],*artifact.get('urls',[])])), None)
                if old is None:
                    # A signed manifest can change its asset URL without changing the
                    # provider. Select only an unambiguous configured route; never fetch
                    # the cached URL itself or append its bytes to a different URL.
                    candidates = []
                    for candidate in self.configured:
                        resolved = self.policy.source_url(artifact['url'],candidate)
                        prefix = candidate.get('prefix','')
                        same_route = (saved['url'].startswith(prefix) if prefix else
                            (urlsplit(saved['url']).scheme,urlsplit(saved['url']).netloc) ==
                            (urlsplit(resolved).scheme,urlsplit(resolved).netloc))
                        if same_route:
                            candidates.append(candidate)
                    if len(candidates) == 1:
                        old = candidates[0]
                if old is None:
                    raise ValueError('原下载来源已禁用或更改，缓存已保留；请手动切换来源')
                self.pin(old)
        if partial.is_file() and partial.stat().st_size == artifact['size'] and sha256(partial) == artifact['sha256']:
            self.check_stop()
            partial.replace(destination)
            state.unlink(missing_ok=True)
            return destination
        configured = [s for s in self.configured if self.pinned_source is None
            or self.source_identity(s) == self.pinned_source]
        if not configured:
            raise ValueError('原下载来源已禁用或更改，缓存已保留；请手动切换来源')
        failures = []
        for url in [artifact['url'], *artifact.get('urls', [])]:
            self.policy.official(url)
            for source in configured:
                resolved = self.policy.source_url(url, source)
                if failures and source.get('layout') == 'modelscope' and self.pinned_source is None:
                    self.progress({'status':'GitHub 传输开始前失败，采用魔搭','source':source['name'],
                        'source_reason':'GitHub 尚未收到资源数据即失败；改用魔搭，保留完整签名和文件校验'})
                if source.get('fallback_only'):
                    self.progress({'status': '常规源失败，自动启用待命代理', 'source': source['name']})
                attempts = max(3, source['retries'] + 1)
                for attempt in range(attempts):
                    self.check_stop()
                    try:
                        await self._transfer(artifact, partial, state, resolved, source)
                        if partial.stat().st_size != artifact['size'] or sha256(partial) != artifact['sha256']:
                            # Never leave a known corrupt prefix eligible for resumption.
                            state.unlink(missing_ok=True)
                            raise ValueError('资源大小或SHA-256校验失败，拒绝安装')
                        self.check_stop()
                        partial.replace(destination)
                        state.unlink(missing_ok=True)
                        return destination
                    except (OSError, ValueError, TimeoutError, aiohttp.ClientError) as error:
                        failures.append(f"{source['name']}: {type(error).__name__}: {error}")
                        LOG.warning('下载失败 来源=%s 次数=%s/%s 错误=%s: %s', source['name'],
                            attempt + 1, attempts, type(error).__name__, error)
                        transient = (isinstance(error,(OSError,TimeoutError,aiohttp.ClientError))
                            or isinstance(error,HTTPDownloadError) and error.retryable)
                        if transient and attempt + 1 < attempts:
                            self.progress({'status': f'当前来源连接中断，正在同源重试 {attempt+1}/{attempts-1}',
                                'source':source['name'],'error':f'{type(error).__name__}: {error}'})
                            await self.wait_retry(attempt)
                            continue
                        if self.pinned_source is not None:
                            raise ValueError(f"当前来源 {source['name']} 下载失败，未自动切源；缓存已保留。"
                                f"请继续下载重试当前来源，或手动切换来源。原因：{type(error).__name__}: {error}") from error
                        self.progress({'status':'当前来源不可用，尝试备用来源', 'source':source['name'],
                            'error':f'{type(error).__name__}: {error}'})
                        break
        raise ValueError('所有下载源均失败：' + '; '.join(failures))

    async def _transfer(self, artifact, partial, state, url, source):
        offset, saved = 0, {}
        try:
            saved = json.loads(state.read_text(encoding='utf-8'))
            if (saved.get('sha256') == artifact['sha256'] and saved.get('size') == artifact['size']
                    and saved.get('url') == url and saved.get('etag') and not saved['etag'].startswith('W/')
                    and partial.is_file()):
                offset = partial.stat().st_size
                if not 0 < offset < artifact['size']:
                    offset = 0
        except (OSError, ValueError, TypeError):
            pass
        headers = {'Range': f'bytes={offset}-', 'If-Range': saved['etag']} if offset else {}
        async with session_for(source) as session:
            response = await request(session, url, headers, self.policy)
            async with response:
                if response.headers.get('Content-Encoding', 'identity') != 'identity':
                    raise ValueError('拒绝压缩编码的字节范围响应')
                if response.status == 200:
                    offset = 0  # Server ignored Range / changed validator: truncate safely.
                elif response.status == 206 and offset:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if (not match or tuple(map(int, match.groups())) != (offset, artifact['size'] - 1, artifact['size'])
                            or response.headers.get('ETag') != saved['etag']):
                        state.unlink(missing_ok=True)
                        raise ValueError('Content-Range或文件标识不匹配，已取消续传')
                else:
                    if response.status == 416:
                        state.unlink(missing_ok=True)
                    raise HTTPDownloadError(response.status)
                if response.content_length is not None and response.content_length != artifact['size'] - offset:
                    state.unlink(missing_ok=True)
                    raise ValueError('响应文件长度与签名清单不符')
                started, initial = monotonic(), offset
                with partial.open('ab' if offset else 'wb') as output:
                    output.flush()
                    atomic_json(state, {'sha256': artifact['sha256'], 'size': artifact['size'], 'url': url,
                                        'etag': response.headers.get('ETag', '')})
                    async for block in response.content.iter_chunked(128 * 1024):
                        self.check_stop()
                        if offset + len(block) > artifact['size']:
                            state.unlink(missing_ok=True)
                            raise ValueError('下载长度超过清单限制')
                        output.write(block)
                        offset += len(block)
                        self.pin(source)
                        self.progress({'status': '下载中', 'source': source['name'], 'done': offset,
                            'total': artifact['size'], 'speed': (offset - initial) / max(.01, monotonic() - started),
                            'remaining': artifact['size'] - offset})
                self.check_stop()
