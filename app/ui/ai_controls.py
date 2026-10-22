"""AI服务页：更新运行配置、轮询有界任务结果，不在Qt线程发HTTP请求。"""
from contextlib import ExitStack
from dataclasses import replace

from PySide6.QtCore import QObject, QSignalBlocker, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QSpinBox,
)

from app.core.ai_settings import AIOptions


class AIControls(QObject):
    PROVIDERS = ('deepseek', 'openai', 'custom')

    def __init__(self, panel):
        super().__init__(panel)
        self.panel, self.ai, self.inputs = panel, None, None
        self._provider, self._cache, self._models = 'deepseek', {}, {}
        self._seen, self._revision = {}, -1
        self._message = ''
        self.widgets = {}
        for kind, names in {
            QComboBox: ('aiProviderCombo', 'llmModelCombo'),
            QLineEdit: ('baseUrlEdit', 'apiKeyEdit'),
            QSpinBox: ('maxTokensSpin', 'timeoutSpin', 'retrySpin', 'replyLengthSpin'),
            QDoubleSpinBox: ('temperatureSpin',),
            QCheckBox: ('apiStreamingCheck', 'aiRequireKeyCheck'),
            QPushButton: ('refreshModelsButton', 'testConnectionButton'),
            QPlainTextEdit: ('connectionResultEdit',),
            QLabel: ('connectionStateLabel', 'connectionGuide', 'latencyValue', 'testedModelValue',
                     'lastTestValue', 'aiConfigHint', 'aiRequireKeyCaption'),
        }.items():
            for name in names:
                widget = panel.findChild(kind, name)
                if widget is None:
                    raise RuntimeError(f'AI服务页缺少控件：{name}')
                self.widgets[name] = widget
        self.w('llmModelCombo').lineEdit().setPlaceholderText('获取后选择模型，也可手动填写模型ID')
        self.w('aiProviderCombo').currentIndexChanged.connect(self.change_provider)
        self.w('llmModelCombo').currentIndexChanged.connect(self.save)
        self.w('llmModelCombo').lineEdit().editingFinished.connect(self.save)
        for name in ('baseUrlEdit', 'apiKeyEdit'):
            self.w(name).editingFinished.connect(self.save)
        for name in ('temperatureSpin', 'maxTokensSpin', 'timeoutSpin', 'retrySpin', 'replyLengthSpin'):
            self.w(name).valueChanged.connect(self.save)
        for name in ('apiStreamingCheck', 'aiRequireKeyCheck'):
            self.w(name).toggled.connect(self.save)
        self.w('refreshModelsButton').clicked.connect(lambda: self.request('models'))
        self.w('testConnectionButton').clicked.connect(lambda: self.request('test'))
        self.w('testConnectionButton').setToolTip('发送一条短回复验证双语工具输出，会消耗少量所选服务的tokens；不朗读、不加入历史。')
        self.w('apiStreamingCheck').setToolTip('控制HTTP流式传输；关闭后等待完整回复。对话设置中的流式显示控制气泡文字如何呈现。')
        self.w('timeoutSpin').setToolTip('每次请求的总超时；重试可能增加整轮等待时间。')
        self.w('retrySpin').setToolTip('仅在尚未收到回复时重试临时网络错误、限流和部分服务器错误；Key错误和回复中断不自动重发。')
        self.w('maxTokensSpin').setToolTip('模型生成token上限；仍遵守桌宠的分组与文字长度限制。太小可能截断JSON。')
        self.w('replyLengthSpin').setToolTip('整轮气泡正文的建议字数，日语配音保持同义。0沿用默认短回复；模型可能略有偏差，token上限仍生效。')
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        panel.closing.connect(self.timer.stop)
        self.custom_key_visible()
        for widget in self.widgets.values():
            if not isinstance(widget, (QLabel, QPlainTextEdit)):
                widget.setEnabled(False)

    def w(self, name):
        return self.widgets[name]

    def bind_runtime(self, ai, inputs):
        self.ai, self.inputs = ai, inputs
        self._cache = dict(ai.defaults)
        for widget in self.widgets.values():
            widget.setEnabled(True)
        self.fill(ai.snapshot().options)
        self.timer.start()
        self.refresh()

    def fill(self, options):
        with ExitStack() as stack:
            for widget in self.widgets.values():
                stack.enter_context(QSignalBlocker(widget))
            self.w('aiProviderCombo').setCurrentIndex(self.PROVIDERS.index(options.provider))
            self.w('baseUrlEdit').setText(options.base_url)
            self.w('apiKeyEdit').setText(options.api_key)
            self.w('llmModelCombo').clear()
            self.w('llmModelCombo').addItems(self._models.get(options.provider, ()))
            self.w('llmModelCombo').setCurrentText(options.model)
            for name, value in (('temperatureSpin', options.temperature), ('maxTokensSpin', options.max_tokens),
                                ('timeoutSpin', options.timeout), ('retrySpin', options.retries),
                                ('replyLengthSpin', options.reply_length)):
                self.w(name).setValue(value)
            self.w('apiStreamingCheck').setChecked(options.streaming)
            self.w('aiRequireKeyCheck').setChecked(options.require_key)
        self._provider = options.provider
        self.custom_key_visible()

    def custom_key_visible(self):
        for name in ('aiRequireKeyCaption', 'aiRequireKeyCheck'):
            self.w(name).setVisible(self._provider == 'custom')

    def read_options(self):
        base = self.w('baseUrlEdit').text().strip().rstrip('/')
        cached = self._cache.get(self._provider, AIOptions(provider=self._provider))
        return AIOptions(
            provider=self._provider, base_url=base, api_key=self.w('apiKeyEdit').text().strip(),
            model=self.w('llmModelCombo').currentText().strip(),
            require_key=self._provider != 'custom' or self.w('aiRequireKeyCheck').isChecked(),
            temperature=self.w('temperatureSpin').value(), max_tokens=self.w('maxTokensSpin').value(),
            reply_length=self.w('replyLengthSpin').value(),
            timeout=self.w('timeoutSpin').value(), retries=self.w('retrySpin').value(),
            streaming=self.w('apiStreamingCheck').isChecked(), chat_path=cached.chat_path if base == cached.base_url else '')

    def save(self, *_):
        if self.ai is None:
            return
        options = self.read_options()
        self._cache[self._provider] = options
        if options != self.ai.snapshot().options:
            self.ai.update(options)
            self._message = ''
        self.refresh()

    def change_provider(self, index):
        if self.ai is None:
            return
        previous = self.ai.snapshot().options
        options = replace(self._cache[self.PROVIDERS[index]], temperature=previous.temperature,
                          max_tokens=previous.max_tokens, reply_length=previous.reply_length, timeout=previous.timeout,
                          retries=previous.retries, streaming=previous.streaming)
        self.fill(options)
        self.save()

    def request(self, name):
        if self.ai is None:
            return
        self.save()
        try:
            self.ai.snapshot().options.validate(for_models=name == 'models')
        except ValueError as error:
            self._message = str(error)
            self.w('connectionResultEdit').setPlainText(str(error))
        else:
            self._message = ''
            self.ai.request(name)
        self.refresh()

    def refresh(self):
        if self.ai is None:
            return
        state = self.ai.snapshot()
        if state.revision != self._revision:
            self._revision = state.revision
            self._seen.clear()
            self.w('latencyValue').setText('— ms')
            self.w('lastTestValue').setText('尚未测试当前配置')
            self.w('connectionResultEdit').clear()
        self.w('testedModelValue').setText(state.options.model or '尚未选择')
        for name, button, label in (('models', 'refreshModelsButton', '获取模型列表'), ('test', 'testConnectionButton', '测试连接')):
            result = self.ai.result(name)
            self.w(button).setEnabled(not result.running)
            self.w(button).setText(('正在获取…' if name == 'models' else '正在测试…') if result.running else label)
            stamp = (result.id, result.running)
            if not result.id or self._seen.get(name) == stamp or result.running:
                continue
            self._seen[name] = stamp
            if result.error:
                self._message = result.error
                self.w('connectionResultEdit').setPlainText(result.error)
                if name == 'test':
                    value = result.value or {}
                    self.w('lastTestValue').setText(value.get('time', '') + ' · 测试失败')
                    self.w('latencyValue').setText(f"{value['latency_ms']} ms" if 'latency_ms' in value else '— ms')
            elif name == 'models':
                self._models[self._provider] = result.value
                selected = state.options.model or result.value[0]
                with QSignalBlocker(self.w('llmModelCombo')):
                    self.w('llmModelCombo').clear()
                    self.w('llmModelCombo').addItems(result.value)
                    self.w('llmModelCombo').setCurrentText(selected)
                self.save()
                self._message = f'已获取{len(result.value)}个模型；请选用支持工具调用、温度和max_tokens的Chat Completions模型。'
            else:
                value = result.value
                self.w('latencyValue').setText(f"{value['latency_ms']} ms")
                self.w('lastTestValue').setText(value['time'])
                self._message = '测试通过，双语结构化回复可用。'
                self.w('connectionResultEdit').setPlainText(
                    f"模型：{value['model']}\n传输：{'流式' if value['streaming'] else '非流式'}\n"
                    f"请求完成耗时：{value['latency_ms']} ms\n气泡文本：{value['caption']}\n"
                    f"日语配音文本：{value['japanese']}\n测试未调用TTS，也未加入对话历史。")
        state = self.ai.snapshot()
        test = self.ai.result('test')
        if test.running:
            title = '正在测试'
        elif test.error:
            title = '测试失败'
        elif state.phase == 'error':
            title = '连接异常'
        elif test.value:
            title = '连接成功'
        else:
            try:
                state.options.validate()
                title = {'idle': '等待验证', 'checking': '正在检查', 'ready': '配置检查通过', 'error': '连接异常'}[state.phase]
            except ValueError:
                title = '等待配置'
        self.w('connectionStateLabel').setText(title)
        phase = 'error' if title in ('测试失败', '连接异常') else 'success' if title == '连接成功' else 'waiting'
        label = self.w('connectionStateLabel')
        if label.property('connectionPhase') != phase:
            label.setProperty('connectionPhase', phase)
            label.style().unpolish(label)
            label.style().polish(label)
        self.w('connectionGuide').setText(state.detail if state.phase == 'error' and not test.running and not test.error
                                         else self._message or state.detail)
        try:
            state.options.validate()
            hint = {'deepseek': 'DeepSeek采用Beta严格工具输出，并关闭思考以降低语音等待时间。',
                    'openai': '使用/v1/chat/completions兼容协议；请填写当前服务的Key，支持手动模型ID。',
                    'custom': '自定义接口需支持Chat Completions工具调用及/models列表；无列表时可手填模型并测试连接。自建无鉴权服务可关闭需要Key。'}[self._provider]
        except ValueError as error:
            hint = str(error)
        self.w('aiConfigHint').setText(hint)
