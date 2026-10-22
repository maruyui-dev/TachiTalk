"""模型发现及真实短回复测试；启动预检不生成回复，手动测试不进入对话历史。"""
import asyncio
from contextlib import aclosing
from datetime import datetime
import json
from time import perf_counter
from types import SimpleNamespace

import aiohttp

from app.core.models import CaptionPart, SpeechPart, StageError
from app.services.llm import LLMClient


async def fetch_models(session, options):
    options.validate(for_models=True)
    headers = {'Authorization': f'Bearer {options.api_key}'} if options.api_key else {}
    try:
        async with session.get(options.models_url, headers=headers, allow_redirects=False,
                               timeout=aiohttp.ClientTimeout(total=min(options.timeout, 30))) as response:
            if response.status != 200:
                if response.status in (401, 403):
                    raise StageError('LLM', options.key_guide(), response.status)
                raise StageError.http('LLM', response.status)
            body = bytearray()
            async for block in response.content.iter_chunked(8192):
                body.extend(block)
                if len(body) > 1024 * 1024:
                    raise StageError('LLM', '模型列表超过1MiB上限')
        result = json.loads(body)
        items = result.get('data') if isinstance(result, dict) else None
        if not isinstance(items, list):
            raise StageError('LLM', '模型列表必须是含data数组的JSON，每项包含id')
        names = []
        for item in items:
            name = item.get('id') if isinstance(item, dict) else None
            if isinstance(name, str) and name.strip() and len(name) <= 256 and name not in names:
                names.append(name)
            if len(names) >= 500:
                break
        if not names:
            raise StageError('LLM', '服务未返回可用模型，请确认账户权限，或手动填写服务支持的模型ID')
        return tuple(names)
    except (aiohttp.ClientError, TimeoutError) as error:
        raise StageError('LLM', f'获取模型失败（{type(error).__name__}），请检查地址、Key和网络') from error
    except (ValueError, UnicodeError) as error:
        raise StageError('LLM', '模型列表不是有效JSON') from error


async def check_configuration(session, options):
    options.validate()
    try:
        names = await fetch_models(session, options)
    except StageError as error:
        if options.provider == 'custom' and error.status == 404:
            return '自定义服务不提供模型列表，配置已检查；生成能力将在测试连接或实际对话时验证'
        raise
    if options.model not in names:
        raise StageError('LLM', '所选模型不在当前服务返回的模型列表中，请获取列表后重新选择', 404)
    return '模型列表与鉴权检查通过；点击测试连接可验证双语结构化生成能力'


async def test_connection(session, settings, state, expressions=None, audio=None):
    # 独立客户端拥有独立历史；测试不会调用ASR/TTS，也不会改动桌宠的上下文。
    options = state.options
    client = LLMClient(session, settings, ai=SimpleNamespace(snapshot=lambda: state), expressions=expressions, audio=audio)
    started = perf_counter()
    speech, captions = {}, {}
    async with aclosing(client.events('这是连接测试。请只用一组parts，日语和气泡文本各一句简短问候，不超过十个字。')) as stream:
        async for event in stream:
            if isinstance(event, SpeechPart):
                speech[event.part_id] = event.japanese
            elif isinstance(event, CaptionPart):
                captions[event.part_id] = event.chinese
    if not speech or not captions:
        raise StageError('LLM', '连接已返回，但缺少有效日语配音或气泡文本，当前模型未满足桌宠回复协议')
    return {'latency_ms': round((perf_counter() - started) * 1000), 'model': options.model,
            'time': datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S'),
            'japanese': ''.join(speech[index] for index in sorted(speech)),
            'caption': ''.join(captions[index] for index in sorted(captions)),
            'streaming': options.streaming}


async def run_ai_commands(session, settings, ai, ui, inputs=None, expressions=None, audio=None):
    tasks = {}

    async def perform(name, command):
        started = perf_counter()
        try:
            value = (await fetch_models(session, command.state.options) if name == 'models' else
                     await test_connection(session, settings, command.state, expressions, audio))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            status = error.status if isinstance(error, StageError) else None
            message = f'HTTP {status}：{error}' if status else str(error)
            details = {'latency_ms': round((perf_counter() - started) * 1000),
                       'time': datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S'), 'status': status}
            accepted = ai.complete(name, command.id, value=details if name == 'test' else None, error=message)
            if accepted and name == 'test':
                ai.health(command.state.revision, 'error', message)
                if inputs is not None and status in (400, 401, 402, 403, 404, 422):
                    inputs.block_service('LLM')
            ui.error(error if isinstance(error, StageError) else StageError('AI设置', str(error)))
        else:
            accepted = ai.complete(name, command.id, value=value)
            if accepted and name == 'test':
                ai.health(command.state.revision, 'ready', '连接测试通过，双语结构化生成可用')
                if inputs is not None:
                    inputs.invalidate_service('LLM')
                    inputs.set_service_ready('LLM')

    try:
        while True:
            commands = ai.commands()
            for name, (id, task) in tuple(tasks.items()):
                if name not in commands or commands[name].id != id:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    del tasks[name]
            for name, command in commands.items():
                if name not in tasks:
                    tasks[name] = (command.id, asyncio.create_task(perform(name, command), name=f'ai-command-{name}'))
            await asyncio.sleep(.05)
    finally:
        for _, task in tasks.values():
            task.cancel()
        await asyncio.gather(*(task for _, task in tasks.values()), return_exceptions=True)
