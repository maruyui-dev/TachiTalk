"""Qt delivery UI; all HTTP, hashing, unpacking and process waiting stay off the GUI thread."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event, Thread
from time import monotonic
import uuid

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox, QDialogButtonBox)

from app.paths import FROZEN, TTS_SERVICE_DIR
from app.version import VERSION
from app.core.components import voice_status
from app.updates.client import UpdateClient
from app.updates.manifest import atomic_json, verify, version_tuple, sha256


def size_text(value):
    return f'{value / 1024**2:,.1f} MiB'


class UpdatePrompt(QDialog):
    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self.setWindowTitle('TachiTalk 发现新版本')
        self.resize(540, 380)
        layout = QVBoxLayout(self)
        self.details = QLabel(f"当前版本：v{VERSION}\n最新版本：v{payload['version']}\n"
            f"发布时间：{payload.get('published_at') or '未提供'}\n标题：{payload.get('title', '')}\n"
            f"更新包：{size_text(payload['archive']['size'])}")
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.details)
        notes = QPlainTextEdit(payload.get('notes', ''))
        notes.setReadOnly(True)
        notes.setAccessibleName('更新说明')
        layout.addWidget(notes)
        buttons = QDialogButtonBox(self)
        buttons.addButton('立即更新', QDialogButtonBox.ButtonRole.AcceptRole).clicked.connect(self.accept)
        buttons.addButton('稍后更新', QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        layout.addWidget(buttons)


class WorkerSignals(QObject):
    done = Signal(str, object)
    progress = Signal(object)


class UpdateControls(QDialog):
    def __init__(self, panel, client=None):
        super().__init__(panel)
        self.panel = panel
        self.client = client or UpdateClient()
        self.envelopes = {}
        self.stop = Event()
        self.thread = None
        self.prompt = None
        self.install_after_check = False
        self.shutting_down = False
        self.signals = WorkerSignals(self)
        self.signals.done.connect(self.on_finished)
        self.signals.progress.connect(self.progress_changed)
        self.setWindowTitle('更新与语音资源')
        self.resize(700, 630)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.check_button = QPushButton('检查版本与语音资源')
        self.install_button = QPushButton('安装 / 修复语音资源')
        self.update_button = QPushButton('更新主程序')
        row = QHBoxLayout()
        for button, slot in [(self.check_button, self.check), (self.install_button, self.install_voice),
                             (self.update_button, self.update_main)]:
            row.addWidget(button)
            button.clicked.connect(slot)
        layout.addLayout(row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        layout.addWidget(self.progress_bar)
        self.state = QLabel('就绪；未安装语音时可继续使用文字对话')
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        row = QHBoxLayout()
        self.pause_button = QPushButton('暂停 / 取消（保留进度）')
        self.retry_button = QPushButton('重试 / 继续下载')
        self.clear_button = QPushButton('删除下载缓存')
        self.pause_button.clicked.connect(self.pause)
        self.retry_button.clicked.connect(self.retry)
        self.clear_button.clicked.connect(self.clear_cache)
        for button in (self.pause_button, self.retry_button, self.clear_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.last_component = None
        self.config = QPlainTextEdit()
        self.config.setAccessibleName('下载源配置JSON')
        raw_config = self.client.config_path.read_text(encoding='utf-8')
        try:
            raw_config = json.dumps(json.loads(raw_config), ensure_ascii=False, indent=2)
        except ValueError:
            pass  # Keep malformed local settings editable so the user can repair them.
        self.config.setPlainText(raw_config)
        source_hint = QLabel('下载源设置：附件 / API / 清单分别配置；fallback_only 代理在常规源失败后自动尝试。\n'
                             'priority 越小越优先；enabled=false 可彻底禁用，不会自动开启。')
        source_hint.setWordWrap(True)
        layout.addWidget(source_hint)
        layout.addWidget(self.config)
        row = QHBoxLayout()
        save = QPushButton('保存下载源')
        save.clicked.connect(self.save_config)
        local = QPushButton('导入签名清单与离线 ZIP')
        local.clicked.connect(self.import_local)
        row.addWidget(save)
        row.addWidget(local)
        layout.addLayout(row)
        legacy = QPushButton('选择旧版安装目录，复用已有语音（无需重下）')
        legacy.clicked.connect(self.select_legacy)
        layout.addWidget(legacy)
        self.uninstall_button = QPushButton('卸载本程序托管的语音组件（保留被修改的文件）')
        self.uninstall_button.clicked.connect(self.remove_voice)
        layout.addWidget(self.uninstall_button)
        hint = QLabel('公共代理的可用性无法保证。暂停保留临时文件；续传需要服务器返回正确 Range 和文件标识。\n'
                      '安装会关闭主程序，完成后重新启动。只更新主程序不会下载语音环境。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.refresh_summary()
        self.set_busy(False)
        panel.closing.connect(self.shutdown)
        record = self.client.directory / 'install-result.json'
        if record.is_file():
            try:
                result = json.loads(record.read_text(encoding='utf-8'))
                self.state.setText('上次安装 / 更新成功' if result.get('ok') else f"上次安装 / 更新失败，已尝试恢复：{result.get('error', '')}")
            except (OSError, ValueError):
                self.state.setText('上次更新结果记录无法读取，请检查安装日志')

    def refresh_summary(self):
        status = voice_status(TTS_SERVICE_DIR)
        text = f"主程序：v{VERSION}\n语音系统：{'已安装' if status['installed'] else '未安装 / 文件不完整'}；版本：{status['version']}"
        for component, envelope in self.envelopes.items():
            payload = envelope['payload']  # Already verified by the check/import worker.
            text += f"\n{'语音' if component == 'voice' else '主程序'}包：{payload['version']}，下载 {size_text(payload['archive']['size'])}"
            text += f"，安装预留约 {size_text(sum(r['size'] for r in payload['files']) * 3 + 32 * 1024**2)}"
        text += f"\n安装磁盘可用：{size_text(shutil.disk_usage(self.client.root).free)}；配置：{self.client.config_path}"
        text += f'\n当前语音目录：{TTS_SERVICE_DIR}'
        self.summary.setText(text)

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.check_button, self.install_button, self.update_button, self.clear_button, self.uninstall_button):
            button.setEnabled(not busy)
        self.pause_button.setEnabled(busy)
        self.retry_button.setEnabled(not busy and self.last_component is not None)

    def start(self, name, function):
        if self.busy:
            return
        self.stop = Event()
        self.set_busy(True)
        self.state.setText('正在后台处理…')
        stop = self.stop
        def work():
            last = 0
            def progress(value):
                nonlocal last
                now = monotonic()
                if now - last >= .15 or 'done' not in value:
                    last = now
                    self.signals.progress.emit(value)
            try:
                value = function(progress, stop)
                result = {'value': value}
            except Exception as error:
                result = {'error': f'{type(error).__name__}: {error}'}
            try:
                self.signals.done.emit(name, result)
            except RuntimeError:
                pass  # Application exited; only resumable downloads can still be running.
        self.thread = Thread(target=work, name='component-download', daemon=True)
        self.thread.start()

    def check(self, automatic=False):
        self.automatic_check = automatic
        self.start('check', lambda progress, stop: asyncio.run(self.client.check(progress)))

    def on_finished(self, name, result):
        self.set_busy(False)
        if self.shutting_down:
            return
        if name in ('prepare', 'import', 'handoff') and self.stop.is_set():
            self.state.setText('已停止；验证完成的缓存会保留，未启动安装')
            return
        if 'error' in result:
            self.state.setText(result['error'])
            return
        value = result['value']
        if name == 'check':
            self.envelopes.update(value['manifests'])
            self.state.setText('检查完成' + ('；' + '; '.join(f'{k}: {v}' for k, v in value['errors'].items()) if value['errors'] else ''))
            self.refresh_summary()
            if self.install_after_check:
                self.install_after_check = False
                QTimer.singleShot(0, self.install_voice)
            envelope = self.envelopes.get('main')
            if envelope:
                payload = envelope['payload']
                if version_tuple(payload['version']) > version_tuple(VERSION):
                    self.prompt = UpdatePrompt(payload, self.panel)
                    self.prompt.accepted.connect(self.update_main)
                    self.prompt.open()  # Modeless: later/close leaves both main windows running.
        elif name.startswith('load-'):
            component = name[5:]
            self.envelopes[component] = value
            self.begin_download(component)
        elif name == 'handoff':
            try:
                subprocess.Popen(value, cwd=self.client.directory,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.panel.close()
            except OSError as error:
                self.state.setText(f'无法启动更新器：{error}，现有程序保持可用。')
        elif name == 'clear':
            self.state.setText('下载缓存已删除')
        else:
            self.progress_bar.setValue(1000)
            self.state.setText('完整性验证通过；正在准备独立安装器')
            if name == 'import':
                payload = value['payload']
                component = '独立语音组件（运行环境与模型）' if payload['component'] == 'voice' else '主程序'
                if QMessageBox.question(self, '确认安装已验证的离线包',
                    f"组件：{component}\n版本：{payload['version']}\n完整ZIP：{size_text(payload['archive']['size'])}\n"
                    '安装将关闭软件，完成后重新启动。是否继续？') != QMessageBox.StandardButton.Yes:
                    self.state.setText('已验证离线包，暂未安装；主程序继续运行')
                    return
            self.launch_updater(value)

    def progress_changed(self, value):
        done, total = value.get('done', 0), value.get('total', 0)
        if total:
            self.progress_bar.setValue(min(1000, int(done * 1000 / total)))
        text = f"{value.get('status', '')}；当前源：{value.get('source', '')}"
        if total:
            text += f"；{size_text(done)} / {size_text(total)}，{size_text(value.get('speed', 0))}/s，剩余 {size_text(value.get('remaining', 0))}"
        if value.get('error'):
            text += '；' + value['error']
        self.state.setText(text)

    def install_voice(self):
        self.begin_download('voice')

    def remove_voice(self):
        if QMessageBox.question(self, '卸载可选语音', '将关闭主程序并卸载本目录托管的语音文件；旧版外部目录、修改过的文件及用户数据会保留。是否继续？') == QMessageBox.StandardButton.Yes:
            self.launch_updater(None)

    def update_main(self):
        self.show()
        self.begin_download('main')

    def begin_download(self, component):
        try:
            envelope = self.envelopes.get(component)
            if envelope is None:
                self.start('load-' + component, lambda progress, stop: self.client.cached(component))
                return
            payload = envelope['payload']
            if component == 'main' and payload['base_version'] != VERSION:
                raise ValueError('此增量包不适用于当前版本，请下载完整主程序安装包迁移')
            if component == 'voice':
                answer = QMessageBox.question(self, '安装独立语音组件',
                    f"版本 {payload['version']}，需下载 {size_text(payload['archive']['size'])}。\n"
                    '将安装或修复 GPT-SoVITS 运行环境与配音资源，完成下载后关闭软件安装并重启。是否继续？')
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self.last_component = component
            self.start('prepare', lambda progress, stop: asyncio.run(self.client.prepare(envelope, progress, stop)))
        except Exception as error:
            self.state.setText(f'{error}；请先检查资源版本或导入维护者签名清单。')

    def retry(self):
        if self.last_component:
            self.begin_download(self.last_component)

    def pause(self):
        self.stop.set()

    def shutdown(self):
        self.shutting_down = True
        self.pause()

    def select_legacy(self):
        directory = QFileDialog.getExistingDirectory(self, '选择可信的旧版TachiTalk安装目录（含 services 与 assets）')
        if not directory:
            return
        from scripts.start_tts import check_files
        root = Path(directory)
        missing = check_files(root / 'services/gpt_sovits', root / 'assets/audio/tts_reference')
        if missing:
            self.state.setText('旧版语音资源不完整：' + '; '.join(missing[:4]))
            return
        atomic_json(self.client.data / 'settings/voice_location.json', {'installation': str(root.resolve())})
        self.state.setText('已记录旧版语音目录。重启后复用；新主程序本地已安装的语音组件优先。请勿删除旧目录。')

    def save_config(self):
        try:
            from app.updates.download import sources, Policy
            config = json.loads(self.config.toPlainText())
            for kind in ('sources', 'api_sources', 'manifest_sources'):
                for source in sources(config, kind):
                    Policy().source_url('https://github.com', source)
            atomic_json(self.client.config_path, config)
            self.state.setText('下载源已保存，下次检查或下载时生效')
        except Exception as error:
            self.state.setText(f'配置无效：{error}')

    def import_local(self):
        manifest, _ = QFileDialog.getOpenFileName(self, '选择维护者签名清单', '', 'JSON (*.json)')
        if not manifest:
            return
        archive, _ = QFileDialog.getOpenFileName(self, '选择完整资源或更新 ZIP（已合并分卷）', '', 'ZIP (*.zip)')
        if not archive:
            return
        def prepare(progress, stop):
            envelope = self.client.import_manifest(manifest)
            payload = verify(envelope, self.client.keys)
            path = Path(archive)
            if path.stat().st_size != payload['archive']['size'] or sha256(path) != payload['archive']['sha256']:
                raise ValueError('离线文件大小或哈希不匹配')
            return {'manifest': Path(manifest), 'archive': path, 'payload': payload}
        self.start('import', prepare)

    def clear_cache(self):
        if self.thread and self.thread.is_alive():
            return
        if QMessageBox.question(self, '删除下载缓存', '删除所有已下载分卷和续传进度？已安装组件不受影响。') != QMessageBox.StandardButton.Yes:
            return
        path = self.client.directory / 'downloads'
        def clear(progress, stop):
            if path.exists():
                expected = self.client.directory.resolve() / 'downloads'
                if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) or path.resolve() != expected:
                    raise ValueError('缓存目录是链接或路径不符，拒绝清理')
                shutil.rmtree(path)
        self.start('clear', clear)

    def launch_updater(self, prepared):
        def prepare_command(progress, stop):
            directory = self.client.directory / 'updaters'
            directory.mkdir(exist_ok=True)
            if FROZEN:
                updater = directory / f'{uuid.uuid4().hex}.exe'
                shutil.copy2(self.client.root / 'TachiTalkUpdater.exe', updater)
                command = [str(updater)]
            else:
                if prepared and prepared['payload']['component'] == 'main':
                    raise ValueError('源码模式请通过 Git 升级；自动二进制补丁只适用于安装版')
                command = [sys.executable, str(self.client.root / 'scripts/update_entry.py')]
            command += ['--root', str(self.client.root), '--parent-pid', str(os.getpid()),
                '--result', str(self.client.directory / 'install-result.json'), '--restart']
            if prepared:
                command += ['--manifest', str(prepared['manifest']), '--archive', str(prepared['archive'])]
            else:
                command += ['--uninstall-voice']
            return command
        self.start('handoff', prepare_command)

    def closeEvent(self, event):
        self.hide()  # Closing the resource window leaves a download running; Pause is explicit.
        event.ignore()
