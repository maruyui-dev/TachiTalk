"""Native v2ProPlus workbench; heavy work stays in an owned private-Python process."""
import json
from pathlib import Path
import time
from PySide6.QtCore import QFile, QIODevice, QObject, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QFormLayout, QMessageBox, QStackedWidget,
    QWidget, QTabWidget, QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QPlainTextEdit, QProgressBar, QFileDialog, QDialog, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QHeaderView)
from app.paths import DATA_ROOT, TTS_SERVICE_DIR
from app.core.components import voice_status
from app.training.project import TrainingOptions, TrainingProject, training_status, training_location, LANGUAGES, AUDIO_EXTENSIONS
from app.training.jobs import TrainingJob


class TrainingPage(QObject):
    def __init__(self, panel, ui_path):
        super().__init__(panel)
        self.panel = panel
        stack = panel.findChild(QStackedWidget, 'pageStack')
        source = QFile(str(ui_path))
        if not source.open(QIODevice.OpenModeFlag.ReadOnly):
            raise FileNotFoundError(f'无法打开模型训练界面：{ui_path}')
        loader = QUiLoader()
        try:
            self.page = loader.load(source, stack)
        finally:
            source.close()
        if self.page is None:
            raise RuntimeError(f'模型训练界面加载失败：{loader.errorString()}')
        stack.addWidget(self.page)
        # 保留Designer中的完整预览布局；运行时将操作栏放入主窗口的固定页脚。
        self.actions = self.page.findChild(QWidget, 'trainingActions')
        self.page.layout().removeWidget(self.actions)
        panel.findChild(QHBoxLayout, 'footerButtonsLayout').insertWidget(0, self.actions)
        self.actions.hide()
        self.setup_workbench(stack)

    def show_notice(self):
        self.refresh()

    def w(self, name, kind=QLineEdit):
        return self.page.findChild(kind, name) or self.actions.findChild(kind, name)

    def setup_workbench(self, stack):
        self.service_root, self.data_root = Path(TTS_SERVICE_DIR), Path(DATA_ROOT)
        self.project = None
        self.started = self.progress_at = 0
        self.editor = self.page
        index = stack.indexOf(self.editor)
        stack.removeWidget(self.editor)
        self.editor.setObjectName('trainingEditor')
        self.page = QWidget(stack)
        self.page.setObjectName('trainingPage')
        box = QVBoxLayout(self.page)
        box.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.resources = QLabel()
        self.resources.setWordWrap(True)
        row.addWidget(self.resources, 1)
        self.download = QPushButton('下载完整训练包')
        self.download.setObjectName('trainingDownloadButton')
        self.download.clicked.connect(lambda: self.open_download('training'))
        row.addWidget(self.download)
        box.addLayout(row)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('trainingTabs')
        self.tabs.addTab(self.editor, '模型训练')
        self.tabs.addTab(self.build_inference(), '语音推理')
        box.addWidget(self.tabs)
        stack.insertWidget(index, self.page)
        for kind in (QLineEdit, QComboBox, QSpinBox, QCheckBox):
            for widget in self.editor.findChildren(kind):
                widget.setEnabled(True)
        self.w('trainingVersionCombo', QComboBox).setEnabled(False)
        for name in ('trainingSoVITSModelEdit', 'trainingGPTModelEdit'):
            self.w(name).setReadOnly(True)
        self.w('trainingNotice', QLabel).setText('v2ProPlus · 导入音频 → 校对标注 → 处理数据集 → 训练 → 试听与应用')
        for name, choices in [('trainingLanguageCombo', ['日语', '中文', '英语', '韩语', '粤语']),
            ('trainingBatchCombo', ['自动（批次2）', '1', '2', '4', '8', '16']),
            ('trainingDeviceCombo', ['GPU 0', 'CPU', 'GPU 1'])]:
            combo = self.w(name, QComboBox)
            combo.clear()
            combo.addItems(choices)
        self.projects = QComboBox()
        self.projects.activated.connect(self.select_project)
        row = QHBoxLayout()
        row.addWidget(QLabel('已有项目'))
        row.addWidget(self.projects, 1)
        self.stage_combo = QComboBox()
        self.stage_combo.addItems(['SoVITS + GPT', '仅 SoVITS', '仅 GPT'])
        row.addWidget(self.stage_combo)
        for title, slot in [('新建项目', self.new_project), ('处理数据集特征', lambda: self.run('prepare'))]:
            button = QPushButton(title)
            button.clicked.connect(slot)
            row.addWidget(button)
            if title == '处理数据集特征':
                self.features_button = button
            else:
                self.new_project_button = button
        self.editor.layout().insertLayout(1, row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        self.log.document().setMaximumBlockCount(150)
        self.editor.layout().addWidget(self.log)
        self.elapsed = QLabel('尚未开始任务')
        self.editor.layout().addWidget(self.elapsed)
        for name, slot in [('trainingBrowseButton', self.browse), ('trainingImportButton', self.import_audio),
            ('trainingPrepareButton', self.preprocess), ('trainingReviewButton', self.review),
            ('trainingDetectButton', lambda: self.run('detect')), ('trainingStartButton', lambda: self.run(['train', 'sovits', 'gpt'][self.stage_combo.currentIndex()])),
            ('trainingPreviewButton', self.preview_trained), ('trainingApplyButton', self.apply_model),
            ('trainingStopButton', self.stop)]:
            button = self.w(name, QPushButton)
            button.setToolTip('')
            button.clicked.connect(slot)
        self.w('trainingPrepareButton', QPushButton).setText('音频处理与自动标注')
        self.w('trainingStopButton', QPushButton).setText('请求停止')
        self.w('trainingApplyButton', QPushButton).setText('应用为桌宠语音')
        self.job = TrainingJob(self.service_root, self)
        self.job.event.connect(self.on_event)
        self.job.finished.connect(self.on_finished)
        self.tabs.currentChanged.connect(lambda _index: self.refresh())
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.panel.closing.connect(self.timer.stop)
        self.restore_projects()
        self.refresh()

    def build_inference(self):
        page = QWidget()
        box = QVBoxLayout(page)
        self.gate = QWidget()
        gate = QVBoxLayout(self.gate)
        title = QLabel('请先下载推理资源包')
        title.setStyleSheet('font-size:22px;font-weight:600')
        gate.addWidget(title)
        gate.addWidget(QLabel('安装后即可使用本地语音合成；文字聊天等其他功能仍可使用。'))
        button = QPushButton('前往下载推理资源包')
        button.clicked.connect(lambda: self.open_download('voice'))
        gate.addWidget(button)
        box.addWidget(self.gate)
        self.infer_form = QWidget()
        form = QFormLayout(self.infer_form)
        self.infer_models = QComboBox()
        self.infer_models.addItems(['默认角色 v2ProPlus', '当前训练项目 v2ProPlus'])
        form.addRow('角色模型', self.infer_models)
        self.reference, self.prompt = QLineEdit(), QLineEdit()
        row = QHBoxLayout()
        row.addWidget(self.reference)
        browse = QPushButton('选择 WAV')
        browse.clicked.connect(lambda: self.reference.setText(QFileDialog.getOpenFileName(self.panel, '3～10秒参考音频', '', 'WAV (*.wav)')[0]))
        row.addWidget(browse)
        form.addRow('参考音频（3～10秒）', row)
        form.addRow('参考音频原文', self.prompt)
        self.infer_language = QComboBox()
        for title, value in zip(['日语', '中文', '英语', '韩语', '粤语'], LANGUAGES):
            self.infer_language.addItem(title, value)
        form.addRow('语言', self.infer_language)
        self.infer_text = QPlainTextEdit('こんにちは、よろしくね。')
        self.infer_text.setMaximumHeight(120)
        form.addRow('合成文本', self.infer_text)
        self.synthesize = QPushButton('合成并试听')
        self.synthesize.clicked.connect(lambda: self.run('infer'))
        form.addRow(self.synthesize)
        stop = QPushButton('停止试听')
        stop.setObjectName('trainingStopPreviewButton')
        stop.clicked.connect(self.stop_preview)
        form.addRow(stop)
        restore = QPushButton('恢复默认角色模型')
        restore.clicked.connect(self.restore_default)
        form.addRow(restore)
        box.addWidget(self.infer_form)
        self.infer_result = QLabel()
        self.infer_result.setWordWrap(True)
        box.addWidget(self.infer_result)
        box.addStretch()
        return page

    def open_download(self, component):
        self.panel.select_page(6)
        controls = self.panel.ensure_update_controls()
        if controls is not None:
            (controls.install_voice if component == 'voice' else controls.install_training)()

    def restore_projects(self):
        selected = str(self.project.directory) if self.project else None
        self.projects.clear()
        for path in sorted((self.data_root / 'training/projects').glob('*/project.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True):
            try:
                project = TrainingProject(path.parent)
            except (ValueError, OSError, KeyError):
                continue
            self.projects.addItem(project.state['name'], str(path.parent))
        if self.projects.count():
            index = self.projects.findData(selected) if selected else 0
            self.projects.setCurrentIndex(max(index, 0))
            self.select_project(self.projects.currentIndex())

    def select_project(self, index):
        if not self.projects.itemData(index):
            return
        self.project = TrainingProject(self.projects.itemData(index))
        self.w('trainingProjectNameEdit').setText(self.project.state['name'])
        for kind, name in [('sovits', 'trainingSoVITSModelEdit'), ('gpt', 'trainingGPTModelEdit')]:
            self.w(name).setText(self.project.state.get('models', {}).get(kind, ''))

    def new_project(self):
        try:
            self.project = TrainingProject.create(self.data_root / 'training/projects', self.w('trainingProjectNameEdit').text(),
                LANGUAGES[self.w('trainingLanguageCombo', QComboBox).currentIndex()])
            self.restore_projects()
        except (ValueError, OSError) as error:
            self.error(error)

    def ensure_project(self):
        if self.project is None:
            self.new_project()
        if self.project is None:
            raise ValueError('请先创建训练项目')
        return self.project

    def browse(self):
        path = QFileDialog.getExistingDirectory(self.panel, '选择源音频目录')
        if path:
            self.w('trainingAudioDirectoryEdit').setText(path)

    def import_audio(self):
        try:
            directory = self.w('trainingAudioDirectoryEdit').text().strip()
            sources = [p for p in Path(directory).iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS] if directory else QFileDialog.getOpenFileNames(self.panel, '导入音频', '', '音频 (*.wav *.mp3 *.flac *.ogg *.m4a *.aac)')[0]
            if sources:
                rows = self.ensure_project().import_audio(sources)
                self.log.appendPlainText(f'已导入 {len(rows)} 条副本，源音频保持原样。')
                self.review()
        except (ValueError, OSError) as error:
            self.error(error)

    def review(self):
        try:
            project = self.ensure_project()
            dialog = QDialog(self.panel)
            dialog.setWindowTitle('音频标注校对')
            dialog.resize(860, 520)
            box = QVBoxLayout(dialog)
            box.addWidget(QLabel('保存后请重新处理数据集特征。'))
            rows = project.state['annotations']
            table = QTableWidget(len(rows), 4)
            table.setHorizontalHeaderLabels(['音频', '说话人', '语言 ja/zh/en/ko/yue', '标注原文'])
            for i, record in enumerate(rows):
                for column, key in enumerate(('name', 'speaker', 'language', 'text')):
                    item = QTableWidgetItem(record.get(key, ''))
                    if not column:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(i, column, item)
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            box.addWidget(table)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            box.addWidget(buttons)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                project.set_annotations([dict(record, speaker=table.item(i, 1).text(), language=table.item(i, 2).text(), text=table.item(i, 3).text()) for i, record in enumerate(rows)])
        except (ValueError, OSError) as error:
            self.error(error)

    def options(self):
        return TrainingOptions(sovits_epochs=self.w('trainingSoVITSEpochsSpin', QSpinBox).value(),
            gpt_epochs=self.w('trainingGPTEpochsSpin', QSpinBox).value(),
            batch_size=[2, 1, 2, 4, 8, 16][self.w('trainingBatchCombo', QComboBox).currentIndex()],
            gpu=['0', 'cpu', '1'][self.w('trainingDeviceCombo', QComboBox).currentIndex()])

    def run(self, task, **extra):
        claimed = False
        try:
            if self.job.running:
                raise ValueError('已有任务正在运行，请等待完成或请求停止')
            inputs = getattr(getattr(self.panel, 'voice_controls', None), 'inputs', None)
            if inputs is not None and inputs.snapshot().busy:
                raise ValueError('桌宠正在回复，请完成本轮后再开始训练或试听')
            if not voice_status(self.service_root)['installed']:
                raise ValueError('请先下载安装推理资源包')
            if task not in ('detect', 'infer') and not training_status(self.service_root, self.data_root.parent)['installed']:
                raise ValueError('请先下载安装 v2ProPlus 训练扩展')
            project = self.ensure_project()
            if task in ('prepare', 'train', 'sovits', 'gpt'):
                project.write_filelist()
            if task == 'infer':
                from app.core.audio_library import inspect_audio
                inspect_audio(self.reference.text())
                if not self.prompt.text().strip() or not self.infer_text.toPlainText().strip():
                    raise ValueError('请填写参考音频原文和合成文本')
                pair = project.model_pair() if self.infer_models.currentIndex() else self.default_models()
                extra.update(models={k: str(v) for k, v in pair.items()}, reference=self.reference.text(),
                    prompt=self.prompt.text(), text=self.infer_text.toPlainText(), language=self.infer_language.currentData())
            voices = getattr(getattr(self.panel, 'voice_controls', None), 'voices', None)
            service = getattr(voices, 'local_service', None)
            self.job.before_start = None
            if service is not None and service.loop is not None:
                import asyncio
                def wait_for_pause():
                    future = asyncio.run_coroutine_threadsafe(service.suspend(), service.loop)
                    try:
                        future.result(timeout=20)
                    except BaseException:
                        future.cancel()
                        raise
                self.job.before_start = wait_for_pause
            if voices is not None:
                voices.training_active = True
                claimed = True
                if inputs is not None:
                    inputs.invalidate_service('TTS')
            self.job.training = training_location(self.service_root, self.data_root.parent)
            self.job.start(project, task, self.options(), **extra)
            self.started = self.progress_at = time.time()
            self.log.appendPlainText('开始任务：' + task)
            self.infer_result.setText('正在后台处理…')
            self.refresh()
        except (ValueError, OSError, KeyError) as error:
            if claimed:
                voices.training_active = False
                if service is not None:
                    service.suspended = False
            self.error(error)

    def preprocess(self):
        dialog = QDialog(self.panel)
        dialog.setWindowTitle('音频处理 · 内置模型')
        dialog.setMinimumWidth(560)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel('识别与人声分离模型随完整训练包提供，无需另选模型文件。'))
        form = QFormLayout()
        operation = QComboBox()
        operation.setObjectName('preprocessOperationCombo')
        for title, value in [('切分并自动标注', 'slice_asr'), ('仅切分音频', 'slice'),
                             ('仅自动标注', 'asr'), ('仅分离人声', 'separate')]:
            operation.addItem(title, value)
        form.addRow('处理方式', operation)
        box.addLayout(form)
        vocals = QCheckBox('处理前先分离人声（适用于带背景音乐的音频）')
        box.addWidget(vocals)
        slicing = QWidget()
        parameters = QFormLayout(slicing)
        fields = {}
        for name, title, initial, lower, upper, suffix in [
                ('threshold', '静音阈值', -34, -80, -10, ' dB'),
                ('min_length', '最短切分目标', 4, .3, 54, ' 秒'),
                ('max_length', '单段最长时长', 15, .3, 54, ' 秒'),
                ('min_interval', '最短静音间隔', .3, .05, 5, ' 秒'),
                ('max_sil_kept', '保留静音长度', .5, .05, 5, ' 秒')]:
            field = QDoubleSpinBox()
            field.setObjectName('preprocessMaxLength' if name == 'max_length' else 'preprocess_' + name)
            field.setRange(lower, upper)
            field.setDecimals(2)
            field.setSingleStep(.1 if suffix == ' 秒' else 1)
            field.setValue(initial)
            field.setSuffix(suffix)
            parameters.addRow(title, field)
            fields[name] = field
        box.addWidget(slicing)
        hint = QLabel('原音频与旧标注保留。仅切分会生成空白标注，之后可自动标注或人工填写；标注完成后再处理数据集特征。')
        hint.setWordWrap(True)
        box.addWidget(hint)
        def refresh_operation():
            slicing.setEnabled(operation.currentData() in ('slice', 'slice_asr'))
            vocals.setEnabled(operation.currentData() != 'separate')
        operation.currentIndexChanged.connect(refresh_operation)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = {name: field.value() for name, field in fields.items()}
            if operation.currentData() in ('slice', 'slice_asr') and (
                    values['min_length'] > values['max_length'] or values['min_interval'] > values['min_length']):
                self.error('单段最长时长应不小于最短切分目标，最短切分目标应不小于静音间隔')
                return
            self.run('preprocess', operation=operation.currentData(), separate_vocals=vocals.isChecked(),
                     slicing=values, language=LANGUAGES[self.w('trainingLanguageCombo', QComboBox).currentIndex()])

    def default_models(self):
        data = json.loads((self.service_root / 'distribution.json').read_text(encoding='utf-8'))
        return dict(gpt=self.service_root / data['selected_gpt'], sovits=self.service_root / data['selected_sovits'])

    def preview_trained(self):
        self.infer_models.setCurrentIndex(1)
        self.infer_text.setPlainText(self.w('trainingPreviewTextEdit').text())
        self.tabs.setCurrentIndex(1)

    def apply_model(self):
        try:
            from app.training.project import apply_voice
            from app.core.audio_library import inspect_audio
            project = self.ensure_project()
            reference, prompt, language = self.reference.text(), self.prompt.text(), self.infer_language.currentData()
            if not reference or not prompt:
                for row in project.state['annotations']:
                    try:
                        candidate = project.owned(row['audio'])
                        inspect_audio(candidate)
                    except ValueError:
                        continue
                    reference, prompt, language = str(candidate), row['text'], row['language']
                    break
            controls = self.panel.audio_resource_controls
            key = apply_voice(project, self.data_root, controls.library, reference, prompt, language)
            controls.refresh(key)
            self.log.appendPlainText('已应用模型和默认参考音频；本程序启动的本地服务将在下次检查时重新加载。旧录音和模型保留。')
        except (ValueError, OSError) as error:
            self.error(error)

    def restore_default(self):
        try:
            (self.data_root / 'settings/active_voice_model.json').unlink(missing_ok=True)
            self.infer_models.setCurrentIndex(0)
            self.infer_result.setText('已恢复默认模型，本地服务将在下次检查时重新加载。')
        except OSError as error:
            self.error(error)

    def stop(self):
        self.job.request_stop()
        self.log.appendPlainText('已请求停止，当前处理阶段或训练轮保存后停止，模型和日志保留。')

    def stop_preview(self):
        import winsound
        winsound.PlaySound(None, 0)

    def on_event(self, value):
        if value['phase'] == 'log':
            self.log.appendPlainText(value['text'])
            return
        self.progress_at = value.get('progress_at', time.time())
        self.w('trainingTaskState', QLabel).setText(value['phase'])
        self.w('trainingEmptyTitle', QLabel).setText(value['phase'])
        self.log.appendPlainText(value['phase'] + (': ' + value.get('error', '') if value.get('error') else ''))
        total, done = value.get('total'), value.get('completed')
        bar = self.w('trainingProgress', QProgressBar)
        bar.setRange(0, 100 if total else 0)
        if total:
            bar.setValue(round(done * 100 / total))
        self.w('trainingProgressValue', QLabel).setText(f'{done:,} / {total:,}' if total else '处理中')

    def on_finished(self, result):
        voices = getattr(getattr(self.panel, 'voice_controls', None), 'voices', None)
        if voices is not None:
            voices.training_active = False
            service = getattr(voices, 'local_service', None)
            if service is not None:
                service.suspended = False
        bar = self.w('trainingProgress', QProgressBar)
        bar.setRange(0, 100)
        bar.setValue(100 if result['ok'] and not result.get('stopped') else 0)
        message = '已停止，产物和日志保留' if result.get('stopped') else '任务成功' if result['ok'] else result.get('error', '任务失败')
        self.log.appendPlainText(message + '\n日志：' + result['log'])
        self.infer_result.setText(message)
        self.w('trainingTaskState', QLabel).setText(message)
        self.w('trainingEmptyTitle', QLabel).setText(message)
        self.w('trainingProgressValue', QLabel).setText(message)
        if self.started:
            self.elapsed.setText(f'总耗时 {int(time.time()-self.started)} 秒 · 任务已结束')
        if self.project:
            self.project = TrainingProject(self.project.directory)
            self.project.refresh_models()
            self.select_project(self.projects.currentIndex())
        if result.get('audio') and not result.get('stopped'):
            import winsound
            winsound.PlaySound(result['audio'], winsound.SND_FILENAME | winsound.SND_ASYNC)
        self.refresh()

    def refresh(self):
        installed = voice_status(self.service_root)['installed']
        trained = training_status(self.service_root, self.data_root.parent)['installed']
        busy = self.job.running
        self.resources.setText(f"推理资源：{'已安装' if installed else '未安装'} · v2ProPlus 完整训练包：{'已安装' if trained else '未安装 / 不完整'}")
        self.gate.setVisible(not installed)
        self.infer_form.setEnabled(installed and not busy)
        self.download.setVisible(not trained)
        self.download.setEnabled(not busy)
        rows = self.project.state['annotations'] if self.project else []
        ready = self.project is not None and (self.project.directory / 'features/ready.json').is_file()
        self.w('trainingStartButton', QPushButton).setEnabled(installed and trained and ready and not busy)
        self.w('trainingStartButton', QPushButton).setVisible(self.tabs.currentIndex() == 0)
        self.w('trainingPrepareButton', QPushButton).setEnabled(installed and trained and bool(rows) and not busy)
        for name in ('trainingBrowseButton', 'trainingImportButton', 'trainingReviewButton'):
            self.w(name, QPushButton).setEnabled(not busy)
        self.features_button.setEnabled(installed and trained and bool(rows) and all(r['text'].strip() for r in rows) and not busy)
        self.w('trainingDetectButton', QPushButton).setEnabled(installed and not busy)
        self.w('trainingStopButton', QPushButton).setEnabled(busy)
        for name in ('trainingPreviewButton', 'trainingApplyButton'):
            self.w(name, QPushButton).setEnabled(installed and self.project is not None and not busy)
        self.projects.setEnabled(not busy)
        self.new_project_button.setEnabled(not busy)
        self.stage_combo.setEnabled(not busy)
        for name in ('trainingProjectNameEdit', 'trainingAudioDirectoryEdit'):
            self.w(name).setEnabled(not busy)
        has_models = False
        if self.project is not None:
            try:
                self.project.model_pair()
                has_models = True
            except ValueError:
                pass
        for name in ('trainingPreviewButton', 'trainingApplyButton'):
            self.w(name, QPushButton).setEnabled(installed and has_models and not busy)
        if busy:
            path = self.job.directory / 'epoch.json'
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding='utf-8'))
                    if value['progress_at'] > self.progress_at:
                        self.on_event(value)
                except (ValueError, OSError, KeyError):
                    pass
            now = time.time()
            self.elapsed.setText(f'总耗时 {int(now-self.started)} 秒 · 最近实际进度 {int(now-self.progress_at)} 秒前' +
                (' · 当前阶段没有新进度，请查看日志' if now-self.progress_at > 120 else ''))

    def error(self, error):
        QMessageBox.warning(self.panel, '模型训练 / 推理', str(error))
