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

from PySide6.QtCore import QObject, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFileDialog, QMessageBox, QDialogButtonBox, QScrollArea, QBoxLayout,
    QCheckBox, QInputDialog)

from app.paths import FROZEN, TTS_SERVICE_DIR
from app.version import VERSION, BUILD_LABEL
from app.core.components import voice_status
from app.updates.client import UpdateClient
from app.updates import main_feed
from app.updates.manifest import atomic_json, verify, version_tuple, sha256, REPOSITORY
from app.ui.update_page import build_page, STYLE, label, button, card
from app.ui.update_network import NetworkPrompt, show_network_result, set_proxy_state


def size_text(value):
    return (f'{value / 1024**3:,.2f} GiB' if value >= 1024**3
            else f'{value / 1024**2:,.1f} MiB')


class UpdatePrompt(QDialog):
    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self.setWindowTitle('TachiTalk · 发现新版本')
        self.setStyleSheet(STYLE)
        self.resize(700, 640)
        self.setMinimumSize(540, 500)
        from app.ui.control_panel import make_icon
        self.setWindowIcon(make_icon('cat', '#e95392', 32))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(make_icon('cat', '#e95392', 56).pixmap(56, 56))
        row.addWidget(icon)
        heading = QVBoxLayout()
        title = label('发现新版本', title=True)
        title.setStyleSheet('font-size: 26px; font-weight: 700')
        heading.addWidget(title)
        heading.addWidget(label('已在后台完成检查，不影响当前使用', muted=True))
        row.addLayout(heading, 1)
        layout.addLayout(row)
        versions, box = card()
        self.details = label(f"当前版本  v{VERSION}    →    新版本  v{payload['version']}\n"
            f"发布时间：{payload.get('published_at') or '未提供'}", title=True)
        row = QHBoxLayout()
        row.addWidget(self.details, 1)
        badge = label('可更新')
        badge.setStyleSheet('color: #23844c; background: #e4f6eb; border-radius: 8px; padding: 6px 10px')
        row.addWidget(badge)
        box.addLayout(row)
        layout.addWidget(versions)
        source_badge = label('签名验证通过 · 下载后覆盖更新主程序')
        source_badge.setStyleSheet('color: #a65c17; background: #fff3df; border-radius: 7px; padding: 7px 10px')
        layout.addWidget(source_badge)
        layout.addWidget(label('本次更新', title=True))
        layout.addWidget(label(payload.get('title', '主程序更新')))
        notes = QPlainTextEdit(payload.get('notes') or '维护者尚未提供详细更新说明。')
        notes.setReadOnly(True)
        notes.setAccessibleName('更新说明')
        layout.addWidget(notes, 1)
        info, box = card()
        full = payload.get('installer')
        archive = full or payload['archive']
        box.addWidget(label(f"更新包大小：{size_text(archive['size'])}"))
        box.addWidget(label('语音资源与个人设置保留。\n下载完成后，请解压并运行安装程序。' if full else
            '仅更新主程序，无需重新下载语音资源。\n下载完成后关闭程序安装，完成后自动重新启动。', muted=True))
        layout.addWidget(info)
        row = QHBoxLayout()
        link = button('查看完整更新记录', lambda: QDesktopServices.openUrl(
            QUrl(f"https://github.com/{REPOSITORY}/releases/tag/v{payload['version']}")))
        link.setProperty('deliveryLink', True)
        row.addWidget(link)
        row.addStretch()
        row.addWidget(button('稍后提醒', self.reject))
        self.download_button = button('下载新版安装包' if full else '下载并更新', self.accept, primary=True)
        row.addWidget(self.download_button)
        layout.addLayout(row)


class WorkerSignals(QObject):
    done = Signal(str, object)
    progress = Signal(object)


