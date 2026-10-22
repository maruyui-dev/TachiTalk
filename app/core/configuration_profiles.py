"""配置文件中各服务的独立配置档；只校验数据，不验证联网可用性。"""
from dataclasses import fields
import math

from app.core.ai_settings import AIOptions
from app.core.voice_settings import ASROptions, TTSOptions, http_url

PROFILE_TYPES = {'ai': (AIOptions, ('deepseek', 'openai', 'custom')),
                 'asr': (ASROptions, ('silicon', 'openai', 'whisper', 'custom')),
                 'tts': (TTSOptions, ('gpt_sovits', 'system', 'openai', 'custom'))}


def parse_profiles(data, *, allow_incomplete=False):
    if not isinstance(data, dict) or set(data) != set(PROFILE_TYPES):
        raise ValueError('服务配置档不完整')
    result = {}
    for stage, (kind, providers) in PROFILE_TYPES.items():
        group = data[stage]
        if not isinstance(group, dict) or set(group) != set(providers):
            raise ValueError('服务配置档含有不支持的服务类型')
        result[stage] = {}
        for name, values in group.items():
            if stage == 'ai' and isinstance(values, dict) and 'reply_length' not in values:
                values = dict(values, reply_length=0)  # 兼容新增长度选项前导出的配置。
            specs = {field.name: field for field in fields(kind)}
            if not isinstance(values, dict) or set(values) != set(specs):
                raise ValueError('服务配置档字段不完整或含有未知字段')
            for key, value in values.items():
                expected = type(specs[key].default)
                if expected is float:
                    valid = type(value) in (int, float) and -1000000 <= value <= 1000000 and math.isfinite(value)
                else:
                    valid = type(value) is expected
                if not valid or isinstance(value, str) and (len(value) > 16384 or '\x00' in value):
                    raise ValueError('服务配置档字段类型或长度不正确')
            if values['provider'] != name or '\n' in values['api_key'] or '\r' in values['api_key']:
                raise ValueError('服务类型不匹配，或密钥含有换行')
            for key in ('url', 'models_url', 'base_url'):
                if values.get(key) and not allow_incomplete:
                    http_url(values[key], '配置中的服务地址')
            if not 5 <= values['timeout'] <= 300:
                raise ValueError('服务超时须为5–300秒')
            if stage == 'ai' and (not 0 <= values['temperature'] <= 2 or not 128 <= values['max_tokens'] <= 32768
                                  or not 0 <= values['reply_length'] <= 2000
                                  or not 0 <= values['retries'] <= 5):
                raise ValueError('AI生成参数超出允许范围')
            if stage == 'asr' and values['language'] not in ('auto', 'zh', 'en', 'ja'):
                raise ValueError('识别语言不受支持')
            result[stage][name] = kind(**values)
    return result


def check_active_profiles(pages, profiles):
    """活动服务的界面值与独立配置档必须一致，避免载入后用到另一套密钥/地址。"""
    ai, audio = pages['aiPage'], pages['audioPage']
    selected = {
        'ai': PROFILE_TYPES['ai'][1][ai['aiProviderCombo']],
        'asr': PROFILE_TYPES['asr'][1][audio['asrProviderCombo']],
        'tts': PROFILE_TYPES['tts'][1][audio['ttsProviderCombo']],
    }
    specs = {
        'ai': {'base_url': 'baseUrlEdit', 'api_key': 'apiKeyEdit', 'model': 'llmModelCombo',
               'temperature': 'temperatureSpin', 'max_tokens': 'maxTokensSpin', 'timeout': 'timeoutSpin',
               'reply_length': 'replyLengthSpin',
               'retries': 'retrySpin', 'streaming': 'apiStreamingCheck', 'require_key': 'aiRequireKeyCheck'},
        'asr': {'url': 'asrUrlEdit', 'models_url': 'asrModelsUrlEdit', 'api_key': 'asrApiKeyEdit',
                'require_key': 'asrRequireKeyCheck', 'model': 'asrModelCombo', 'auto_send': 'asrAutoSendCheck',
                'trim_silence': 'trimSilenceCheck', 'timeout': 'asrTimeoutSpin',
                'local_path': 'whisperPathEdit', 'allow_download': 'whisperDownloadCheck'},
        'tts': {'url': 'ttsUrlEdit', 'api_key': 'ttsApiKeyEdit', 'require_key': 'ttsRequireKeyCheck',
                'model': 'ttsModelEdit', 'auto_read': 'autoReadCheck', 'interrupt': 'interruptSpeechCheck',
                'timeout': 'ttsTimeoutSpin'},
    }
    for stage, bindings in specs.items():
        if selected[stage] not in profiles[stage]:
            raise ValueError('所选服务缺少对应配置档')
        options = profiles[stage][selected[stage]]
        values = ai if stage == 'ai' else audio
        for attr, field in bindings.items():
            value = values[field].strip() if isinstance(values[field], str) else values[field]
            if attr == 'base_url':
                value = value.rstrip('/')
            if stage == 'ai' and attr == 'require_key' and selected[stage] != 'custom':
                value = True
            if getattr(options, attr) != value:
                raise ValueError('活动服务的界面字段与配置档不一致，请重新保存完整配置')
    if selected['asr'] == 'silicon' and audio['asrLanguageCombo'] != 0:
        raise ValueError('硅基流动识别语言须为自动检测')
    if profiles['asr'][selected['asr']].language != ('auto', 'zh', 'en', 'ja')[audio['asrLanguageCombo']]:
        raise ValueError('识别语言与服务配置档不一致')
    voice = audio['systemVoiceCombo'] if selected['tts'] == 'system' else audio['ttsVoiceEdit'].strip()
    if profiles['tts'][selected['tts']].voice != voice:
        raise ValueError('试听音色与服务配置档不一致')
