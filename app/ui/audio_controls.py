"""录音设备卡片：控件写入线程安全状态，电平轮询取最新值。"""
from contextlib import ExitStack
import logging

from PySide6.QtCore import QObject, QSignalBlocker, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QComboBox, QKeySequenceEdit, QLabel, QProgressBar, QPushButton, QSlider

from app.ui.recording_hotkey import HoldShortcut


class AudioControls(QObject):
    MODES = ('vad', 'hold', 'toggle')

    def __init__(self, panel):
        super().__init__(panel)
        self.panel, self.inputs = panel, None
        self.device = panel.findChild(QComboBox, 'microphoneCombo')
        self.mode = panel.findChild(QComboBox, 'recordingModeCombo')
        self.shortcut = panel.findChild(QKeySequenceEdit, 'recordingShortcut')
        self.rate = panel.findChild(QComboBox, 'sampleRateCombo')
        self.volume = panel.findChild(QSlider, 'inputVolumeSlider')
        self.volume_label = panel.findChild(QLabel, 'inputVolumeSliderValue')
        self.level = panel.findChild(QProgressBar, 'inputLevel')
        self.scan = panel.findChild(QPushButton, 'scanMicrophoneButton')
        self.test = panel.findChild(QPushButton, 'testMicrophoneButton')
        self.manual = panel.findChild(QPushButton, 'manualRecordingButton')
        self.status = panel.findChild(QLabel, 'microphoneStatus')
        self._scan_version, self._device_disabled = -1, False
        self._result = ''
        self._shortcut = self.shortcut.keySequence()
        self.shortcut.setMaximumSequenceLength(1)
        self.volume.setToolTip('软件输入音量：100%为麦克风原始音量，0%静音；电平、VAD和ASR均使用调整后的声音。')
        self.test.setToolTip('测试5秒输入电平，可随时停止；不调用ASR、LLM或TTS。')
        self.hotkey = HoldShortcut(self.shortcut, self._hold_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.test_timer = QTimer(self)
        self.test_timer.setSingleShot(True)
        self.test_timer.setInterval(5000)
        self.test_timer.timeout.connect(self.finish_test)
        self.scan.clicked.connect(self.request_scan)
        self.test.clicked.connect(self.toggle_test)
        self.manual.clicked.connect(self.toggle_manual)
        self.device.currentIndexChanged.connect(self.change_device)
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.rate.currentTextChanged.connect(self.change_rate)
        self.volume.valueChanged.connect(self.change_volume)
        self.shortcut.editingFinished.connect(self.change_shortcut)
        panel.closing.connect(self.close)
        for widget in (self.device, self.mode, self.shortcut, self.rate, self.volume, self.scan, self.test, self.manual):
            widget.setEnabled(False)

    def bind_inputs(self, inputs):
        self.inputs = inputs
        options = inputs.capture_state().options
        with ExitStack() as stack:
            for widget in (self.device, self.mode, self.rate, self.volume):
                stack.enter_context(QSignalBlocker(widget))
            self.mode.setCurrentIndex(self.MODES.index(options.mode))
            self.volume.setValue(options.volume)
            text = f'{options.sample_rate} Hz'
            if self.rate.findText(text) < 0:
                self.rate.addItem(text)
            self.rate.setCurrentText(text)
            self._fill_devices(inputs.audio_status())
        for widget in (self.device, self.mode, self.rate, self.volume, self.scan, self.test):
            widget.setEnabled(True)
        self.timer.start()
        self.request_scan()

    def _fill_devices(self, audio):
        selected = -1 if self._device_disabled else audio.state.options.device
        with QSignalBlocker(self.device):
            self.device.clear()
            self.device.addItem('系统默认麦克风', None)
            for device in audio.devices:
                self.device.addItem(device.label, device.index)
            if selected is not None and selected != -1 and self.device.findData(selected) < 0:
                self.device.addItem(f'配置的设备 #{selected} · 请获取设备并确认', selected)
            self.device.addItem('暂不使用麦克风', -1)
            self.device.setCurrentIndex(max(0, self.device.findData(selected)))

    def request_scan(self):
        if self.inputs is not None:
            self._result = ''
            self.inputs.request_device_scan()
            self.refresh()

    def change_device(self):
        if self.inputs is None:
            return
        index = self.device.currentData()
        if index == -1:
            self._device_disabled = True
            self.inputs.set_recording(False)
        else:
            name = next((d.name for d in self.inputs.audio_status().devices if d.index == index), '')
            self.inputs.configure_audio(device=index, device_name=name)
            if self._device_disabled:
                self._device_disabled = False
                self.inputs.set_recording(True)
        self._result = ''
        logging.getLogger('tachitalk').info('输入设备：%s', self.device.currentText())
        self.refresh()

    def change_mode(self):
        if self.inputs is not None:
            self.inputs.configure_audio(mode=self.MODES[self.mode.currentIndex()])
            self._result = ''
            self.refresh()

    def change_rate(self, text):
        if self.inputs is not None:
            self.inputs.configure_audio(sample_rate=int(text.split()[0]))
            self._result = ''
            self.refresh()

    def change_volume(self, value):
        self.volume_label.setText(f'{value}%')
        if self.inputs is not None:
            self.inputs.configure_audio(volume=value)

    def change_shortcut(self):
        try:
            self.hotkey.set_sequence(self.shortcut.keySequence())
        except ValueError as error:
            with QSignalBlocker(self.shortcut):
                self.shortcut.setKeySequence(self._shortcut)
            self._result = str(error)
        else:
            self._shortcut = QKeySequence(self.shortcut.keySequence())
            self._result = ''
        self.refresh()

    def _hold_changed(self, active):
        if self.inputs is not None:
            self.inputs.set_manual_active(active)

    def toggle_manual(self):
        if self.inputs is not None:
            self.inputs.set_manual_active(not self.inputs.capture_state().manual_active)
            self.refresh()

    def toggle_test(self):
        if self.inputs is None:
            return
        if self.inputs.capture_state().testing:
            self.finish_test()
        else:
            self._result = ''
            self.inputs.set_testing(True)
            self.test_timer.start()
            self.refresh()

    def finish_test(self):
        self.test_timer.stop()
        if self.inputs is None or not self.inputs.capture_state().testing:
            return
        audio = self.inputs.audio_status()
        self.inputs.set_testing(False)
        if audio.error:
            self._result = audio.error
        elif not audio.test_frames:
            self._result = '未采集到音频，请检查设备、采样率和系统麦克风权限。'
        elif audio.test_peak <= 1:
            self._result = '测试完成，未检测到明显输入信号；请检查音量并靠近麦克风说话。'
        else:
            self._result = f'测试完成，已检测到输入信号，最高电平 {audio.test_peak}%。'
        logging.getLogger('tachitalk').info('%s', self._result)
        self.refresh()

    def refresh(self):
        if self.inputs is None:
            return
        audio = self.inputs.audio_status()
        state, mode = audio.state, audio.state.options.mode
        dialogue = self.inputs.snapshot()
        if audio.scan_version != self._scan_version:
            self._scan_version = audio.scan_version
            self._fill_devices(audio)
            if audio.scan_version and not audio.scan_error:
                self._result = (f'已获取 {len(audio.devices)} 个麦克风输入端点，请选择设备。' if audio.devices
                                else '未检测到麦克风输入设备，请连接设备并重新获取。')
        if self._device_disabled and dialogue.recording:
            self._device_disabled = False
            self._fill_devices(audio)
        self.scan.setEnabled(not audio.scanning)
        self.scan.setText('正在获取…' if audio.scanning else '获取麦克风设备')
        self.test.setText('停止测试' if state.testing else '测试麦克风')
        for widget in (self.device, self.mode, self.rate):
            widget.setEnabled(not state.testing)
        self.manual.setVisible(mode == 'toggle')
        self.manual.setEnabled(dialogue.recording and dialogue.ready and audio.capture_active
                               and (not dialogue.busy or dialogue.can_interrupt) and not state.testing)
        self.manual.setText('结束录音并发送' if state.manual_active else '回复中…' if dialogue.busy else '开始录音')
        self.shortcut.setEnabled(mode == 'hold' and not state.testing)
        self.volume_label.setText(f'{state.options.volume}%')
        self.level.setValue(audio.level if audio.capture_active else 0)
        self.level.setFormat('输入信号 · %p%' if audio.capture_active else '设备异常' if audio.error else '等待输入')
        try:
            self.hotkey.set_enabled(mode == 'hold' and dialogue.recording and not state.testing)
        except ValueError as error:
            self._result = str(error)
        if state.testing and audio.error:
            self.finish_test()
            return
        if state.testing:
            message = '请说话，正在测试输入电平；5秒后结束，测试声音不会发送给AI。'
        elif audio.scanning:
            message = '正在获取系统麦克风设备…'
        elif self._result or audio.error or audio.scan_error:
            message = self._result or audio.error or audio.scan_error
        elif not dialogue.recording:
            message = '录音已关闭；可以点击测试麦克风临时检查输入，或开启录音对话。'
        elif mode == 'hold':
            message = f'按住 {self._shortcut.toString()} 说话，松开后发送；控制面板未聚焦时也可使用。'
        elif mode == 'toggle':
            message = '点击开始录音，说完点击结束并发送；达到单段上限时自动发送，未检测到人声时不发送。'
        else:
            message = '持续监听：检测到人声后收集本句话，静音时不触发对话。'
        self.status.setText(message)

    def close(self):
        self.timer.stop()
        self.test_timer.stop()
        self.hotkey.close()
        if self.inputs is not None:
            self.inputs.set_testing(False)
