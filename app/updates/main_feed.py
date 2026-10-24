"""Bounded main version hints; executable updates require a separate signed manifest."""
import asyncio
from datetime import datetime
import json
import re
import aiohttp
from app.updates.download import fetch_small
from app.updates.manifest import version_tuple
from app.updates.modelscope import ENTRY
from app.version import VERSION
from app.updates.manifest import REPOSITORY

ENABLED = True  # Public object anonymously verified; see main-feed-live.json evidence.
URL = ENTRY + 'main-latest.json'


async def check(progress=lambda value: None):
    result = {'manifests':{},'errors':{},'main':{'state':'disabled','version':None}}
    if not ENABLED:
        return result
    def validate(body):
        value = json.loads(body) if isinstance(body, (bytes, str)) else body
        if (not isinstance(value,dict) or type(value.get('schema')) is not int or value['schema'] != 1
                or value.get('component') != 'main' or value.get('channel') not in ('testing','stable')
                or not isinstance(value.get('version'),str) or not re.fullmatch(r'\d+\.\d+\.\d+',value['version'])):
            raise ValueError('主程序版本信息格式无效')
        for field,maximum in (('title',512),('notes',65536),('published_at',128)):
            if not isinstance(value.get(field),str) or len(value[field]) > maximum:
                raise ValueError('版本说明字段无效')
        datetime.fromisoformat(value['published_at'])
        if any(key in value for key in ('installer','archive','parts','signature','files')):
            raise ValueError('版本信息不得作为可执行安装授权')
        return value
    progress({'status':'正在后台检测魔搭社区主程序版本（不影响语音资源）'})
    failures = []
    endpoints = [('魔搭社区', URL), ('GitHub', f'https://api.github.com/repos/{REPOSITORY}/releases/latest')]
    for source, url in endpoints:
        try:
            # Version hints never authorize executable operations.
            configured = [{'name':source,'prefix':'','connect_timeout':3,'read_timeout':3,'retries':0}]
            def validate_response(body):
                if source == '魔搭社区':
                    return validate(body)
                release = json.loads(body)
                if (not isinstance(release, dict) or release.get('draft') is not False
                        or release.get('prerelease') is not False):
                    raise ValueError('GitHub 正式版本信息无效')
                tag = release.get('tag_name')
                if not isinstance(tag, str) or not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
                    raise ValueError('GitHub 主程序版本无效')
                title, notes = release.get('name') or tag, release.get('body') or ''
                if not isinstance(title, str) or not isinstance(notes, str):
                    raise ValueError('GitHub 更新说明格式无效')
                return validate({'schema':1, 'component':'main', 'channel':'stable', 'version':tag[1:],
                    'title':title[:512], 'notes':notes[:65536], 'published_at':release.get('published_at')})
            async with asyncio.timeout(6):
                body = await fetch_small(url,configured,limit=1024*1024 if source == 'GitHub' else 64*1024,
                    validator=validate_response)
            value = validate_response(body)
            result['main'] = {key:value[key] for key in ('version','title','notes','published_at','channel')}
            result['main'].update(source=source,state='update_available' if
                version_tuple(value['version']) > version_tuple(VERSION) else 'current')
            if failures:
                result['main']['source_note'] = ('固定版本文件暂不可用，已读取魔搭上的兼容文件名'
                    if source == '魔搭社区' else '魔搭版本文件暂不可用，已从 GitHub 获取版本信息')
            result['errors'] = {}
            return result
        except (OSError,ValueError,KeyError,TypeError,TimeoutError,aiohttp.ClientError) as error:
            failures.append(f'{source}: {type(error).__name__}: {error}')
            # v2.0.0 was uploaded under the delivery filename. Only on 404, read
            # that known alias; future releases still publish main-latest.json.
            if url == URL and 'HTTP 404' in str(error):
                endpoints.insert(1, ('魔搭社区', ENTRY + f'TachiTalk-v{VERSION}-main-latest.json'))
            result['main'] = {'state':'error','version':None,'source':'魔搭社区'}
            result['errors']['main'] = '主程序版本检测暂不可用：' + '; '.join(failures)
    return result
