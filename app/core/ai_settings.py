"""AI服务运行配置：每轮使用快照，界面任务只有模型列表和连接测试两个槽。"""
from dataclasses import dataclass, field, replace
from threading import Lock

import config
from app.core.voice_settings import CommandResult, http_url


@dataclass(frozen=True, slots=True)
class AIOptions:
    provider: str = 'deepseek'
    base_url: str = ''
    api_key: str = field(default='', repr=False)
    model: str = ''
    require_key: bool = True
    temperature: float = .7
    max_tokens: int = 2048
    reply_length: int = 0  # 正文建议字数；0沿用默认短回复，不截断双语文本。
    timeout: int = 60
    retries: int = 2
    streaming: bool = True
    chat_path: str = ''  # 入口自检/旧配置可显式指定，面板按服务类型自动选择路径。

    def reply_parts(self, default):
        return max(default, (self.reply_length + 119) // 120 + 1) if self.reply_length else default

    def validate(self, *, for_models=False):
        if self.provider not in ('deepseek', 'openai', 'custom'):
            raise ValueError('不支持的AI接口类型')
        base = self.base_url.strip().rstrip('/')
        http_url(base, 'AI基础地址')
        if any(base.endswith(path) for path in ('/chat/completions', '/models')) or '?' in base or '#' in base:
            raise ValueError('请填写API基础地址，例如https://api.example.com/v1，不要填写完整请求路径或查询参数')
        if (self.require_key or self.provider != 'custom') and not self.api_key.strip():
            raise ValueError(self.key_guide('缺少'))
        if '\r' in self.api_key or '\n' in self.api_key:
            raise ValueError('API Key中不能包含换行，请只复制完整的一行密钥')
        if not for_models and not self.model.strip():
            raise ValueError('AI模型名称为空，请获取模型列表后选择，或手动填写模型ID')
        if not 0 <= self.temperature <= 2 or not 128 <= self.max_tokens <= 32768:
            raise ValueError('温度须为0–2，最大输出须为128–32768 tokens')
        if type(self.reply_length) is not int or not 0 <= self.reply_length <= 2000:
            raise ValueError('回复长度须为0–2000字，0表示不额外限制')
        if not 5 <= self.timeout <= 300 or not 0 <= self.retries <= 5:
            raise ValueError('请求超时须为5–300秒，重试次数须为0–5')

    def key_guide(self, reason='无效或过期的'):
        if self.provider == 'deepseek':
            url = 'https://platform.deepseek.com/api_keys'
        elif self.provider == 'openai':
            url = 'https://platform.openai.com/api-keys（官方服务）或兼容服务提供商的控制台'
        else:
            url = '自定义服务提供商的官网控制台'
        return (f'{reason}LLM API Key，用于生成回复。前往{url} → API密钥 → 创建新密钥，'
                '填写控制面板的AI服务页API Key。自建无鉴权接口可关闭需要Key。')

    @property
    def chat_url(self):
        base = self.base_url.strip().rstrip('/')
        if self.chat_path:
            return base + self.chat_path
        if self.provider == 'deepseek':
            if base.endswith('/v1'):
                base = base[:-3]
            return base + ('/chat/completions' if base.endswith('/beta') else '/beta/chat/completions')
        return base + '/chat/completions'

    @property
    def models_url(self):
        base = self.base_url.strip().rstrip('/')
        if self.provider == 'deepseek' and base.endswith('/beta'):
            base = base[:-5]
        return base + '/models'


@dataclass(frozen=True, slots=True)
class AIState:
    options: AIOptions
    revision: int = 0
    phase: str = 'idle'
    detail: str = '尚未验证当前配置'


@dataclass(frozen=True, slots=True)
class AICommand:
    id: int
    state: AIState


def provider_defaults(settings):
    return {
        'deepseek': AIOptions(base_url=settings.llm_base_url, chat_path=settings.llm_chat_path,
                              model=settings.llm_model),
        'openai': AIOptions(provider='openai', base_url='https://api.openai.com/v1'),
        'custom': AIOptions(provider='custom'),
    }


class AISettings:
    def __init__(self, settings):
        self.defaults = provider_defaults(settings)
        config.register_runtime_key(self.defaults['deepseek'].api_key)
        self._lock = Lock()
        self._state = AIState(self.defaults['deepseek'])
        self._commands, self._serial = {}, 0
        self._results = {name: CommandResult() for name in ('models', 'test')}

    def snapshot(self):
        with self._lock:
            return self._state

    def update(self, options):
        config.register_runtime_key(options.api_key)
        with self._lock:
            old = self._state
            if options == old.options:
                return
            self._state = AIState(options, old.revision + 1, 'idle', '配置已更改，等待验证')
            self._commands.clear()  # 配置变化立即作废旧测试；不会让慢响应覆盖新配置。
            self._results = {name: CommandResult() for name in ('models', 'test')}

    def health(self, revision, phase, detail):
        with self._lock:
            if self._state.revision == revision:
                self._state = replace(self._state, phase=phase, detail=config.redact(detail))

    def request(self, name):
        if name not in self._results:
            raise ValueError('未知AI设置操作')
        with self._lock:
            self._serial += 1
            command = AICommand(self._serial, self._state)
            self._commands[name] = command
            self._results[name] = CommandResult(command.id, running=True)
            return command.id

    def commands(self):
        with self._lock:
            return dict(self._commands)

    def result(self, name):
        with self._lock:
            return self._results[name]

    def complete(self, name, id, value=None, error=''):
        with self._lock:
            command = self._commands.get(name)
            if command is not None and command.id == id and command.state.revision == self._state.revision:
                self._results[name] = CommandResult(id, value, config.redact(error))
                return True
            return False
