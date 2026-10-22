"""独立音频资源页；沿用立绘页卡片与全局试听通道，不改动立绘布局。"""
from array import array
from dataclasses import replace
from pathlib import Path
import wave

from PySide6.QtCore import QFile, QIODevice, QObject, QSignalBlocker, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QWidget, QSizePolicy, QScrollArea, QFrame)

from app.core.audio_library import inspect_audio
from app.core.voice_settings import ReferencePreview


class AudioResourceControls(QObject):
    def __init__(self, panel, library, ui_path):
        super().__init__(panel)
        self.panel, self.library = panel, library
        self.voices = None
        self._preview_id = 0
        self._selected_key = None
        self._dirty = False
        self.ui_path = ui_path
        self.page = None
        resources = panel.findChild(QWidget, 'resourcesPage')
        layout = resources.layout()
        portrait_scroll = panel.findChild(QWidget, 'resourcesPageScroll')
        layout.removeWidget(portrait_scroll)
        self.tabs = QTabWidget(resources)
        self.tabs.setObjectName('resourceManagerTabs')
        self.tabs.setStyleSheet('QTabWidget#resourceManagerTabs::pane {border:0;} '
            'QTabBar::tab {background:transparent; padding:10px 22px; color:#8790a1;}'
            'QTabBar::tab:selected {color:#bc5981; border-bottom:2px solid #e88eb1;}')
        self.tabs.addTab(portrait_scroll, '立绘管理')
        self.scroll = QScrollArea(self.tabs)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setProperty('pageScroll', True)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabs.addTab(self.scroll, '音频管理')
        layout.addWidget(self.tabs)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.poll)
        self.tabs.currentChanged.connect(self.ensure_page)
        panel.closing.connect(self.close)

    def ensure_page(self, index):
        if index != 1 or self.page is not None:
            return
        # 首次打开才构造音频控件，避免隐藏页的布局/字体/波形阻塞立绘动画。
        source = QFile(str(self.ui_path))
        if not source.open(QIODevice.OpenModeFlag.ReadOnly):
            raise FileNotFoundError(f'无法打开音频管理界面：{self.ui_path}')
        loader = QUiLoader()
        try:
            self.page = loader.load(source, self.scroll)
        finally:
            source.close()
        if self.page is None:
            raise RuntimeError(loader.errorString())
        self.scroll.setWidget(self.page)
        self.w('audioWaveform', QLabel).setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.w('audioNicknameEdit', QLineEdit).setMaxLength(64)
        self.w('audioSceneEdit', QLineEdit).setMaxLength(200)
        self.table = self.w('audioResourceTable', QTableWidget)
        self.combo = self.w('audioPackCombo', QComboBox)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(43)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.combo.currentIndexChanged.connect(self.select_pack)
        self.w('audioSearchEdit', QLineEdit).textChanged.connect(self.filter_rows)
        for name in ('audioNicknameEdit', 'audioSceneEdit'):
            self.w(name, QLineEdit).textEdited.connect(self.mark_dirty)
        self.w('audioPromptEdit', QPlainTextEdit).textChanged.connect(self.mark_dirty)
        for name in ('audioEnabledCheck', 'audioDefaultCheck'):
            self.w(name, QCheckBox).clicked.connect(self.mark_dirty)
        self.w('audioEnabledCheck', QCheckBox).clicked.connect(
            lambda enabled: self.w('audioDefaultCheck', QCheckBox).setChecked(False) if not enabled else None)
        self.w('audioDefaultCheck', QCheckBox).clicked.connect(
            lambda default: self.w('audioEnabledCheck', QCheckBox).setChecked(True) if default else None)
        for name, callback in (
            ('audioImportButton', self.import_audio), ('audioSaveButton', self.save),
            ('audioRenameButton', self.rename), ('audioReplaceButton', self.replace_audio),
            ('audioRemoveButton', self.remove), ('audioDefaultButton', self.set_default),
            ('audioNewPackButton', self.new_pack), ('audioRenamePackButton', self.rename_pack),
            ('audioRemovePackButton', self.remove_pack), ('audioImportPackButton', self.import_pack),
            ('audioExportPackButton', self.export_pack), ('audioOpenFolderButton', self.open_folder),
            ('audioRawPreviewButton', lambda: self.preview(True)),
            ('audioTTSPreviewButton', lambda: self.preview(False)), ('audioStopPreviewButton', self.stop)):
            self.w(name, QPushButton).clicked.connect(lambda _=False, callback=callback: self.perform(callback))
        self.timer.start()
        self.refresh()
        if self.library.warning:
            self.report(self.library.warning, True)

    def w(self, name, cls=QWidget):
        return self.page.findChild(cls, name)

    def report(self, text, error=False):
        status = self.w('audioResourceStatus', QLabel)
        status.setText(text)
        status.setStyleSheet('color:#b56826;' if error else 'color:#42946d;')

    def perform(self, callback):
        try:
            callback()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.report(str(error), True)

    def mark_dirty(self, *_):
        self._dirty = True

    def leave_editor(self):
        if not self._dirty:
            return True
        answer = QMessageBox.question(self.panel, '音频信息尚未保存', '保存当前音频信息后继续？',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            self.save(refresh=False)
        self._dirty = False
        return True

    def selected(self):
        if self.page is None:
            return None
        return self.library.records.get(self._selected_key)

    def refresh(self, key=None):
        if self.page is None:
            return
        key = key or self._selected_key
        self._selected_key = None
        with QSignalBlocker(self.combo), QSignalBlocker(self.table):
            self.combo.clear()
            for pack_id, name in self.library.packs.items():
                self.combo.addItem(name, pack_id)
            self.combo.setCurrentIndex(self.combo.findData(self.library.active_id))
            self.table.setRowCount(0)
            for ref in self.library.records.values():
                row = self.table.rowCount()
                self.table.insertRow(row)
                state = '文件缺失' if not Path(ref.path).is_file() else '待填原文' if not ref.prompt else (
                    '默认' if ref.enabled and ref.key == self.library.default_key else '已启用' if ref.enabled else '已禁用')
                for col, text in enumerate((ref.name, '日语', Path(ref.path).name, state)):
                    cell = QTableWidgetItem(text)
                    cell.setData(Qt.ItemDataRole.UserRole, ref.key)
                    cell.setToolTip(ref.path if col == 2 else text)
                    self.table.setItem(row, col, cell)
                if ref.key == key:
                    self.table.setCurrentCell(row, 0)
            if self.table.currentRow() < 0 and self.table.rowCount():
                self.table.setCurrentCell(0, 0)
        self.w('audioLibraryCardTitle', QLabel).setText(self.library.packs[self.library.active_id] + ' · 参考音频')
        self.w('audioRemovePackButton', QPushButton).setEnabled(self.library.active_id != 'default')
        self._dirty = False
        self.filter_rows()
        self.selection_changed()
        try:
            names = '、'.join(self.library.snapshot().names)
        except ValueError:
            names = '暂无可用音频，请填写原文后启用'
        self.w('audioAllowedNames', QLabel).setText('LLM当前可选：' + names)
        self.w('audioAllowedNames', QLabel).setMaximumHeight(54)
        self.w('audioAllowedNames', QLabel).setToolTip(names)

    def filter_rows(self, *_):
        query = self.w('audioSearchEdit', QLineEdit).text().strip().casefold()
        count = 0
        for row in range(self.table.rowCount()):
            visible = query in ' '.join(self.table.item(row, col).text() for col in (0, 2)).casefold()
            self.table.setRowHidden(row, not visible)
            count += visible
        self.w('audioResourceCount', QLabel).setText(f'{count} / {self.table.rowCount()} 条参考音频 · 日语')

    def selection_changed(self):
        row = self.table.currentRow()
        cell = self.table.item(row, 0) if row >= 0 else None
        key = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if key is not None and key == self._selected_key:
            return
        try:
            if not self.leave_editor():
                self.restore_selection()
                return
        except (OSError, ValueError) as error:
            self.report(str(error), True)
            self.restore_selection()
            return
        self._selected_key = key
        ref = self.selected()
        for name in ('audioNicknameEdit', 'audioSceneEdit', 'audioPromptEdit', 'audioEnabledCheck',
                     'audioDefaultCheck', 'audioSaveButton', 'audioRenameButton', 'audioReplaceButton',
                     'audioDefaultButton', 'audioRemoveButton'):
            self.w(name).setEnabled(ref is not None)
        self.w('audioNicknameEdit', QLineEdit).setText(ref.name if ref else '')
        self.w('audioSceneEdit', QLineEdit).setText(ref.scene if ref else '')
        self.w('audioPromptEdit', QPlainTextEdit).setPlainText(ref.prompt if ref else '')
        self.w('audioEnabledCheck', QCheckBox).setChecked(ref.enabled if ref else False)
        self.w('audioDefaultCheck', QCheckBox).setChecked(ref.key == self.library.default_key if ref else False)
        self.w('audioPreviewName', QLabel).setText(ref.name if ref else '请选择参考音频')
        self.w('audioPreviewFile', QLabel).setText(Path(ref.path).name if ref else '')
        self.draw_waveform(ref)
        self._dirty = False
        self.poll()

    def restore_selection(self):
        with QSignalBlocker(self.table):
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == self._selected_key:
                    self.table.setCurrentCell(row, 0)
                    return

    def draw_waveform(self, ref):
        waveform = self.w('audioWaveform', QLabel)
        waveform.clear()
        metadata = self.w('audioPreviewMetadata', QLabel)
        metadata.clear()
        if ref is None:
            return
        try:
            rate, channels, duration = inspect_audio(ref.path)
            with wave.open(ref.path, 'rb') as stream:
                samples = array('h', stream.readframes(stream.getnframes()))
            image = QPixmap(560, 120)
            image.fill(QColor('#f8faff'))
            painter = QPainter(image)
            painter.setPen(QColor('#91b9e4'))
            stride = max(1, len(samples) // 140)
            for index in range(140):
                block = samples[index * stride:(index + 1) * stride]
                height = max(1, round(max((abs(n) for n in block), default=0) / 32768 * 52))
                painter.drawLine(2 + index * 4, 60 - height, 2 + index * 4, 60 + height)
            painter.end()
            waveform.setPixmap(image)
            waveform.setScaledContents(True)
            metadata.setText(f'{duration:.2f} 秒 · 日语 · {rate // 1000}kHz · ' + ('单声道' if channels == 1 else '双声道'))
        except (OSError, ValueError) as error:
            metadata.setText(str(error))

    def save(self, refresh=True):
        ref = self.selected()
        if ref is None:
            return
        self.library.update(ref.key, name=self.w('audioNicknameEdit', QLineEdit).text(),
            scene=self.w('audioSceneEdit', QLineEdit).text(), prompt=self.w('audioPromptEdit', QPlainTextEdit).toPlainText(),
            enabled=self.w('audioEnabledCheck', QCheckBox).isChecked(),
            default=self.w('audioDefaultCheck', QCheckBox).isChecked())
        self._dirty = False
        if refresh:
            self.refresh(ref.key)
        else:
            # 切换列表行前保存时，不重新选择旧行；刷新放在本次选择事件之后。
            QTimer.singleShot(0, self.refresh)
        self.report('音频已保存，昵称和参考从下一轮对话生效。')

    def import_audio(self):
        if not self.leave_editor():
            return
        paths, _ = QFileDialog.getOpenFileNames(self.panel, '导入参考音频', '', 'PCM WAV (*.wav)')
        for path in paths:
            ref = self.library.add(path)
            self.refresh(ref.key)
        if paths:
            self.report('已复制到音频库；请填写日语原文、使用场景并启用。')

    def rename(self):
        if self.selected():
            self.w('audioNicknameEdit', QLineEdit).setFocus()
            self.w('audioNicknameEdit', QLineEdit).selectAll()
            self.report('在右侧修改昵称后点击“保存音频”，LLM名称同步更新。')

    def replace_audio(self):
        if not self.selected() or not self.leave_editor():
            return
        path, _ = QFileDialog.getOpenFileName(self.panel, '替换参考音频', '', 'PCM WAV (*.wav)')
        if path:
            key = self._selected_key
            self.library.replace(key, path)
            self.refresh(key)
            self.report('已替换；请重新填写对应原文并启用。当前回复继续使用旧参考。')

    def remove(self):
        ref = self.selected()
        if ref and QMessageBox.question(self.panel, '移除参考音频', f'从音频库移除“{ref.name}”？原文件与当前回复不受影响。') == QMessageBox.StandardButton.Yes:
            self.library.remove(ref.key)
            self._dirty = False
            self.refresh()
            self.report('已移除，下一轮不再提供此昵称。')

    def set_default(self):
        if not self.selected():
            return
        self.w('audioEnabledCheck', QCheckBox).setChecked(True)
        self.w('audioDefaultCheck', QCheckBox).setChecked(True)
        self.save()

    def select_pack(self, *_):
        key = self.combo.currentData()
        if key == self.library.active_id or key is None:
            return
        def change():
            if self.leave_editor():
                self.library.select_pack(key)
                self.refresh()
            else:
                with QSignalBlocker(self.combo):
                    self.combo.setCurrentIndex(self.combo.findData(self.library.active_id))
        self.perform(change)
        with QSignalBlocker(self.combo):
            self.combo.setCurrentIndex(self.combo.findData(self.library.active_id))

    def new_pack(self):
        if not self.leave_editor():
            return
        name, ok = QInputDialog.getText(self.panel, '新建角色音频库', '角色音频包名称：')
        if ok:
            self.library.create_pack(name.strip())
            self.refresh()

    def rename_pack(self):
        if not self.leave_editor():
            return
        name, ok = QInputDialog.getText(self.panel, '重命名音频包', '名称：', text=self.combo.currentText())
        if ok:
            self.library.rename_pack(name.strip())
            self.refresh()

    def remove_pack(self):
        if QMessageBox.question(self.panel, '移除音频包', '移除当前音频包？原始文件与立绘资源不受影响。') == QMessageBox.StandardButton.Yes:
            self.library.remove_pack()
            self._dirty = False
            self.refresh()

    def import_pack(self):
        if not self.leave_editor():
            return
        directory = QFileDialog.getExistingDirectory(self.panel, '选择包含WAV及同名TXT原文的音频包')
        if directory:
            self.library.import_pack(directory)
            self.refresh()

    def export_pack(self):
        if not self.leave_editor():
            return
        directory = QFileDialog.getExistingDirectory(self.panel, '选择导出位置（将创建新文件夹）')
        if directory:
            target = Path(directory) / (self.combo.currentText() + '_音频包')
            self.library.export_pack(target)
            self.report('音频包已导出：' + str(target))

    def open_folder(self):
        self.library.directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.directory)))

    def bind_runtime(self, voices):
        self.voices = voices
        self.poll()

    def preview(self, raw):
        ref = self.selected()
        if ref is None or self.voices is None:
            return
        inspect_audio(ref.path)
        if not raw:
            if self.voices.snapshot().tts.provider != 'gpt_sovits':
                raise ValueError('参考音频试读需要在语音与音频页选择GPT-SoVITS')
            prompt = self.w('audioPromptEdit', QPlainTextEdit).toPlainText().strip()
            if not prompt or len(prompt) > 1000:
                raise ValueError('TTS试读前请填写与录音一致的原文（最多1000字）')
            ref = replace(ref, prompt=prompt)
        self._preview_id = self.voices.request('preview', ReferencePreview(ref, raw))
        self.poll()

    def stop(self):
        if self.voices is not None:
            self._preview_id = self.voices.request('preview', None)

    def poll(self):
        if self.page is None:
            return
        ref = self.selected()
        for name in ('audioRawPreviewButton', 'audioTTSPreviewButton'):
            self.w(name, QPushButton).setEnabled(ref is not None and self.voices is not None)
        self.w('audioStopPreviewButton', QPushButton).setEnabled(self.voices is not None and self.voices.result('preview').running)
        if self.voices is not None and self._preview_id:
            result = self.voices.result('preview')
            if result.id == self._preview_id:
                self.w('audioPreviewStatus', QLabel).setText('正在合成或播放试听…' if result.running else result.error or str(result.value))

    def close(self):
        self.timer.stop()
        if self.voices is not None and self.voices.result('preview').id == self._preview_id:
            self.voices.request('preview', None)