class UpdateControls(QScrollArea):
    def __init__(self, panel, client=None):
        super().__init__(panel)
        self.panel = panel
        self.client = client or UpdateClient()
        self.envelopes = {}
        self.stop = Event()
        self.thread = None
        self.main_thread = None
        self.main_check_running = False
        self.main_source = None
        self.prompt = None
        self.install_after_check = False
        self.install_after_probe = False
        self.confirm_after_probe = True
        self.network_prompt = None
        self.network_result = None
        self.shutting_down = False
        self.last_component = None
        self.operation = None
        self.pending_source_switch = False
        self.confirm_after_reset = False
        self.main_result = {'state': 'unchecked' if main_feed.ENABLED else 'disabled', 'version': None}
        self.check_errors = {}
        self.voice_required = None
        self.settings_dialog = None
        self.preparing_since = None
        self.preparation_timer = QTimer(self)
        self.preparation_timer.setInterval(1000)
        self.preparation_timer.timeout.connect(self.refresh_preparation_elapsed)
        self.signals = WorkerSignals(self)
        self.signals.done.connect(self.on_finished)
        self.signals.progress.connect(self.progress_changed)
        build_page(self)
        self.config.setPlainText(self.client.config_path.read_text(encoding='utf-8'))
        self.refresh_summary()
        self.set_busy(False)
        panel.closing.connect(self.shutdown)
        self.disk_timer = QTimer(self)
        self.disk_timer.setInterval(5000)
        self.disk_timer.timeout.connect(self.refresh_disk)
        self.disk_timer.start()
        record = self.client.directory / 'install-result.json'
        if record.is_file():
            try:
                result = json.loads(record.read_text(encoding='utf-8'))
                self.state.setText('上次安装 / 更新成功' if result.get('ok') else f"上次安装 / 更新失败，已尝试恢复：{result.get('error', '')}")
                if result.get('ok') and not result.get('cleanup', {}).get('complete', True):
                    self.state.setText('上次安装 / 更新成功，部分材料清理未完成；详见安装日志：' + result.get('log', str(record)))
            except (OSError, ValueError):
                self.state.setText('上次更新结果记录无法读取，请检查安装日志')

    def refresh_summary(self):
        status = voice_status(TTS_SERVICE_DIR)
        state = self.main_result['state']
        latest = self.main_result.get('version')
        descriptions = {'disabled': '更新检查暂未开放', 'current': '已是最新版本', 'no_patch': '有新版本，但没有适用的增量包',
            'unknown': '暂时无法确认最新版本', 'error': '更新检查失败', 'update_available': '发现新版本'}
        self.main_status.setText(f"当前版本 v{VERSION}  ·  {descriptions.get(state, '尚未检查')}")
        self.main_detail.setText(self.check_errors.get('main') or
            (f"最新发布 v{latest}；可前往更新记录下载完整主程序。" if state == 'no_patch' else
             f"最新发布 v{latest}" if latest else '更新检查暂未开放；语音资源可独立安装、修复或离线导入。'))
        self.main_detail.setToolTip(self.check_errors.get('api', ''))
        if latest and state == 'current' and version_tuple(latest) < version_tuple(VERSION):
            self.main_detail.setText(f'{BUILD_LABEL} · 当前版本高于公开发布 v{latest}，无需更新。')
        if main_feed.ENABLED:
            self.check_button.setText('检查版本信息')
            if state == 'unchecked':
                self.main_detail.setText('后台静默检测默认使用魔搭社区；语音资源独立管理。')
            elif state != 'error':
                self.main_detail.setText(f"{self.main_result.get('source', '魔搭社区')} · 最新发布 v{latest} · {self.main_result.get('title','')}\n{self.main_result.get('source_note', '')}\n{self.main_result.get('notes','')}")
        envelope = self.envelopes.get('voice')
        self.voice_state.setText('已安装' if status['installed'] else '尚未安装')
        self.voice_version.setText(f"GPT-SoVITS v2ProPlus  ·  本机：{status['version']}")
        self.voice_detail.setText(self.check_errors.get('voice', ''))
        self.voice_required = None
        if envelope:
            payload = envelope['payload']
            self.voice_state.setText('可修复 / 重装' if status['installed'] else '可安装 · 尚未安装')
            self.voice_version.setText(f"GPT-SoVITS v2ProPlus  ·  组件版本 {payload['version']}")
            self.download_size.setText(size_text(payload['archive']['size']))
            # Conservative staging + replacement + full backup estimate, computed once per check.
            self.voice_required = sum(item['size'] for item in payload['files']) * 3 + 32 * 1024**2
            self.install_size.setText(size_text(self.voice_required))
        else:
            self.download_size.setText('获取语音清单后显示')
            self.install_size.setText('获取语音清单后显示')
        destination = self.client.root / 'services/gpt_sovits'
        text = f'主程序目录：{self.client.root}\n新增语音目录：{destination}'
        if Path(TTS_SERVICE_DIR).resolve() != destination.resolve():
            text += f'\n当前运行语音：{TTS_SERVICE_DIR}（旧版复用 / 当前会话）'
        self.location_details.setText(text)
        self.refresh_disk()
        try:
            config = self.client.configuration()
            preferred = config.get('preferred_download_source')
            from app.updates.download import sources
            configured = sources(config)
            primary = configured[0]['name'] if configured else '未启用下载源'
            self.source_label.setText('来源：' + ('手动选择 · ' + preferred if preferred else '自动测速 · GitHub < 250 ms，否则魔搭'))
            proxies = any(s.get('enabled', True) and s.get('fallback_only') for s in config.get('sources', []))
            mode = preferred or ('GitHub / 魔搭 · 自动测速' if configured else '未启用下载源')
            self.settings_button.setText('下载设置　　' + mode + '　 ›')
        except (OSError, ValueError):
            self.source_label.setText('来源配置无效，请打开下载设置修复')

    def begin_preparation(self):
        if self.preparing_since is None:
            self.preparing_since = monotonic()
        self.preparation_hint.setText('首次下载准备预计约需 5 分钟，完成后自动开始下载。期间请勿重复点击。')
        self.preparation_hint.show()
        self.progress_bar.setRange(0,0)
        self.percent_label.setText('准备中')
        self.preparation_timer.start()
        self.refresh_preparation_elapsed()

    def refresh_preparation_elapsed(self):
        if self.preparing_since is not None:
            minutes,seconds = divmod(max(0,int(monotonic()-self.preparing_since)),60)
            self.eta_label.setText(f'准备已用 {minutes} 分 {seconds} 秒 · 完成后自动下载')

    def finish_preparation(self, message=None):
        self.preparation_timer.stop()
        self.preparing_since = None
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0,1000)
            self.progress_bar.setValue(0)
            self.percent_label.setText('0%')
            self.eta_label.setText('预计剩余 —')
        self.preparation_hint.setVisible(bool(message))
        if message:
            self.preparation_hint.setText(message)

    def refresh_disk(self):
        try:
            usage = shutil.disk_usage(self.client.root)
            self.disk_ring.set_usage(usage.total, usage.free)
            self.disk_title.setText(f'安装磁盘  {self.client.root.anchor} · 跟随主程序')
            self.disk_details.setText(f'● 已用    {size_text(usage.used)}\n\n○ 可用    {size_text(usage.free)}\n\n总容量    {size_text(usage.total)}')
            if self.voice_required is None:
                self.space_state.setText('检查语音清单后确认安装空间要求')
            else:
                enough = usage.free >= self.voice_required
                self.space_state.setText('✓ 安装磁盘空间充足' if enough else '安装磁盘空间不足')
                self.space_state.setStyleSheet('color: #23844c' if enough else 'color: #b44b57')
        except OSError as error:
            self.space_state.setText(f'无法读取安装磁盘：{error}')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'resource_row'):
            self.resource_row.setDirection(QBoxLayout.Direction.TopToBottom if self.viewport().width() < 850
                else QBoxLayout.Direction.LeftToRight)
        if hasattr(self, 'network_row'):
            self.network_row.setDirection(QBoxLayout.Direction.TopToBottom if self.viewport().width() < 850
                else QBoxLayout.Direction.LeftToRight)

    def set_busy(self, busy):
        self.busy = busy
        # Disabling the focused button makes Qt focus the next enabled control,
        # often below the viewport. QScrollArea then scrolls to that control.
        # Keep focus on the visible page before changing any button state.
        focused = self.focusWidget()
        if focused is not None and focused is not self and self.isAncestorOf(focused):
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        for item in (self.check_button, self.install_button, self.clear_button, self.uninstall_button,
                     self.import_button, self.legacy_button, self.settings_button, self.network_check_button):
            item.setEnabled(not busy)
        self.check_button.setEnabled(main_feed.ENABLED and not self.main_check_running)
        self.update_button.setEnabled(main_feed.ENABLED and not busy and not self.main_check_running
            and self.main_result['state'] == 'update_available')
        downloading = busy and self.operation == 'prepare'
        self.pause_button.setEnabled(downloading)
        self.cancel_button.setEnabled(downloading or (busy and self.operation in ('diagnose', 'reset-download')) or
            (busy and self.operation == 'voice-manifest'))
        self.switch_button.setEnabled(not busy or downloading)
        self.retry_button.setEnabled(not busy and self.last_component is not None and
            (self.last_component != 'main' or self.main_result['state'] == 'update_available'))

    def start(self, name, function):
        if self.busy:
            return
        self.operation = name
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
        if main_feed.ENABLED:
            if self.main_check_running or self.shutting_down:
                return
            self.main_check_running = True
            self.check_button.setEnabled(False)
            self.main_status.setText(f'当前版本 v{VERSION}  ·  正在后台检测魔搭社区…')
            def work():
                try:
                    result = {'value':asyncio.run(self.client.check())}
                except Exception as error:
                    result = {'error':f'{type(error).__name__}: {error}'}
                try:
                    self.signals.done.emit('main-check',result)
                except RuntimeError:
                    pass
            self.main_thread = Thread(target=work,name='main-version-check',daemon=True)
            self.main_thread.start()
            return
        if self.busy:
            return
        self.close_prompt()
        self.envelopes.pop('main', None)
        self.main_result = {'state':'disabled','version':None}
        self.refresh_summary()
        self.state.setText('主程序更新检查暂未开放；可直接安装 / 修复语音资源。')
        self.set_busy(self.busy)

    def close_prompt(self):
        if self.prompt:
            self.prompt.reject()
            self.prompt.deleteLater()
            self.prompt = None

    def on_finished(self, name, result):
        if name == 'main-check':
            self.main_check_running = False
            if self.shutting_down:
                return
            if 'error' in result:
                self.main_result = {'state':'error','version':None,'source':'魔搭社区'}
                self.check_errors['main'] = result['error']
            else:
                self.main_result = result['value']['main']
                self.check_errors.pop('main',None)
                self.check_errors.update(result['value']['errors'])
            existing = self.envelopes.get('main')
            if existing and existing['payload']['version'] != self.main_result.get('version'):
                self.envelopes.pop('main', None)
            state = self.main_result['state']
            text = {'current':'已是最新版本','update_available':'发现新版本','error':'版本检测暂不可用'}.get(state,'更新检查暂未开放')
            self.main_status.setText(f'当前版本 v{VERSION}  ·  {text}')
            self.main_detail.setText(self.check_errors.get('main') or
                f"{self.main_result.get('source', '魔搭社区')} · 最新发布 v{self.main_result.get('version','—')} · {self.main_result.get('title','')}\n"
                f"{self.main_result.get('source_note', '')}\n{self.main_result.get('notes','')}")
            self.check_button.setEnabled(main_feed.ENABLED)
            self.update_button.setEnabled(main_feed.ENABLED and not self.busy and state == 'update_available')
            # Do not touch voice busy/stop/progress, navigate, prompt, or install.
            return
        if name == 'check':
            # Ignore even a stale queued result. Never surface a version prompt.
            voice = result.get('value', {}).get('manifests', {}).get('voice')
            if voice:
                try:
                    if verify(voice, self.client.keys)['component'] == 'voice':
                        self.envelopes['voice'] = voice
                except (ValueError, KeyError, TypeError):
                    pass
            self.set_busy(False)
            self.main_result = {'state':'unchecked' if main_feed.ENABLED else 'disabled','version':None}
            self.envelopes.pop('main', None)
            if self.last_component == 'main':
                self.last_component = None
            self.close_prompt()
            self.refresh_summary()
            self.set_busy(False)
            return
        self.set_busy(False)
        if 'error' in result or self.stop.is_set() or name in ('prepare','import','handoff'):
            self.finish_preparation()
        if self.shutting_down:
            return
        if name in ('diagnose', 'check') and self.stop.is_set():
            self.install_after_probe = self.install_after_check = False
            if name == 'diagnose':
                set_proxy_state(self, 'unchecked', '检测已取消')
                self.modelscope_status.setText('检测已取消')
                self.modelscope_status.setStyleSheet('')
            self.state.setText('已取消连接检测 / 检查；未开始下载')
            return
        if name == 'prepare' and self.pending_source_switch:
            self.pending_source_switch = False
            self.reset_selected_download()
            return
        if name in ('prepare', 'import', 'handoff', 'reset-download') and self.stop.is_set():
            self.state.setText('已停止；验证完成的缓存会保留，未启动安装')
            self.task_count.setText('已停止 · 可继续')
            return
        if 'error' in result:
            self.state.setText(result['error'])
            if name == 'check':
                self.install_after_check = False
                self.main_result = {'state': 'unknown', 'version': None}
                self.check_errors = {'main': result['error'], 'voice': result['error']}
                self.envelopes = {}
                self.refresh_summary()
                self.set_busy(False)
            elif name == 'prepare':
                self.task_count.setText('已停止' if self.stop.is_set() else '下载失败 · 可重试')
            elif name == 'diagnose':
                self.install_after_probe = False
                self.modelscope_status.setText('检测失败')
                self.modelscope_status.setStyleSheet('color: #a96813')
                set_proxy_state(self, 'unknown', '代理状态无法确认')
                self.github_status.setText('检测失败')
                self.github_detail.setText(result['error'])
            if name == 'voice-manifest':
                self.check_errors['voice'] = result['error']
                self.refresh_summary()
            return
        value = result['value']
        if name == 'main-manifest':
            if self.stop.is_set():
                return
            self.envelopes['main'] = value
            self.close_prompt()
            self.prompt = UpdatePrompt(value['payload'], self.panel)
            self.prompt.accepted.connect(lambda: self.begin_download('main', confirm=False))
            self.prompt.open()
            self.state.setText('主程序更新签名已验证；确认后下载，保留语音、立绘和个人配置。')
        elif name == 'voice-manifest':
            if self.stop.is_set():
                self.finish_preparation()
                return
            self.envelopes['voice'] = value
            self.check_errors.pop('voice', None)
            self.refresh_summary()
            self.begin_download('voice', confirm=self.confirm_after_probe)
        elif name == 'diagnose':
            if value.get('state') == 'cancelled':
                self.finish_preparation()
                self.install_after_probe = False
                set_proxy_state(self, 'unchecked', '检测已取消')
                self.modelscope_status.setText('检测已取消')
                self.modelscope_status.setStyleSheet('')
                return
            self.network_result = value
            show_network_result(self, value)
            requested = self.install_after_probe
            if value['state'] == 'ok':
                self.install_after_probe = False
                self.state.setText('当前下载渠道连接正常；完整下载仍需签名和文件校验。')
                if requested and 'voice' in self.envelopes:
                    self.begin_download('voice', confirm=self.confirm_after_probe)
                elif requested:
                    self.finish_preparation()
                    self.state.setText('连接可用，但尚无本次检查取得的可信语音清单：' + self.check_errors.get('voice', '请重新检查更新'))
            else:
                self.finish_preparation()
                self.state.setText('资源连接检测未通过；可查看详情、重新检测或尝试现有下载源。')
                self.open_network_prompt(value, can_continue=requested and 'voice' in self.envelopes)
        elif name == 'check':
            self.close_prompt()
            self.envelopes = dict(value['manifests'])
            self.check_errors = value['errors']
            self.main_result = value.get('main', {'state': 'update_available' if 'main' in self.envelopes else 'unknown', 'version': None})
            if self.main_result['state'] != 'update_available' and self.last_component == 'main':
                self.last_component = None
            self.state.setText('检查完成；主程序和语音资源的检查结果分别显示在上方。' +
                (' 版本接口暂不可用，已尝试签名附件清单。' if 'api' in self.check_errors else ''))
            self.refresh_summary()
            self.set_busy(False)
            requested = self.install_after_check
            if requested:
                self.install_after_check = False
                self.detect_network(for_install=True)
            envelope = self.envelopes.get('main')
            payload = envelope['payload'] if envelope else self.main_result if self.main_result.get('installer') else None
            if payload and not requested:
                if version_tuple(payload['version']) > version_tuple(VERSION):
                    self.prompt = UpdatePrompt(payload, self.panel)
                    if payload.get('installer'):
                        url = payload['installer']['url']
                        self.prompt.accepted.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
                    else:
                        self.prompt.accepted.connect(self.update_main)
                    self.prompt.open()  # Later/close keeps the application running.
        elif name == 'reset-download':
            self.progress_bar.setValue(0)
            self.percent_label.setText('0%')
            self.transfer_details.setText('0.0 MiB / —　·　速度 —')
            self.eta_label.setText('预计剩余 —')
            self.state.setText('旧下载缓存已清理；正在从所选来源重新下载。')
            if self.confirm_after_reset:
                self.begin_download(self.last_component, confirm=True)
            else:
                self.retry()
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
            self.percent_label.setText('100%')
            self.task_count.setText('完整性验证通过')
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
        route = value.get('routing')
        if route:
            if route.get('state') == 'checking':
                self.github_status.setText('正在检测…')
                self.github_detail.setText('实际分卷首字节检测 · 最多 3 秒')
            else:
                from app.ui.update_network import probe_description
                self.github_status.setText(probe_description(route['probe']))
                self.github_detail.setText(route['reason'])
                self.modelscope_status.setText('本次采用魔搭' if route['source'] == '魔搭' else '备用 · 尚未检测')
                self.modelscope_detail.setText('最终渠道：' + route['source'] + '；' + route['reason'])
                self.network_note.setText('测量含连接、必要重定向及首字节；上限 3 秒、最多 1 KiB。' + route['reason'])
        done, total = value.get('done', 0), value.get('total', 0)
        if done > 0 and self.preparing_since is not None:
            self.finish_preparation('准备完成，已开始下载。连接中断时优先从当前来源续传。')
        if total and self.preparing_since is None:
            self.progress_bar.setRange(0,1000)
            self.progress_bar.setValue(min(1000, int(done * 1000 / total)))
            self.percent_label.setText('<1%' if 0 < done < total / 100 else f'{min(100, done * 100 / total):.0f}%')
        status = value.get('status', '')
        text = status
        if self.operation == 'prepare':
            self.task_count.setText('1 个任务')
            component = 'GPT-SoVITS 语音资源' if self.last_component == 'voice' else 'TachiTalk 主程序更新'
            parts = f" · 第 {value['part']} / {value['parts']} 个分卷" if 'part' in value else ''
            self.task_title.setText(component + ' · ' + status + parts)
        if value.get('source'):
            self.source_label.setText('当前来源：' + value['source'])
        if value.get('source_reason'):
            self.modelscope_status.setText('本次采用魔搭')
            self.modelscope_detail.setText(value['source_reason'])
            self.network_note.setText('最终渠道：' + value['source'] + '；' + value['source_reason'])
        if total and self.preparing_since is None:
            speed = value.get('speed', 0)
            speed_text = f'{size_text(speed)}/s' if speed else '速度计算中'
            self.transfer_details.setText(f'{size_text(done)} / {size_text(total)}　·　{speed_text}')
            if speed > 0:
                seconds = max(0, int((total - done) / speed))
                minutes, seconds = divmod(seconds, 60)
                self.eta_label.setText(f'预计剩余 {minutes} 分 {seconds} 秒')
            else:
                self.eta_label.setText('正在验证' if done == total else '预计剩余：计算中')
        if value.get('error'):
            text += '；' + value['error']
        self.state.setToolTip(text)
        self.state.setText(text)

    def detect_network(self, *, for_install=False):
        if self.busy or self.shutting_down:
            return
        self.close_network_prompt()
        self.install_after_probe = for_install
        if for_install:
            self.begin_preparation()
        self.github_status.setText('正在检测…')
        self.github_status.setStyleSheet('')
        self.modelscope_status.setText('正在检测…')
        self.modelscope_status.setStyleSheet('')
        self.github_detail.setText('安装检查当前下载渠道；手动检测时同时检查 GitHub')
        set_proxy_state(self, 'checking', '正在读取代理设置…')
        self.start('diagnose', lambda progress, stop: asyncio.run(self.client.diagnose(
            self.envelopes.get('voice'), stop=stop, progress=progress, include_github=not for_install)))

    def close_network_prompt(self):
        if self.network_prompt:
            self.network_prompt.reject()
            self.network_prompt.deleteLater()
            self.network_prompt = None

    def open_network_prompt(self, result, *, can_continue):
        requested = self.install_after_probe
        self.close_network_prompt()
        self.install_after_probe = requested
        dialog = NetworkPrompt(result, self.panel, can_continue=can_continue)
        self.network_prompt = dialog
        dialog.rejected.connect(lambda: setattr(self, 'install_after_probe', False))
        def repeat():
            pending = self.install_after_probe
            self.detect_network(for_install=pending)
        def proceed():
            if not self.install_after_probe or self.busy or self.shutting_down:
                return
            self.close_network_prompt()
            self.install_after_probe = False
            self.begin_download('voice', confirm=self.confirm_after_probe)
        dialog.retry_requested.connect(repeat)
        dialog.continue_requested.connect(proceed)
        def use_modelscope():
            try:
                config = self.client.configuration()
                from app.updates.download import sources
                mirror = next(s for s in sources(config) if s.get('layout') == 'modelscope')
                self.close_network_prompt()
                self.apply_source_choice(mirror['name'])
            except (OSError, ValueError, StopIteration) as error:
                self.state.setText(f'魔搭配置不可用：{error}')
        dialog.modelscope_requested.connect(use_modelscope)
        dialog.open()

    def install_voice(self, *, confirm=True):
        if self.busy:
            return
        self.begin_preparation()
        self.confirm_after_probe = confirm
        if 'voice' not in self.envelopes:
            self.github_status.setText('正在读取可信清单…')
            self.start('voice-manifest', lambda progress, stop: asyncio.run(
                self.client.voice_manifest(progress, stop=stop)))
            return
        self.begin_download('voice', confirm=confirm)

    def remove_voice(self):
        if QMessageBox.question(self, '卸载可选语音', '将关闭主程序并卸载本目录托管的语音文件；旧版外部目录、修改过的文件及用户数据会保留。是否继续？') == QMessageBox.StandardButton.Yes:
            self.launch_updater(None)

    def update_main(self):
        if self.busy or self.shutting_down:
            return
        if not FROZEN:
            self.state.setText('源码开发模式请使用 Git 更新；覆盖安装仅用于冻结安装版。')
            return
        if not main_feed.ENABLED or self.main_result['state'] != 'update_available':
            self.check()
            return
        from app.updates.download import sources
        try:
            choices = [s['name'] for s in sources(self.client.configuration())
                if s.get('layout') == 'modelscope' or not s.get('prefix')]
            selected, ok = QInputDialog.getItem(self, '主程序更新来源',
                '选择下载来源；切换已有任务的来源会清理该任务缓存并从零下载。', choices, 0, False)
            if not ok or not selected:
                return
            self.main_source = selected
            version = self.main_result['version']
            self.start('main-manifest', lambda progress, stop: asyncio.run(
                self.client.main_manifest(version, progress, stop=stop, selected_source=selected)))
        except (OSError, ValueError) as error:
            self.state.setText(f'无法检查主程序更新：{error}')

    def begin_download(self, component, *, confirm=True):
        if self.busy:
            return
        try:
            envelope = self.envelopes.get(component)
            if envelope is None:
                self.start('load-' + component, lambda progress, stop: self.client.cached(component))
                return
            payload = envelope['payload']
            if component == 'main' and payload['base_version'] != VERSION:
                raise ValueError('此增量包不适用于当前版本，请下载完整主程序安装包迁移')
            if payload['archive']['sha256'] in self.client.configuration().get('restart_archives', []):
                self.reset_selected_download(component, confirm=confirm)
                return
            if component == 'voice' and confirm:
                answer = QMessageBox.question(self, '安装独立语音组件',
                    f"版本 {payload['version']}，需下载 {size_text(payload['archive']['size'])}。\n"
                    '将安装或修复 GPT-SoVITS 运行环境与配音资源，完成下载后关闭软件安装并重启。是否继续？')
                if answer != QMessageBox.StandardButton.Yes:
                    self.finish_preparation()
                    return
            if component == 'voice':
                self.begin_preparation()
            self.last_component = component
            self.task_title.setText('正在准备语音资源下载' if component == 'voice' else '正在准备主程序更新')
            self.task_count.setText('1 个任务')
            if component == 'main':
                self.start('prepare', lambda progress, stop: asyncio.run(self.client.prepare(
                    envelope, progress, stop, selected_source=self.main_source)))
            else:
                self.start('prepare', lambda progress, stop: asyncio.run(self.client.prepare(envelope, progress, stop)))
        except Exception as error:
            self.finish_preparation()
            self.state.setText(f'{error}；请先检查资源版本或导入维护者签名清单。')

    def retry(self):
        if self.last_component:
            self.begin_download(self.last_component, confirm=False)

    def pause(self):
        self.finish_preparation()
        self.pending_source_switch = False
        self.install_after_probe = self.install_after_check = False
        self.stop.set()

    def cancel_download(self):
        self.pause()
        self.state.setText('正在取消当前任务；保留缓存，可稍后继续或在下载设置中删除。')

    def select_source(self):
        try:
            from app.updates.download import sources
            config = self.client.configuration()
            choices = ['自动选择（GitHub < 250 ms，否则魔搭）'] + [s['name'] for s in sources(config)]
            current = self.main_source if self.last_component == 'main' else config.get('preferred_download_source')
            index = choices.index(current) if current in choices else 0
            selected, ok = QInputDialog.getItem(self, '切换下载来源',
                '更换来源将停止当前连接，删除本任务的下载缓存，再从 0% 重新下载。', choices, index, False)
            if not ok:
                return
            preferred = None if selected == choices[0] else selected
            if preferred == current:
                return
            self.apply_source_choice(preferred)
        except (OSError, ValueError) as error:
            self.state.setText(f'无法切换来源：{error}')

    def apply_source_choice(self, preferred):
        """All manual entries share the stop/reset/download protocol."""
        try:
            config = self.client.configuration()
            if self.last_component == 'main':
                self.main_source = preferred
            else:
                config['preferred_download_source'] = preferred
            if self.last_component in self.envelopes:
                pending = set(config.get('restart_archives', []))
                pending.add(self.envelopes[self.last_component]['payload']['archive']['sha256'])
                config['restart_archives'] = sorted(pending)
            else:
                config['reset_voice_on_next_install'] = True
            atomic_json(self.client.config_path, config)
            self.config.setPlainText(json.dumps(config, ensure_ascii=False, indent=2))
            self.source_label.setText('来源：' + (preferred or '自动测速 · GitHub / 魔搭'))
            if self.busy and self.operation == 'prepare':
                self.pending_source_switch = True
                self.stop.set()
                self.state.setText('正在停止旧连接；结束后清理本任务缓存，从所选来源重新下载…')
            elif not self.busy and self.last_component in self.envelopes:
                self.reset_selected_download()
        except (OSError, ValueError) as error:
            self.state.setText(f'无法切换来源：{error}')

    def reset_selected_download(self, component=None, *, confirm=False):
        if self.shutting_down or self.busy:
            return
        component = component or self.last_component
        envelope = self.envelopes.get(component)
        if not envelope:
            self.state.setText('来源已更改；未找到当前任务清单，没有清理缓存。')
            return
        self.last_component = component
        self.confirm_after_reset = confirm
        self.start('reset-download', lambda progress, stop: self.client.reset_download(envelope, stop))

    def show_release_notes(self):
        QDesktopServices.openUrl(QUrl(f'https://github.com/{REPOSITORY}/releases'))

    def open_settings(self):
        if self.settings_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle('TachiTalk · 下载设置')
            dialog.resize(680, 540)
            dialog.setStyleSheet(STYLE)
            layout = QVBoxLayout(dialog)
            layout.addWidget(label('下载设置', title=True))
            layout.addWidget(label('新在线任务检测 GitHub：首字节 < 250 ms 使用 GitHub，否则使用魔搭。魔搭无需注册。', muted=True))
            self.proxy_check = QCheckBox('允许使用已配置的公共备用代理')
            layout.addWidget(self.proxy_check)
            advanced = QPushButton('高级：编辑下载源配置')
            advanced.setCheckable(True)
            advanced.toggled.connect(self.config.setVisible)
            layout.addWidget(advanced)
            layout.addWidget(self.config, 1)
            self.config.hide()
            row = QHBoxLayout()
            row.addWidget(self.clear_button)
            row.addWidget(self.uninstall_button)
            self.clear_button.show()
            self.uninstall_button.show()
            layout.addLayout(row)
            layout.addWidget(label('卸载仅处理本程序托管的语音文件；旧版语音和用户修改的文件会保留。', muted=True))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
            buttons.accepted.connect(self.save_config)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            self.settings_dialog = dialog
        try:
            config = self.client.configuration()
            self.config.setPlainText(json.dumps(config, ensure_ascii=False, indent=2))
            self.proxy_was_enabled = any(s.get('enabled', True) and s.get('fallback_only')
                for kind in ('sources', 'api_sources', 'manifest_sources') for s in config.get(kind, []))
            self.proxy_check.setChecked(self.proxy_was_enabled)
        except (OSError, ValueError):
            self.config.show()
        self.settings_dialog.open()

    def shutdown(self):
        self.shutting_down = True
        self.pause()
        self.close_network_prompt()

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
            if self.settings_dialog is not None:
                if self.proxy_check.isChecked() != getattr(self, 'proxy_was_enabled', self.proxy_check.isChecked()):
                    for kind in ('sources', 'api_sources', 'manifest_sources'):
                        for item in config.get(kind, []):
                            if item.get('fallback_only'):
                                item['enabled'] = self.proxy_check.isChecked()
            for kind in ('sources', 'api_sources', 'manifest_sources'):
                for source in sources(config, kind):
                    Policy().source_url(f'https://github.com/{REPOSITORY}/releases/download/v1.3.0/voice-manifest.json', source)
            enabled = {source['name'] for source in sources(config)}
            if config.get('preferred_download_source') not in enabled:
                config['preferred_download_source'] = None
            atomic_json(self.client.config_path, config)
            self.state.setText('下载源已保存，下次检查或下载时生效')
            self.refresh_summary()
            if self.settings_dialog is not None:
                self.settings_dialog.accept()
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
                '--result', str(self.client.directory / 'install-result.json'), '--restart', '--show-progress']
            if prepared:
                command += ['--manifest', str(prepared['manifest']), '--archive', str(prepared['archive'])]
            else:
                command += ['--uninstall-voice']
            return command
        self.start('handoff', prepare_command)

