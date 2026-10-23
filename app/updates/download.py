"""Bounded HTTP requests and durable, conservative Range resumption."""
import asyncio
import json
from pathlib import Path
import re
from threading import Event
from time import monotonic
from urllib.parse import urlsplit

import aiohttp

from app.updates.manifest import atomic_json, official_url, sha256


class Paused(Exception):
    pass


class Policy:
    def __init__(self, test_origin=None):
        # Only injectable by tests; never read this from remote manifests or user config.
        self.test_origin = test_origin

    def official(self, url):
        if self.test_origin and url.startswith(self.test_origin + '/'):
            return url
        return official_url(url)

    def source_url(self, url, source):
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
        hosts = {start.hostname, 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
        if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password
                or parsed.port not in (443, None)):
            raise ValueError('下载重定向地址不受信任')


def sources(config, kind='sources'):
    result = []
    for item in config.get(kind, []):
        if not item.get('enabled', True):
            continue
        item = dict(item)
        for name, default, maximum in [('connect_timeout', 8, 30), ('read_timeout', 20, 60), ('retries', 1, 3)]:
            value = item.get(name, default)
            if type(value) not in (int, float) or not (0 <= value <= maximum):
                raise ValueError('下载源超时/重试配置不正确')
            item[name] = max(1, value) if name != 'retries' else int(value)
        result.append(item)
    return sorted(result, key=lambda item: (bool(item.get('fallback_only', False)), item.get('priority', 0)))


async def request(session, url, headers, policy):
    initial = url
    from urllib.parse import urljoin
    for _ in range(6):
        policy.redirect(url, initial)
        response = await session.get(url, headers=headers, allow_redirects=False)
        if response.status not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get('Location', '')
        response.release()
        if not location:
            raise ValueError('重定向缺少地址')
        url = urljoin(url, location)
    raise ValueError('重定向次数过多')


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
    def __init__(self, configured, *, progress=lambda value: None, stop=None, policy=None):
        self.configured, self.progress = configured, progress
        self.stop, self.policy = stop or Event(), policy or Policy()

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
        if partial.is_file() and partial.stat().st_size == artifact['size'] and sha256(partial) == artifact['sha256']:
            self.check_stop()
            partial.replace(destination)
            state.unlink(missing_ok=True)
            return destination
        failures = []
        for url in [artifact['url'], *artifact.get('urls', [])]:
            self.policy.official(url)
            for source in self.configured:
                resolved = self.policy.source_url(url, source)
                if source.get('fallback_only'):
                    self.progress({'status': '常规源失败，自动启用待命代理', 'source': source['name']})
                for _ in range(source['retries'] + 1):
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
                        self.progress({'status': '重试 / 切换下载源', 'source': source['name'], 'error': str(error)})
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
                    raise ValueError(f'HTTP {response.status}')
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
                        self.progress({'status': '下载中', 'source': source['name'], 'done': offset,
                            'total': artifact['size'], 'speed': (offset - initial) / max(.01, monotonic() - started),
                            'remaining': artifact['size'] - offset})
                self.check_stop()
