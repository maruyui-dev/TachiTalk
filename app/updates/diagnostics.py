"""Read-only official resource probes; never authorize an installation or change routing."""
import asyncio
import os
import re
from threading import Event
from time import monotonic
from urllib.request import getproxies

import aiohttp

from app.updates.download import Policy, request, session_for, sources
from app.updates.manifest import REPOSITORY, verify

LATEST_MANIFEST_URL = f'https://github.com/{REPOSITORY}/releases/latest/download/voice-manifest.json'


def pac_configured():
    if os.name != 'nt':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
            return bool(winreg.QueryValueEx(key, 'AutoConfigURL')[0])
    except FileNotFoundError:
        return False


def proxy_status():
    """Presence only. Do not expose proxy URLs/credentials or infer TUN routing."""
    try:
        configured = getproxies()
        detected = any(configured.get(kind) for kind in ('http', 'https', 'all', 'socks'))
        pac = pac_configured()
    except OSError:
        return {'state': 'unknown', 'summary': '代理状态无法确认'}
    return {'state': 'detected' if detected or pac else 'not_found',
        'summary': '检测到系统 / 环境代理设置' if detected else '检测到自动代理脚本' if pac else '未发现系统 / 环境代理'}


async def probe_url(url, *, kind, expected_size=None, policy=None, timeout=8, source=None):
    """Read <=1 KiB; latency ends at first body byte, including connect and redirects."""
    policy = policy or Policy()
    started = monotonic()
    try:
        # The single fixed discovery endpoint is not a pinned Release asset. All
        # artifact URLs still require the original strict official-asset policy.
        if kind != 'manifest' or url != LATEST_MANIFEST_URL:
            policy.official(url)
        source = dict(source or {}, connect_timeout=4, read_timeout=4)
        async with asyncio.timeout(timeout), session_for(source) as session:
            response = await request(session, policy.source_url(url, source), {'Range': 'bytes=0-1023'}, policy)
            try:
                if response.status not in (200, 206):
                    raise ValueError(f'HTTP {response.status}')
                if response.headers.get('Content-Encoding', 'identity') != 'identity':
                    raise ValueError('响应使用了压缩编码')
                if 'text/html' in response.headers.get('Content-Type', '').lower():
                    raise ValueError('返回了 HTML 页面，而非资源')
                count = min(1024, response.content_length) if response.content_length is not None else 1024
                data = bytearray(await response.content.read(1))
                first_byte_ms = (monotonic() - started) * 1000
                while len(data) < count:
                    block = await response.content.read(count - len(data))
                    if not block:
                        break
                    data.extend(block)
                if not data:
                    raise ValueError('资源响应为空')
                if response.status == 206:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not match:
                        raise ValueError('分段响应缺少有效 Content-Range')
                    start, end, total = map(int, match.groups())
                    if (start != 0 or end != min(1024, total) - 1 or len(data) != end + 1
                            or (expected_size is not None and total != expected_size)):
                        raise ValueError('分段响应范围或文件长度不匹配')
                elif expected_size is not None and response.content_length not in (None, expected_size):
                    raise ValueError('资源长度与签名清单不匹配')
                prefix = bytes(data).lstrip().lower()
                if prefix.startswith((b'<html', b'<!doctype', b'<?xml')):
                    raise ValueError('返回了错误页面，而非资源')
                if kind == 'manifest' and not prefix.startswith(b'{'):
                    raise ValueError('清单响应不是 JSON 对象')
                return {'state': 'ok', 'latency_ms': first_byte_ms,
                    'bytes_read': len(data), 'detail': f'HTTP {response.status} · 已读取资源前缀'}
            finally:
                response.close()  # A server may ignore Range; never drain its multi-GB response.
    except (TimeoutError, aiohttp.ServerTimeoutError):
        return {'state': 'timeout', 'detail': '连接或读取超时'}
    except (OSError, ValueError, aiohttp.ClientError) as error:
        return {'state': 'error', 'detail': f'{type(error).__name__}: {error}'}


