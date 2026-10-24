"""Display-only main version metadata. It never authorizes executable updates."""
import asyncio
from datetime import datetime
import json
import re
import aiohttp
from app.updates.download import fetch_small
from app.updates.manifest import version_tuple
from app.updates.modelscope import ENTRY
from app.version import VERSION

ENABLED = True  # Public object anonymously verified; see main-feed-live.json evidence.
URL = ENTRY + 'main-latest.json'


async def check(progress=lambda value: None):
    result = {'manifests':{},'errors':{},'main':{'state':'disabled','version':None}}
    if not ENABLED:
        return result
    def validate(body):
        value = json.loads(body)
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
    try:
        # Single fixed public repository file. No release API or fallback service.
        configured = [{'name':'魔搭社区','prefix':'','connect_timeout':3,'read_timeout':3,'retries':0}]
        async with asyncio.timeout(6):
            body = await fetch_small(URL,configured,limit=64*1024,validator=validate)
        value = validate(body)
        result['main'] = {key:value[key] for key in ('version','title','notes','published_at','channel')}
        result['main'].update(source='魔搭社区',state='update_available' if
            version_tuple(value['version']) > version_tuple(VERSION) else 'current')
    except (OSError,ValueError,KeyError,TypeError,TimeoutError,aiohttp.ClientError) as error:
        result['main'] = {'state':'error','version':None,'source':'魔搭社区'}
        result['errors']['main'] = f'魔搭版本检测暂不可用：{type(error).__name__}: {error}'
    return result
