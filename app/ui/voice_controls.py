"""语音服务与播放卡片：Qt只维护配置，所有设备和网络操作交给后台循环。"""
from contextlib import ExitStack
from dataclasses import replace
from config import Settings

from PySide6.QtCore import QObject, QSignalBlocker, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSlider, QSpinBox, QWidget,
)

from app.core.voice_settings import ASROptions, TTSOptions, default_voice_profiles


class VoiceControls(QObject):
    ASR_PROVIDERS = ('silicon', 'openai', 'whisper', 'custom')
    TTS_PROVIDERS = ('gpt_sovits', 'system', 'openai', 'custom')
    LANGUAGES = ('auto', 'zh', 'en', 'ja')

    def __init__(self, panel):
        super().__init__(panel)
        self.panel, self.voices, self.inputs = panel, None, None
        self.widgets = {}
        groups = {
            QComboBox: ('asrProviderCombo', 'asrModelCombo', 'asrLanguageCombo',
                        'ttsProviderCombo', 'systemVoiceCombo', 'speakerCombo'),
            QLineEdit: ('asrApiKeyEdit', 'asrUrlEdit', 'asrModelsUrlEdit', 'whisperPathEdit',
                        'ttsUrlEdit', 'ttsApiKeyEdit', 'ttsModelEdit', 'ttsVoiceEdit'),
            QCheckBox: ('asrRequireKeyCheck', 'whisperDownloadCheck', 'asrAutoSendCheck',
                        'trimSilenceCheck', 'ttsRequireKeyCheck', 'autoReadCheck', 'interruptSpeechCheck'),
            QSpinBox: ('asrTimeoutSpin', 'ttsTimeoutSpin'),
            QPlainTextEdit: ('asrDraftEdit', 'speechTestEdit'),
            QPushButton: ('refreshAsrModelsButton', 'asrSendButton', 'asrDiscardButton',
                         'refreshSystemVoicesButton', 'playSampleButton', 'scanSpeakerButton'),
            QLabel: ('asrServiceStatus', 'ttsServiceStatus', 'playbackStatus', 'outputVolumeSliderValue'),
            QSlider: ('outputVolumeSlider',),
        }
        for kind, names in groups.items():
            for name in names:
                widget = panel.findChild(kind, name)
                if widget is None:
                    raise RuntimeError(f'语音页面缺少控件：{name}')
                self.widgets[name] = widget
        self._asr_cache, self._tts_cache = {}, {}
        self._asr_provider, self._tts_provider = 'silicon', 'gpt_sovits'
        self._seen = {}
        self._requested = {}
        self._draft_version = -1
        self._asr_message = self._tts_message = ''
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.model_timer = QTimer(self)
        self.model_timer.setSingleShot(True)
        self.model_timer.setInterval(400)
        self.model_timer.timeout.connect(self.request_models)
        self.w('asrProviderCombo').currentIndexChanged.connect(self.change_asr_provider)
        self.w('ttsProviderCombo').currentIndexChanged.connect(self.change_tts_provider)
        for name in ('asrApiKeyEdit', 'asrUrlEdit', 'asrModelsUrlEdit'):
            self.w(name).editingFinished.connect(self.asr_connection_changed)
        for name in ('asrRequireKeyCheck',):
            self.w(name).toggled.connect(self.asr_connection_changed)
        for name in ('whisperDownloadCheck', 'asrAutoSendCheck', 'trimSilenceCheck'):
            self.w(name).toggled.connect(self.save_asr)
        for name in ('asrTimeoutSpin',):
            self.w(name).valueChanged.connect(self.save_asr)
        self.w('whisperPathEdit').editingFinished.connect(self.save_asr)
        self.w('asrModelCombo').currentIndexChanged.connect(self.save_asr)
        self.w('asrModelCombo').lineEdit().editingFinished.connect(self.save_asr)
        self.w('asrLanguageCombo').currentIndexChanged.connect(self.save_asr)
        for name in ('ttsUrlEdit', 'ttsApiKeyEdit', 'ttsModelEdit', 'ttsVoiceEdit'):
            self.w(name).editingFinished.connect(self.save_tts)
        for name in ('autoReadCheck', 'interruptSpeechCheck', 'ttsRequireKeyCheck'):
            self.w(name).toggled.connect(self.save_tts)
        self.w('ttsTimeoutSpin').valueChanged.connect(self.save_tts)
        self.w('systemVoiceCombo').currentIndexChanged.connect(self.save_tts)
        self.w('refreshAsrModelsButton').clicked.connect(self.request_models)
        self.w('refreshSystemVoicesButton').clicked.connect(self.request_voices)
        self.w('scanSpeakerButton').clicked.connect(self.request_speakers)
        self.w('playSampleButton').clicked.connect(self.toggle_preview)
        self.w('speakerCombo').currentIndexChanged.connect(self.save_output)
        self.w('outputVolumeSlider').valueChanged.connect(self.save_output)
        self.w('asrSendButton').clicked.connect(self.send_draft)
        self.w('asrDiscardButton').clicked.connect(self.discard_draft)
        self.w('asrDraftEdit').textChanged.connect(self.refresh_draft_actions)
        self.w('interruptSpeechCheck').setToolTip(
            '开启后允许说话打断：ASR确认新的有效文字后停止旧回复。外放回声无法完全靠文字过滤，建议使用耳机。')
        self.w('autoReadCheck').setToolTip('从下一轮回复开始生效；关闭后仅显示回复文字，不调用TTS。')
        self.w('trimSilenceCheck').setToolTip('裁去录音片段首尾静音，保留约100毫秒余量，避免切掉发音。')
        self.w('playSampleButton').setToolTip('直接使用当前TTS服务、输出设备和音量，不经过ASR或LLM。')
        panel.closing.connect(self.close)
        self.show_groups()
        for widget in self.widgets.values():
            if not isinstance(widget, QLabel):
                widget.setEnabled(False)

    def w(self, name):
        return self.widgets[name]

    def bind_runtime(self, voices, inputs):
        self.voices, self.inputs = voices, inputs
        snapshot = voices.snapshot()
        self._asr_cache, self._tts_cache = default_voice_profiles(Settings())
        self._asr_cache[snapshot.asr.provider] = snapshot.asr
        self._tts_cache[snapshot.tts.provider] = snapshot.tts
        for widget in self.widgets.values():
            widget.setEnabled(True)
        with QSignalBlocker(self.w('outputVolumeSlider')):
            self.w('outputVolumeSlider').setValue(snapshot.output.volume)
        self.fill_asr(snapshot.asr)
        self.fill_tts(snapshot.tts)
        self.fill_speakers(())
        self.apply_preferences()
        self.timer.start()
        self.request_models()
        self.request_speakers()

    def blockers(self, names):
        stack = ExitStack()
        for name in names:
            stack.enter_context(QSignalBlocker(self.w(name)))
        return stack

    def fill_asr(self, options):
        names = ('asrProviderCombo', 'asrApiKeyEdit', 'asrUrlEdit', 'asrModelsUrlEdit', 'asrModelCombo',
                 'asrLanguageCombo', 'asrAutoSendCheck', 'trimSilenceCheck', 'asrRequireKeyCheck',
                 'asrTimeoutSpin', 'whisperPathEdit', 'whisperDownloadCheck')
        with self.blockers(names):
            self.w('asrProviderCombo').setCurrentIndex(self.ASR_PROVIDERS.index(options.provider))
            for name, value in (('asrApiKeyEdit', options.api_key), ('asrUrlEdit', options.url),
                                ('asrModelsUrlEdit', options.models_url), ('whisperPathEdit', options.local_path)):
                self.w(name).setText(value)
            self.w('asrModelCombo').clear()
            if options.model:
                self.w('asrModelCombo').addItem(options.model)
            self.w('asrLanguageCombo').setCurrentIndex(self.LANGUAGES.index(options.language))
            self.w('asrTimeoutSpin').setValue(options.timeout)
            for name, value in (('asrRequireKeyCheck', options.require_key), ('asrAutoSendCheck', options.auto_send),
                                ('trimSilenceCheck', options.trim_silence), ('whisperDownloadCheck', options.allow_download)):
                self.w(name).setChecked(value)
        self._asr_provider = options.provider
        self.show_groups()

    def fill_tts(self, options):
        names = ('ttsProviderCombo', 'ttsUrlEdit', 'ttsApiKeyEdit', 'ttsModelEdit', 'ttsVoiceEdit',
                 'ttsRequireKeyCheck', 'autoReadCheck', 'interruptSpeechCheck', 'ttsTimeoutSpin', 'systemVoiceCombo')
        with self.blockers(names):
            self.w('ttsProviderCombo').setCurrentIndex(self.TTS_PROVIDERS.index(options.provider))
            for name, value in (('ttsUrlEdit', options.url), ('ttsApiKeyEdit', options.api_key),
                                ('ttsModelEdit', options.model), ('ttsVoiceEdit', options.voice)):
                self.w(name).setText(value)
            self.w('ttsRequireKeyCheck').setChecked(options.require_key)
            self.w('autoReadCheck').setChecked(options.auto_read)
            self.w('interruptSpeechCheck').setChecked(options.interrupt)
            self.w('ttsTimeoutSpin').setValue(options.timeout)
            self.w('systemVoiceCombo').setCurrentIndex(self.w('systemVoiceCombo').findData(options.voice))
        self._tts_provider = options.provider
        self.show_groups()

    def show_groups(self):
        local = self._asr_provider == 'whisper'
        for name, visible in (('asrRemoteConfig', self._asr_provider in ('openai', 'custom')),
                              ('asrLocalConfig', local), ('asrReviewGroup', not self.w('asrAutoSendCheck').isChecked()),
                              ('ttsConnectionGroup', self._tts_provider != 'system'),
                              ('ttsSystemGroup', self._tts_provider == 'system')):
            self.panel.findChild(QWidget, name).setVisible(visible)
        self.w('asrApiKeyEdit').setVisible(not local)
        self.w('asrApiKeyEdit').setPlaceholderText(
            '输入硅基流动 API Key' if self._asr_provider == 'silicon' else '填写所选服务的API Key；不会沿用其他服务的Key')
        self.panel.findChild(QLabel, 'asrApiKeyCaption').setVisible(not local)
        self.w('asrLanguageCombo').setEnabled(self.voices is not None and self._asr_provider != 'silicon')
        self.w('asrLanguageCombo').setToolTip(
            '硅基流动当前ASR接口未公开识别语言参数，使用自动检测。其他服务可指定语言。'
            if self._asr_provider == 'silicon' else '向兼容接口发送语言代码，或用于本地Whisper。')
        for name in ('ttsModelEdit', 'ttsVoiceEdit'):
            visible = self._tts_provider != 'gpt_sovits'
            self.w(name).setVisible(visible)
            self.panel.findChild(QLabel, name + 'Caption').setVisible(visible)

    def change_asr_provider(self, index):
        if self.voices is None:
            return
        options = replace(self._asr_cache[self.ASR_PROVIDERS[index]],
                          auto_send=self.w('asrAutoSendCheck').isChecked(),
                          trim_silence=self.w('trimSilenceCheck').isChecked())
        self._asr_message = ''
        self.fill_asr(options)
        self.save_asr()
        self.request_models()

    def change_tts_provider(self, index):
        if self.voices is None:
            return
        options = replace(self._tts_cache[self.TTS_PROVIDERS[index]],
                          auto_read=self.w('autoReadCheck').isChecked(),
                          interrupt=self.w('interruptSpeechCheck').isChecked())
        self._tts_message = ''
        self.fill_tts(options)
        self.save_tts()
        if options.provider == 'system':
            self.request_voices()

    def apply_preferences(self):
        snapshot = self.voices.snapshot()
        self.inputs.set_voice_preferences(auto_read=snapshot.tts.auto_read,
                                          auto_send=snapshot.asr.auto_send, interrupt=snapshot.tts.interrupt)
        self.inputs.configure_audio(trim_silence=snapshot.asr.trim_silence)

    def read_asr_options(self):
        return ASROptions(
            provider=self._asr_provider, url=self.w('asrUrlEdit').text().strip(),
            models_url=self.w('asrModelsUrlEdit').text().strip(), api_key=self.w('asrApiKeyEdit').text().strip(),
            require_key=self.w('asrRequireKeyCheck').isChecked(), model=self.w('asrModelCombo').currentText().strip(),
            language='auto' if self._asr_provider == 'silicon' else self.LANGUAGES[self.w('asrLanguageCombo').currentIndex()],
            auto_send=self.w('asrAutoSendCheck').isChecked(), trim_silence=self.w('trimSilenceCheck').isChecked(),
            timeout=self.w('asrTimeoutSpin').value(), local_path=self.w('whisperPathEdit').text().strip(),
            allow_download=self.w('whisperDownloadCheck').isChecked())

    def save_asr(self, *_):
        if self.voices is None:
            return
        options = self.read_asr_options()
        self._asr_cache[options.provider] = options
        self.voices.set_asr(options)
        self.apply_preferences()
        self.show_groups()

    def asr_connection_changed(self, *_):
        self.save_asr()
        if self.voices is not None:
            self.model_timer.start()

    def read_tts_options(self):
        return TTSOptions(
            provider=self._tts_provider, url=self.w('ttsUrlEdit').text().strip(),
            api_key=self.w('ttsApiKeyEdit').text().strip(), require_key=self.w('ttsRequireKeyCheck').isChecked(),
            model=self.w('ttsModelEdit').text().strip(),
            voice=(self.w('systemVoiceCombo').currentData() or '') if self._tts_provider == 'system'
                  else self.w('ttsVoiceEdit').text().strip(),
            auto_read=self.w('autoReadCheck').isChecked(), interrupt=self.w('interruptSpeechCheck').isChecked(),
            timeout=self.w('ttsTimeoutSpin').value())

    def save_tts(self, *_):
        if self.voices is None:
            return
        options = self.read_tts_options()
        self._tts_cache[options.provider] = options
        self.voices.set_tts(options)
        self.apply_preferences()

    def request_models(self):
        self.model_timer.stop()
        if self.voices is not None:
            self.save_asr()
            self._asr_message = ''
            self._requested['models'] = self.voices.request('models', self.voices.snapshot().asr)

    def request_voices(self):
        if self.voices is not None:
            self._tts_message = ''
            self._requested['voices'] = self.voices.request('voices')

    def request_speakers(self):
        if self.voices is not None:
            self._requested['speakers'] = self.voices.request('speakers')

    def fill_speakers(self, devices):
        selected = self.voices.snapshot().output.device
        combo = self.w('speakerCombo')
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem('系统默认扬声器', None)
            for device in devices:
                combo.addItem(device.label, device.index)
            if selected is not None and combo.findData(selected) < 0:
                combo.addItem(f'配置的设备 #{selected} · 请重新获取并确认', selected)
            combo.setCurrentIndex(max(0, combo.findData(selected)))

    def save_output(self, *_):
        volume = self.w('outputVolumeSlider').value()
        self.w('outputVolumeSliderValue').setText(f'{volume}%')
        if self.voices is not None:
            self.voices.set_output(device=self.w('speakerCombo').currentData(), volume=volume)

    def toggle_preview(self):
        if self.voices is None:
            return
        if self.voices.result('preview').running:
            self._requested['preview'] = self.voices.request('preview', None)
        else:
            self.save_tts()
            text = self.w('speechTestEdit').toPlainText().strip()
            try:
                if not 1 <= len(text) <= 500:
                    raise ValueError('试听文字请输入1–500字；使用当前所选TTS直接合成')
                options = self.voices.snapshot().tts
                options.validate()
            except ValueError as error:
                self.w('playbackStatus').setText(str(error))
                return
            self._requested['preview'] = self.voices.request('preview', (text, options))
        self.refresh()

    def send_draft(self):
        if self.voices is not None:
            accepted, message = self.inputs.submit_text(self.w('asrDraftEdit').toPlainText(), from_asr=True)
            self._asr_message = message
            if accepted:
                self.discard_draft()

    def discard_draft(self):
        if self.voices is not None:
            self.voices.set_draft('')
            self.w('asrDraftEdit').clear()
            self.inputs.set_review_pending(False)

    def refresh_draft_actions(self):
        if self.inputs is not None:
            state = self.inputs.snapshot()
            self.w('asrSendButton').setEnabled(bool(self.w('asrDraftEdit').toPlainText().strip())
                                             and self.inputs.reply_ready() and (not state.busy or state.can_interrupt))

    def refresh(self):
        if self.voices is None:
            return
        for name in ('models', 'speakers', 'voices', 'preview'):
            result = self.voices.result(name)
            stamp = (result.id, result.running)
            if not result.id or self._seen.get(name) == stamp:
                continue
            self._seen[name] = stamp
            if name == 'models':
                self.w('refreshAsrModelsButton').setEnabled(not result.running)
                if result.running:
                    self._asr_message = '正在获取当前服务的识别模型…'
                elif result.id == self._requested.get(name):
                    if result.error:
                        self._asr_message = result.error + '；若服务不提供模型列表，请手动填写模型ID。'
                    else:
                        options = self.voices.snapshot().asr
                        with QSignalBlocker(self.w('asrModelCombo')):
                            self.w('asrModelCombo').clear()
                            self.w('asrModelCombo').addItems(result.value)
                            self.w('asrModelCombo').setCurrentText(options.model if options.model in result.value else result.value[0])
                        self.save_asr()
                        self._asr_message = f'已获取 {len(result.value)} 个模型；模型也可手动填写。'
            elif name == 'speakers':
                self.w('scanSpeakerButton').setEnabled(not result.running)
                self.w('scanSpeakerButton').setText('正在获取…' if result.running else '获取扬声器设备')
                if not result.running:
                    if not result.error:
                        self.fill_speakers(result.value)
                    self.w('playbackStatus').setText(result.error or f'已获取 {len(result.value)} 个扬声器输出端点。')
            elif name == 'voices':
                self.w('refreshSystemVoicesButton').setEnabled(not result.running)
                if result.running:
                    self._tts_message = '正在获取系统音色…'
                elif result.id == self._requested.get(name):
                    if result.error:
                        self._tts_message = result.error
                    else:
                        selected = self._tts_cache['system'].voice
                        with QSignalBlocker(self.w('systemVoiceCombo')):
                            self.w('systemVoiceCombo').clear()
                            self.w('systemVoiceCombo').addItem('请选择已安装的音色', '')
                            for voice in result.value:
                                self.w('systemVoiceCombo').addItem(f"{voice['name']} · {voice['language']}", voice['name'])
                            self.w('systemVoiceCombo').setCurrentIndex(max(0, self.w('systemVoiceCombo').findData(selected)))
                        self._tts_message = '请选择音色；日语回复需要可朗读日语的音色，可在Windows语音设置中安装。'
            else:
                self.w('playSampleButton').setText('结束' if result.running else '试听')
                self.w('playbackStatus').setText('正在合成或播放试听，再次点击结束。' if result.running else result.error or str(result.value))
        text, version = self.voices.draft()
        if version != self._draft_version:
            self._draft_version = version
            self.w('asrDraftEdit').setPlainText(text)
        self.refresh_draft_actions()
        asr_hint = {
            'silicon': '硅基流动使用自动检测语言。Key：cloud.siliconflow.cn → API密钥 → 新建密钥。',
            'openai': '填写转录地址、模型列表地址和Key；语言参数使用zh/en/ja。OpenAI Key：platform.openai.com/api-keys。',
            'whisper': '本地Whisper使用CPU推理；模型常驻子进程，关闭程序时释放。',
            'custom': '自定义服务须兼容OpenAI音频转录：multipart file/model，可选language；返回JSON的text字段。地址、Key及模型由服务提供商给出。',
        }[self._asr_provider]
        tts_hint = {
            'gpt_sovits': 'GPT-SoVITS使用资源管理→音频管理中启用的参考音频；整轮共用一条参考。',
            'system': '使用系统已安装的音色，不调用线上TTS；输出设备和音量仍由本页控制。',
            'openai': '填写语音接口地址、Key、模型和音色ID。OpenAI Key：platform.openai.com/api-keys → Create new secret key。',
            'custom': '自定义TTS须兼容OpenAI语音接口：JSON model/input/voice，支持response_format=wav并返回WAV。',
        }[self._tts_provider]
        for service, options, hint, message, label in (
            ('ASR', self.voices.snapshot().asr, asr_hint, self._asr_message, 'asrServiceStatus'),
            ('TTS', self.voices.snapshot().tts, tts_hint, self._tts_message, 'ttsServiceStatus')):
            try:
                options.validate()
                validation = ('已就绪' if self.inputs.service_ready(service) else
                              '配置不可用，请查看运行日志后修改配置' if self.inputs.service_blocked(service) else '等待验证或首次调用')
            except ValueError as error:
                validation = str(error)
            self.w(label).setText('\n'.join(value for value in (message, validation, hint) if value))

    def close(self):
        self.timer.stop()
        self.model_timer.stop()
        if self.voices is not None:
            self.voices.request('preview', None)