async def select_voice_source(artifact, *, stop=None, progress=lambda value: None):
    """Strict 250 ms TTFB decision for a new online task only."""
    from app.updates.download import Paused
    if stop is not None and stop.is_set():
        raise Paused('已取消下载连接检测')
    progress({'status':'正在检测 GitHub 实际分卷链路（最多 3 秒）','routing':{'state':'checking'}})
    probe = await probe_url(artifact['url'], kind='artifact', expected_size=artifact['size'], timeout=3)
    if stop is not None and stop.is_set():
        raise Paused('已取消下载连接检测')
    latency = probe.get('latency_ms')
    fast = probe.get('state') == 'ok' and isinstance(latency,(int,float)) and 0 <= latency < 250
    source = 'GitHub' if fast else '魔搭'
    reason = (f'GitHub 首字节 {latency:.2f} ms，严格小于 250 ms' if fast else
        f'GitHub 首字节 {latency:.2f} ms，大于或等于 250 ms' if probe.get('state') == 'ok' and latency is not None
        else 'GitHub 探测超时或异常：' + probe.get('detail', '未取得有效响应'))
    result = {'source':source,'reason':reason,'probe':probe}
    progress({'status':f'采用 {source}：{reason}','source':source,'routing':result})
    return result


async def diagnose(client, envelope=None, *, stop=None, progress=lambda value: None, include_github=False):
    stop = stop or Event()
    if stop.is_set():
        return {'state': 'cancelled'}
    proxy = proxy_status()
    payload, manifest_error = None, ''
    try:
        if envelope is None:
            try:
                envelope = client.cached('voice')
            except (OSError, ValueError, KeyError, TypeError):
                # A first-run prefix-only probe cannot discover a signed part URL.
                # Fetch the bounded manifest, verify it, then probe <=1 KiB/part.
                envelope = await client.voice_manifest(progress, stop=stop)
        payload = verify(envelope, client.keys)
        if payload['component'] != 'voice':
            raise ValueError('不是语音组件清单')
    except (OSError, ValueError, KeyError, TypeError) as error:
        manifest_error = f'尚无可用的可信语音清单：{error}'
        payload = None
    if stop.is_set():
        return {'state': 'cancelled'}
    manifest_url = (payload['parts'][0]['url'].rsplit('/', 1)[0] + '/voice-manifest.json' if payload else
        LATEST_MANIFEST_URL)
    config = client.configuration()
    configured = sources(config)
    if not configured:
        raise ValueError('未启用下载源，请在下载设置中启用 GitHub 或魔搭')
    preferred = config.get('preferred_download_source')
    source = next((s for s in configured if not s.get('prefix')), configured[0])
    channel = source.get('name', 'GitHub')
    progress({'status': f'正在检测 {channel} 清单与语音分卷连接（最多约 8 秒）'})
    async def probes(selected):
        manifest_probe = probe_url(manifest_url, kind='manifest', source=selected)
        if payload:
            part = payload['parts'][0]
            return await asyncio.gather(manifest_probe,
                probe_url(part['url'], kind='artifact', expected_size=part['size'], source=selected))
        return await manifest_probe, {'state': 'unknown', 'detail': '需先取得可信清单，才能检测对应分卷'}
    mirror = next((s for s in configured if s.get('layout') == 'modelscope'), None)
    if mirror:
        (manifest, artifact), mirror_result = await asyncio.gather(probes(source), probes(mirror))
        direct = None
    else:
        manifest, artifact = await probes(source)
        direct, mirror_result = None, None
    if stop.is_set():
        return {'state': 'cancelled'}
    state = ('failed' if any(item['state'] in ('timeout', 'error') for item in (manifest, artifact)) else
        'ok' if artifact['state'] == 'ok' else 'unknown')
    return {'state': state, 'channel': channel, 'prefix': source.get('prefix', ''),
        'modelscope': {'manifest':mirror_result[0], 'artifact':mirror_result[1]} if mirror_result else None,
        'github': {'manifest': direct[0], 'artifact': direct[1]} if direct else None,
        'manifest': manifest, 'artifact': artifact, 'proxy': proxy,
        'manifest_error': manifest_error}
