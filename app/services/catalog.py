"""兼容音频接口的模型目录；不把失败替换成编造的模型列表。"""
import json

import aiohttp

from app.core.models import StageError


async def fetch_asr_models(session, options):
    options.validate(for_models=True)
    if options.provider == 'whisper':
        # faster-whisper官方模型标识；列目录不会下载模型权重。
        return ('tiny', 'base', 'small', 'medium', 'large-v3', 'large-v3-turbo')
    headers = {'Authorization': f'Bearer {options.api_key}'} if options.api_key else {}
    try:
        async with session.get(options.models_url, headers=headers, allow_redirects=False,
                               timeout=aiohttp.ClientTimeout(total=min(options.timeout, 30))) as response:
            if response.status != 200:
                raise StageError.http('ASR', response.status)
            body = bytearray()
            async for block in response.content.iter_chunked(8192):
                body.extend(block)
                if len(body) > 1024 * 1024:
                    raise StageError('ASR', '模型列表超过1MiB上限')
            result = json.loads(body)
        items = result.get('data', result.get('models')) if isinstance(result, dict) else result
        if not isinstance(items, list):
            raise StageError('ASR', '模型列表需返回data数组，每项含id；也支持models字符串数组')
        names = []
        for item in items:
            name = item.get('id') if isinstance(item, dict) else item
            if isinstance(name, str) and 0 < len(name) <= 256 and name not in names:
                names.append(name)
            if len(names) >= 500:
                break
        selected = [name for name in names if any(word in name.lower() for word in ('sensevoice', 'speechasr', 'asr', 'whisper', 'transcrib'))]
        if options.provider == 'silicon':
            names = selected
        elif selected:
            names = selected
        if not names:
            raise StageError('ASR', '服务未返回可识别的ASR模型，可在识别模型框手动填写服务文档中的模型ID')
        return tuple(names)
    except StageError:
        raise
    except (aiohttp.ClientError, TimeoutError) as error:
        raise StageError('ASR', f'获取模型失败（{type(error).__name__}），请检查地址、Key和网络；模型也可手动填写') from error
    except (ValueError, TypeError) as error:
        raise StageError('ASR', '模型列表不是有效JSON，可手动填写识别模型') from error
