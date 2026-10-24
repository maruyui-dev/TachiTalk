"""Public voice mirror adapter; signed GitHub identities remain unchanged."""
import re
from urllib.parse import urlsplit

from app.updates.manifest import REPOSITORY

ENTRY = 'https://modelscope.cn/models/MaruYui/TachiTalk-Voice-Runtime/resolve/master/'
FILES = {'voice-manifest.json', 'SHA256SUMS.txt', *(
    f'voice-v2ProPlus-cu128-runtime-1.zip.part{i:03}' for i in range(4))}
METADATA_FILE = 'main-latest.json'


def main_file(path):
    match = re.fullmatch(r'main/v(\d+\.\d+\.\d+)/(main-from-\d+\.\d+\.\d+\.json|main-(\d+\.\d+\.\d+)\.zip\.part\d{3})', path)
    return bool(match and (match[3] is None or match[3] == match[1]))


def resolve(url, source):
    if source.get('prefix') != ENTRY:
        raise ValueError('魔搭入口必须为已配置的公开语音仓库')
    release = f'https://github.com/{REPOSITORY}/releases/download/v1.3.0/'
    latest = f'https://github.com/{REPOSITORY}/releases/latest/download/voice-manifest.json'
    main = re.fullmatch(r'https://github\.com/' + re.escape(REPOSITORY) +
        r'/releases/download/(v\d+\.\d+\.\d+)/(main-[^/]+)', url)
    if main and main_file('main/' + main[1] + '/' + main[2]):
        return ENTRY + 'main/' + main[1] + '/' + main[2]
    name = 'voice-manifest.json' if url == latest else url[len(release):] if url.startswith(release) else ''
    if name not in FILES:
        raise ValueError('此签名附件尚未接入魔搭仓库，请使用原始来源')
    return ENTRY + name


def trusted_redirect(url, initial):
    start, target = urlsplit(initial), urlsplit(url)
    if start.hostname != 'modelscope.cn' or not initial.startswith(ENTRY):
        return False
    if (target.scheme != 'https' or target.username or target.password or target.port not in (None,443)
            or target.fragment):
        raise ValueError('魔搭重定向地址不受信任')
    # Observed public LFS endpoint. No wildcard subdomains or arbitrary OSS hosts.
    if (target.hostname == 'modelscope.cn' and url.startswith(ENTRY)
            and (url[len(ENTRY):] in FILES | {METADATA_FILE} or main_file(url[len(ENTRY):])
                or re.fullmatch(r'TachiTalk-v\d+\.\d+\.\d+-main-latest\.json', url[len(ENTRY):]))):
        return True
    if (target.hostname == 'cdn-lfs-cn-1.modelscope.cn' and
            re.fullmatch(r'/prod/lfs-objects/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{60}',target.path)):
        return True
    raise ValueError('魔搭重定向地址不受信任')


def retired(source):
    return (source.get('layout') == 'r2' or 'cloudflare' in str(source.get('name','')).lower()
        or urlsplit(source.get('prefix','')).hostname in ('download.jieyiblog.me','dl.jieyiblog.me'))
