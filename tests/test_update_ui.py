import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
import sys
import traceback
import unittest
from unittest.mock import AsyncMock, patch

from PySide6.QtCore import QTimer, Signal, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QDialog, QMessageBox, QPlainTextEdit, QStackedWidget, QPushButton, QLabel
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.ui.update_controls import UpdateControls, UpdatePrompt
from app.updates.client import UpdateClient
from app.updates.download import Downloader, Policy
from app.updates.manifest import canonical, atomic_json
from app.paths import voice_location
from app.version import VERSION
from tests.test_updates import bundle


class Panel(QMainWindow):
    closing = Signal()


class UpdateUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # These cases verify the retained closed-gate mode, independent of the
        # production gate opened only after anonymous feed verification.
        gate = patch('app.updates.main_feed.ENABLED', False)
        gate.start()
        self.addCleanup(gate.stop)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = Panel()
        self.addCleanup(self.panel.close)
        self.client = UpdateClient(root=self.root, data=self.root / 'data')
        async def connected(*args, **kwargs):
            return {'state': 'ok', 'manifest': {'state': 'ok', 'latency_ms': 12, 'detail': 'HTTP 206'},
                'artifact': {'state': 'ok', 'latency_ms': 18, 'detail': 'HTTP 206'},
                'proxy': {'state': 'not_found', 'summary': '未发现系统 / 环境代理'},
                'manifest_error': ''}
        # Existing installer UI tests stay offline; real transport has its own HTTP tests.
        diagnostic = patch.object(self.client, 'diagnose', connected, create=True)
        diagnostic.start()
        self.addCleanup(diagnostic.stop)
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        self.payload, _ = bundle(base=VERSION)
        self.payload['version'] = '.'.join([*VERSION.split('.')[:2], str(int(VERSION.split('.')[2]) + 1)])
        self.envelope = {'key_id': 'test', 'payload': self.payload,
                         'signature': base64.b64encode(key.sign(canonical(self.payload))).decode()}
        self.ui = UpdateControls(self.panel, self.client)
        self.addCleanup(self.cleanup_ui)

    def cleanup_ui(self):
        self.ui.pause()
        if self.ui.thread:
            self.ui.thread.join(timeout=3)
        self.ui.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wait_idle(self):
        deadline = time.monotonic() + 5
        # A finished preflight thread can still have a queued Qt result that starts
        # the real download. Wait for both UI and worker, within the same deadline.
        while time.monotonic() < deadline:
            QApplication.processEvents()
            # Yield Python's GIL as a real Qt event loop does, so both the local
            # HTTP server and asyncio download worker can make progress.
            time.sleep(.001)
            if not self.ui.busy and not (self.ui.thread and self.ui.thread.is_alive()):
                break
        detail = ''
        if self.ui.busy:
            frame=sys._current_frames().get(self.ui.thread.ident) if self.ui.thread else None
            detail=f'operation={self.ui.operation}; state={self.ui.state.text()}\n'
            if frame is not None:
                detail+=''.join(traceback.format_stack(frame))
        self.assertFalse(self.ui.busy,detail)
        self.assertFalse(bool(self.ui.thread and self.ui.thread.is_alive()))

    def test_closed_update_entry_does_not_start_manual_or_automatic_network_checks(self):
        check = AsyncMock(return_value={'manifests': {}, 'errors': {},
                                        'main': {'state': 'disabled', 'version': None}})
        with patch.object(self.client, 'check', check):
            for automatic in (False, True):
                self.ui.check(automatic=automatic)
                self.wait_idle()
        check.assert_not_awaited()
        self.assertIn('暂未开放', self.ui.main_status.text())
        self.assertTrue(self.ui.check_button.isHidden() or not self.ui.check_button.isEnabled())
        self.assertIsNone(self.ui.prompt)

    def test_first_voice_install_starts_independent_manifest_worker_without_update_check(self):
        with patch.object(self.ui, 'start') as start, patch.object(self.ui, 'check') as check:
            self.ui.install_voice()
        check.assert_not_called()
        self.assertEqual(start.call_count, 1)
        self.assertEqual(start.call_args.args[0], 'voice-manifest')
        self.assertTrue(self.ui.install_button.isEnabled(), 'A missing manifest must not disable voice installation')

    def test_queued_old_update_result_cannot_reopen_main_updates_or_popup(self):
        self.ui.envelopes['main'] = self.envelope
        with patch.object(self.ui, 'begin_download') as begin:
            self.ui.on_finished('check', {'value': {'manifests': {'main': self.envelope},
                'errors': {}, 'main': {'state': 'update_available', 'version': self.payload['version']}}})
        begin.assert_not_called()
        self.assertNotIn('main', self.ui.envelopes)
        self.assertEqual(self.ui.main_result['state'], 'disabled')
        self.assertIsNone(self.ui.prompt)
        self.assertFalse(self.ui.update_button.isEnabled())

    def test_resource_page_has_no_cloudflare_card_settings_or_hint(self):
        texts = [item.text() for item in self.ui.findChildren(QLabel)]
        texts.extend(item.text() for item in self.ui.findChildren(QPushButton))
        self.assertFalse(any('Cloudflare' in text or 'jieyiblog.me' in text for text in texts), texts)
        self.assertFalse(hasattr(self.ui, 'cloudflare_status'))
        self.assertIsNotNone(getattr(self.ui, 'modelscope_status', None))

    def test_update_prompt_includes_metadata_and_later_keeps_panel_alive(self):
        self.panel.show()
        prompt = UpdatePrompt(self.payload, self.panel)
        prompt.show()
        self.assertIn(VERSION, prompt.details.text())
        self.assertIn(self.payload['version'], prompt.details.text())
        self.assertIn('2026-10-22', prompt.details.text())
        self.assertEqual(prompt.findChild(QPlainTextEdit).toPlainText(), self.payload['notes'])
        prompt.reject()
        self.assertEqual(prompt.result(), QDialog.DialogCode.Rejected)
        self.assertTrue(self.panel.isVisible())
        prompt.deleteLater()

    def test_modelscope_is_visible_as_an_available_voice_download_channel(self):
        self.assertNotIn('Cloudflare', self.ui.settings_button.text())
        self.assertNotIn('暂未接入', self.ui.modelscope_status.text())

    def test_cancelled_or_failed_detection_does_not_stay_checking_modelscope(self):
        self.ui.modelscope_status.setText('正在检测…')
        self.ui.stop.set()
        self.ui.on_finished('diagnose', {'value': {'state':'cancelled'}})
        self.assertIn('已取消', self.ui.modelscope_status.text())
        self.ui.stop.clear()
        self.ui.modelscope_status.setText('正在检测…')
        self.ui.on_finished('diagnose', {'error':'network failure'})
        self.assertEqual(self.ui.modelscope_status.text(), '检测失败')

    def test_all_sources_disabled_keeps_settings_usable(self):
        config = self.client.configuration()
        config['sources'] = []
        atomic_json(self.client.config_path, config)
        self.ui.refresh_summary()
        self.assertIn('未启用下载源', self.ui.settings_button.text())

    def test_github_failure_offers_switch_to_modelscope(self):
        from app.ui.update_network import NetworkPrompt
        dialog = NetworkPrompt({'state':'failed','channel':'GitHub','prefix':'',
            'manifest':{'state':'timeout'}, 'artifact':{'state':'timeout'},
            'proxy':{'state':'not_found','summary':'未发现代理'}}, self.panel)
        self.assertEqual(dialog.modelscope_button.text(), '改用魔搭')
        dialog.deleteLater()

    def test_queued_full_installer_result_never_prompts_or_starts_download_while_updates_closed(self):
        installer = {'url': 'https://github.com/maruyui-dev/TachiTalk/releases/download/v9.0.0/TachiTalk-v9.0.0-main.zip',
                     'size': 123456}
        with patch.object(self.ui, 'begin_download') as begin, \
             patch('app.ui.update_controls.QDesktopServices.openUrl') as open_url:
            self.ui.on_finished('check', {'value': {'manifests': {}, 'errors': {},
                'main': {'state': 'no_patch', 'version': '9.0.0', 'installer': installer,
                         'title': '新版本', 'notes': '改进', 'published_at': '2026-10-23'}}})
            self.assertIsNone(self.ui.prompt)
            begin.assert_not_called()
            open_url.assert_not_called()


    def test_voice_manifest_and_download_workers_keep_qt_heartbeat_running(self):
        calls, beats = [], []
        payload, _ = bundle(component='voice', name='services/gpt_sovits/api_v2.py', base='*')
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        envelope = {'key_id': 'test', 'payload': payload,
                    'signature': base64.b64encode(key.sign(canonical(payload))).decode()}
        async def manifest(progress, **kwargs):
            calls.append(threading.get_ident())
            await asyncio.sleep(.18)
            return envelope
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: beats.append(1))
        timer.start()
        with patch.object(self.client, 'voice_manifest', manifest), patch.object(self.ui, 'begin_download') as begin:
            self.ui.install_voice()
            self.wait_idle()
            begin.assert_called_once()
            self.assertEqual(begin.call_args.args, ('voice',))
        timer.stop()
        self.assertNotEqual(calls[0], threading.get_ident())
        self.assertGreater(len(beats), 4)
        self.assertIsNone(self.ui.prompt)
        self.ui.envelopes['voice'] = envelope
        async def prepare(envelope, progress, stop):
            calls.append(threading.get_ident())
            await asyncio.sleep(.15)
            return {'payload': payload, 'archive': self.root / 'offline.zip', 'manifest': self.root / 'manifest.json'}
        with patch.object(self.client, 'prepare', prepare), patch.object(self.ui, 'launch_updater') as launch, \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.ui.install_button.click()
            self.wait_idle()
            launch.assert_called_once()
        self.assertNotEqual(calls[-1], threading.get_ident())

    def test_unavailable_sources_leave_window_and_settings_usable(self):
        self.panel.show()
        async def fail(progress, **kwargs):
            raise ValueError('all sources unavailable')
        with patch.object(self.client, 'voice_manifest', fail):
            self.ui.install_voice()
            self.wait_idle()
        self.assertIn('all sources unavailable', self.ui.state.text())
        self.assertTrue(self.ui.install_button.isEnabled())
        self.assertTrue(self.ui.config.isEnabled())
        self.assertTrue(self.panel.isVisible())

    def test_main_check_error_and_voice_availability_have_independent_labels(self):
        voice, _ = bundle(component='voice', name='services/gpt_sovits/api_v2.py', base='*')
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        envelope = {'key_id': 'test', 'payload': voice,
                    'signature': base64.b64encode(key.sign(canonical(voice))).decode()}
        with patch('app.ui.update_controls.voice_status', return_value={'installed': False, 'version': '未安装'}):
            self.ui.on_finished('check', {'value': {'manifests': {'voice': envelope},
                'errors': {'main': 'HTTP 404'}, 'main': {'state': 'unknown', 'version': None}}})
        self.assertIn('暂未开放', getattr(self.ui, 'main_status', QLabel()).text())
        self.assertIn('可安装', getattr(self.ui, 'voice_state', QLabel()).text())
        self.assertTrue(self.ui.install_button.isEnabled())
        self.assertFalse(self.ui.update_button.isEnabled())

    def test_current_check_clears_stale_main_patch_without_hiding_voice(self):
        self.ui.envelopes['main'] = self.envelope
        self.ui.on_finished('check', {'value': {'manifests': {}, 'errors': {},
            'main': {'state': 'current', 'version': '1.3.0'}}})
        self.assertNotIn('main', self.ui.envelopes)
        self.assertFalse(self.ui.update_button.isEnabled())

    def test_download_progress_reports_percentage_speed_eta_and_source(self):
        self.ui.progress_changed({'status': '下载中', 'source': 'GitHub', 'done': 512 * 1024**2,
            'total': 1024**3, 'speed': 2 * 1024**2, 'part': 2, 'parts': 4})
        self.assertEqual(self.ui.progress_bar.value(), 500)
        self.assertIn('2.0 MiB/s', getattr(self.ui, 'transfer_details', QLabel()).text())
        self.assertIn('4 分 16 秒', getattr(self.ui, 'eta_label', QLabel()).text())
        self.assertIn('GitHub', getattr(self.ui, 'source_label', QLabel()).text())

    def test_new_task_routing_displays_detection_ms_channel_and_reason(self):
        self.ui.progress_changed({'status': '正在检测 GitHub 实际分卷链路', 'routing': {'state': 'checking'}})
        self.assertIn('正在检测', self.ui.github_status.text())
        reason = 'GitHub 首字节 250.00 ms，大于或等于 250 ms'
        self.ui.progress_changed({'status': '采用魔搭', 'source': '魔搭', 'routing': {
            'source': '魔搭', 'reason': reason, 'probe': {'state': 'ok', 'latency_ms': 250}}})
        self.assertIn('250.00 ms', self.ui.github_status.text())
        self.assertIn('魔搭', self.ui.source_label.text())
        self.assertIn(reason, self.ui.modelscope_detail.text())
        self.assertIn('重定向', self.ui.network_note.text())
        self.assertIn('首字节', self.ui.network_note.text())

    def test_failed_github_routing_never_displays_a_fake_zero_ms(self):
        reason = 'GitHub 探测超时或异常：连接超时'
        self.ui.progress_changed({'status': '采用魔搭', 'source': '魔搭', 'routing': {
            'source': '魔搭', 'reason': reason, 'probe': {'state': 'timeout', 'detail': '连接超时'}}})
        self.assertIn('超时', self.ui.github_status.text())
        self.assertNotIn('0 ms', self.ui.github_status.text())
        self.assertNotIn('0.00 ms', self.ui.github_status.text())
        self.assertIn(reason, self.ui.modelscope_detail.text())
        self.assertIn('魔搭', self.ui.source_label.text())

    def test_long_source_error_does_not_stretch_page_horizontally(self):
        self.panel.setCentralWidget(self.ui)
        self.panel.resize(1100,900)
        self.panel.show()
        QTest.qWait(50)
        width=self.panel.width()
        self.ui.progress_changed({'status':'重试 / 切换下载源','source':'GHFast（官方失败后自动尝试）',
            'error':'ConnectionTimeoutError: https://download.example.com/'+'verylongpath'*300})
        self.ui.github_detail.setText('https://download.example.com/'+'verylongpath'*300)
        self.ui.modelscope_detail.setText('https://download.example.com/'+'verylongpath'*300)
        QTest.qWait(100)
        self.assertEqual(self.panel.width(),width)
        self.assertLessEqual(self.ui.widget().width(),self.ui.viewport().width())
        self.assertEqual(self.ui.horizontalScrollBar().maximum(),0)

    def test_install_shows_preparation_hint_instead_of_a_stuck_zero_percent(self):
        with patch.object(self.ui,'start'):
            self.ui.install_voice()
        hint=getattr(self.ui,'preparation_hint',QLabel())
        self.assertIn('5 分钟',hint.text())
        self.assertFalse(hint.isHidden())
        self.assertEqual(self.ui.percent_label.text(),'准备中')
        self.assertEqual(self.ui.progress_bar.maximum(),0)
        self.ui.on_finished('voice-manifest',{'error':'offline'})
        self.assertEqual(self.ui.progress_bar.maximum(),1000)

    def test_preparation_elapsed_is_real_and_first_bytes_end_preparation(self):
        with patch.object(self.ui,'start'):
            self.ui.install_voice()
        self.ui.progress_changed({'status':'准备下载 / 验证缓存','done':0,'total':5*1024**3})
        self.assertEqual(self.ui.percent_label.text(),'准备中')
        with patch('app.ui.update_controls.monotonic',return_value=self.ui.preparing_since+301):
            self.ui.refresh_preparation_elapsed()
        self.assertIn('5 分 1 秒',self.ui.eta_label.text())
        self.ui.progress_changed({'status':'下载中','done':1024**2,'total':5*1024**3,'speed':1024**2})
        self.assertIsNone(self.ui.preparing_since)
        self.assertFalse(self.ui.preparation_timer.isActive())
        self.assertEqual(self.ui.percent_label.text(),'<1%')

    def test_install_without_manifest_fetches_voice_directly_and_does_not_loop_on_failure(self):
        with patch.object(self.ui, 'start') as start, patch.object(self.ui, 'check') as check:
            self.ui.install_voice()
            check.assert_not_called()
            self.assertEqual(start.call_args.args[0], 'voice-manifest')
        self.ui.on_finished('voice-manifest', {'error': 'timeout'})
        self.wait_idle()
        self.assertFalse(self.ui.install_after_check)
        self.assertFalse(self.ui.busy)

    def test_install_prepares_directly_and_manual_diagnostics_never_install(self):
        self.ui.envelopes['voice'] = dict(self.envelope, payload=dict(self.payload, component='voice'))
        calls = []
        async def diagnose(*args, **kwargs):
            calls.append(('diagnose', threading.get_ident()))
            return {'state': 'ok', 'manifest': {'state': 'ok', 'latency_ms': 4},
                'artifact': {'state': 'ok', 'latency_ms': 6},
                'proxy': {'state': 'not_found', 'summary': '未发现系统代理'}}
        async def prepare(*args):
            calls.append(('prepare', threading.get_ident()))
            raise ValueError('test stops before installer')
        with patch.object(self.client, 'diagnose', diagnose), patch.object(self.client, 'prepare', prepare), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.ui.install_voice()
            self.wait_idle()
            QTest.qWait(40)
            self.wait_idle()
        self.assertEqual([call[0] for call in calls], ['prepare'])
        self.assertTrue(all(call[1] != threading.get_ident() for call in calls))
        calls.clear()
        with patch.object(self.client, 'diagnose', diagnose), patch.object(self.client, 'prepare', prepare):
            getattr(self.ui, 'detect_network', lambda: None)()
            self.wait_idle()
        self.assertEqual([call[0] for call in calls], ['diagnose'])

    def test_failed_manual_probe_offers_modelscope_without_preparing_or_claiming_ready(self):
        self.ui.envelopes['voice'] = self.envelope
        async def failed(*args, **kwargs):
            return {'state': 'failed', 'manifest': {'state': 'ok', 'latency_ms': 9},
                'artifact': {'state': 'timeout', 'detail': '连接超时'},
                'proxy': {'state': 'not_found', 'summary': '未发现系统代理'}}
        with patch.object(self.client, 'diagnose', failed), patch.object(self.client, 'prepare') as prepare, \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            self.ui.detect_network()
            if self.ui.thread:
                self.wait_idle()
        prepare.assert_not_called()
        dialog = getattr(self.ui, 'network_prompt', None)
        self.assertIsNotNone(dialog, 'failed resource preflight must show the designed recovery dialog')
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.modelscope_button.isEnabled())
        self.assertIn('魔搭', dialog.modelscope_button.text())
        dialog.reject()
        self.assertFalse(self.ui.install_after_probe)

    def test_shutdown_during_diagnostics_never_downloads(self):
        self.ui.envelopes['voice'] = self.envelope
        entered = threading.Event()
        async def delayed(*args, **kwargs):
            entered.set()
            await asyncio.sleep(.08)
            return {'state': 'ok', 'manifest': {'state': 'ok'}, 'artifact': {'state': 'ok'},
                'proxy': {'state': 'unknown', 'summary': '代理状态无法确认'}}
        with patch.object(self.client, 'diagnose', delayed), patch.object(self.client, 'prepare') as prepare, \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            self.ui.detect_network()
            self.assertTrue(entered.wait(.5), 'manual detection must run in a worker')
            self.ui.shutdown()
            self.wait_idle()
        prepare.assert_not_called()

    def test_detection_card_does_not_claim_connectivity_before_probe(self):
        self.assertIsNotNone(getattr(self.ui, 'network_check_button', None))
        self.assertIn('尚未检测', getattr(self.ui, 'modelscope_status', QLabel()).text())
        self.assertIn('尚未检测', getattr(self.ui, 'github_status', QLabel()).text())

    def test_proxy_state_changes_icon_badge_and_accessible_description(self):
        from app.ui.update_network import show_network_result
        icon = getattr(self.ui, 'proxy_icon', None)
        self.assertIsNotNone(icon, 'proxy status needs its own stateful icon')
        images = []
        for state, summary, color in [('detected', '检测到系统 / 环境代理设置', '#23844c'),
                ('not_found', '未发现系统 / 环境代理', '#69758b'),
                ('unknown', '代理状态无法确认', '#a96813')]:
            show_network_result(self.ui, {'state': 'ok', 'manifest': {'state': 'ok'},
                'artifact': {'state': 'ok'}, 'proxy': {'state': state, 'summary': summary}})
            self.assertEqual(icon.accessibleName(), summary)
            self.assertIn(color, self.ui.proxy_status.styleSheet())
            self.assertEqual(self.ui.proxy_status.text(), summary)
            images.append(icon.pixmap().toImage())
        self.assertNotEqual(images[0], images[1], 'detected and absent need visibly different icons')
        self.assertNotEqual(images[1], images[2], 'absent and unknown must not share a badge')
        with patch.object(self.ui, 'start'):
            self.ui.detect_network()
        self.assertIn('正在读取', self.ui.proxy_status.text())
        self.assertNotEqual(icon.pixmap().toImage(), images[0], 'new checks must clear the old positive icon')

    def test_resource_navigation_embeds_page_and_returns_to_existing_pages(self):
        from app.ui.control_panel import load_window
        panel = load_window()
        try:
            with patch('app.ui.update_controls.UpdateClient', return_value=self.client):
                panel.findChild(QPushButton, 'navDelivery').click()
            stack = panel.findChild(QStackedWidget, 'pageStack')
            self.assertEqual(stack.currentWidget(), panel.update_controls)
            self.assertFalse(panel.update_controls.isWindow())
            self.assertEqual(panel.findChild(QLabel, 'pageTitle').text(), '更新与语音资源')
            self.assertFalse(panel.findChild(QPushButton, 'navCharacter').isChecked())
            self.assertTrue(panel.findChild(QPushButton, 'saveButton').isHidden())
            panel.findChild(QPushButton, 'navCharacter').click()
            self.assertEqual(stack.currentIndex(), 0)
            self.assertFalse(panel.findChild(QPushButton, 'navDelivery').isChecked())
        finally:
            self.app.processEvents()  # Drain the panel's initial fit timers before deleting its labels.
            panel.close()
            panel.deleteLater()

    def test_explicit_pause_or_cancel_overrides_pending_source_switch(self):
        for stop in (self.ui.pause, self.ui.cancel_download):
            self.ui.pending_source_switch = True
            stop()
            with patch.object(self.ui, 'retry') as retry, patch.object(self.ui, 'launch_updater') as launch:
                self.ui.on_finished('prepare', {'value': {'payload': self.payload}})
                QTest.qWait(20)
                retry.assert_not_called()
                launch.assert_not_called()

    def test_source_switch_clears_only_current_task_before_restarting_at_zero(self):
        self.ui.envelopes['voice'] = self.envelope
        self.ui.last_component = 'voice'
        cache = self.client.directory / 'downloads' / self.payload['archive']['sha256']
        cache.mkdir(parents=True)
        (cache / '0000.bin.part').write_bytes(b'old source prefix')
        other = cache.parent / ('f' * 64)
        other.mkdir()
        (other / 'keep.bin').write_bytes(b'other task')
        self.ui.operation = 'prepare'
        self.ui.set_busy(True)
        calls = []
        async def prepare(*args):
            calls.append(cache.exists())
            raise ValueError('test ends before HTTP')
        selected = self.client.configuration()['sources'][1]['name']
        with patch('app.ui.update_controls.QInputDialog.getItem', return_value=(selected, True)), \
             patch.object(self.client, 'prepare', prepare):
            self.ui.select_source()
            self.assertTrue(cache.exists(), 'must not clear while old worker is active')
            self.ui.on_finished('prepare', {'error': 'Paused'})
            QTest.qWait(60)
            self.wait_idle()
        self.assertEqual(calls, [False], 'selected source must start after its old task cache is cleared')
        self.assertEqual((other / 'keep.bin').read_bytes(), b'other task')

    def test_source_switch_waits_for_worker_then_retries_exactly_once(self):
        configured = self.client.configuration()
        selected = configured['sources'][1]['name']
        self.ui.operation = 'prepare'
        self.ui.last_component = 'voice'
        self.ui.envelopes['voice'] = self.envelope
        self.ui.set_busy(True)
        with patch('app.ui.update_controls.QInputDialog.getItem', return_value=(selected, True)):
            self.ui.select_source()
        self.assertTrue(self.ui.stop.is_set())
        self.assertTrue(self.ui.pending_source_switch)
        self.assertEqual(self.client.configuration()['preferred_download_source'], selected)
        with patch.object(self.ui, 'retry') as retry, patch.object(self.ui, 'launch_updater') as launch:
            self.ui.on_finished('prepare', {'error': 'Paused'})
            self.wait_idle()  # Restart follows the newly required cache reset worker.
            retry.assert_called_once()
            launch.assert_not_called()

    def test_same_source_selection_does_not_discard_download(self):
        self.ui.last_component = 'voice'
        self.ui.envelopes['voice'] = self.envelope
        with patch('app.ui.update_controls.QInputDialog.getItem', return_value=('自动选择（GitHub < 250 ms，否则魔搭）', True)), \
             patch.object(self.ui, 'reset_selected_download') as reset:
            self.ui.select_source()
        reset.assert_not_called()

    def test_failed_cache_cleanup_cannot_be_bypassed_by_retry_or_install(self):
        self.ui.last_component = 'voice'
        self.ui.envelopes['voice'] = self.envelope
        selected = self.client.configuration()['sources'][1]['name']
        async def prepare(*args):
            self.fail('cache cleanup failure must block preparing from a changed source')
        with patch('app.ui.update_controls.QInputDialog.getItem', return_value=(selected, True)), \
             patch.object(self.client, 'reset_download', side_effect=PermissionError('locked cache')) as reset, \
             patch.object(self.client, 'prepare', prepare), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.ui.select_source()
            self.wait_idle()
            self.ui.retry()
            self.wait_idle()
            self.assertEqual(reset.call_count, 2, 'retry must retry failed cleanup before any new-source download')
            self.ui.install_voice()
            self.wait_idle()
            QTest.qWait(20)
            self.wait_idle()
            self.assertEqual(reset.call_count, 3, 'install must not bypass outstanding source cleanup')

    def test_pending_voice_cleanup_targets_voice_after_main_was_used(self):
        from app.updates.manifest import atomic_json
        voice = dict(self.envelope, payload=dict(self.payload, component='voice'))
        self.ui.envelopes.update(main=self.envelope, voice=voice)
        self.ui.last_component = 'main'
        config = self.client.configuration()
        config['restart_archives'] = [self.payload['archive']['sha256']]
        atomic_json(self.client.config_path, config)
        seen = []
        def reset(envelope, stop):
            seen.append(envelope['payload']['component'])
            config['restart_archives'] = []
            atomic_json(self.client.config_path, config)
        with patch.object(self.client, 'reset_download', reset), patch.object(self.ui, 'retry'):
            self.ui.begin_download('voice', confirm=False)
            self.wait_idle()
        self.assertEqual(seen, ['voice'])

    def test_switching_second_component_preserves_first_pending_reset(self):
        from app.updates.manifest import atomic_json
        first_sha = 'e' * 64
        config = self.client.configuration()
        config['restart_archives'] = [first_sha]
        atomic_json(self.client.config_path, config)
        self.ui.envelopes['main'] = self.envelope
        self.ui.last_component = 'main'
        selected = config['sources'][1]['name']
        with patch('app.ui.update_controls.QInputDialog.getItem', return_value=(selected, True)), \
             patch.object(self.ui, 'reset_selected_download'):
            self.ui.select_source()
        self.assertEqual(set(self.client.configuration()['restart_archives']),
            {first_sha, self.payload['archive']['sha256']})

    def test_failed_probe_can_explicitly_continue_existing_source_and_retry_keeps_intent(self):
        self.ui.envelopes['voice'] = self.envelope
        failed = {'state': 'failed', 'manifest': {'state': 'ok'}, 'artifact': {'state': 'timeout'},
            'proxy': {'state': 'not_found', 'summary': '未发现系统代理'}}
        self.ui.install_after_probe = True
        self.ui.open_network_prompt(failed, can_continue=True)
        with patch.object(self.ui, 'detect_network') as detect:
            self.ui.network_prompt.retry_button.click()
        detect.assert_called_once_with(for_install=True)
        with patch.object(self.ui, 'begin_download') as begin:
            self.ui.network_prompt.continue_button.click()
        begin.assert_called_once_with('voice', confirm=True)
        self.assertFalse(self.ui.install_after_probe)

    def test_new_check_invalidates_cached_main_retry_and_previous_prompt(self):
        self.client.import_manifest(self.write_manifest())
        self.ui.envelopes['main'] = self.envelope
        self.ui.last_component = 'main'
        self.ui.prompt = UpdatePrompt(self.payload, self.panel)
        self.ui.prompt.show()
        self.ui.on_finished('check', {'value': {'manifests': {}, 'errors': {},
            'main': {'state': 'no_patch', 'version': '1.3.9'}}})
        with patch.object(self.client, 'cached') as cached, patch.object(self.ui, 'start') as start:
            self.ui.retry()
            self.ui.update_main()
            cached.assert_not_called()
            self.assertFalse(any(call.args[0] in ('load-main', 'prepare') for call in start.call_args_list))
        self.assertTrue(self.ui.prompt is None or not self.ui.prompt.isVisible())

    def write_manifest(self):
        path = self.root / 'signed-main.json'
        atomic_json(path, self.envelope)
        return path

    def test_settings_preserve_explicit_proxy_disables_in_advanced_json(self):
        self.ui.open_settings()
        config = self.client.configuration()
        config['sources'].append({'name': 'GHFast saved relay', 'prefix': 'https://ghfast.top/',
                                  'enabled': True, 'fallback_only': True})
        for kind in ('sources', 'api_sources', 'manifest_sources'):
            for source in config[kind]:
                if source.get('fallback_only'):
                    source['enabled'] = False
        self.ui.config.setPlainText(json.dumps(config))
        self.ui.save_config()
        saved = self.client.configuration()
        self.assertFalse(any(source.get('enabled', True) for kind in ('sources', 'api_sources', 'manifest_sources')
            for source in saved[kind] if source.get('fallback_only')))

    def test_disabling_selected_proxy_returns_downloads_to_enabled_official_source(self):
        config = self.client.configuration()
        config['sources'].append({'name': 'GHFast saved relay', 'prefix': 'https://ghfast.top/',
                                  'enabled': True, 'fallback_only': True})
        config['preferred_download_source'] = next(s['name'] for s in config['sources'] if s.get('fallback_only'))
        atomic_json(self.client.config_path, config)
        self.ui.open_settings()
        self.ui.proxy_check.setChecked(False)
        self.ui.save_config()
        saved = self.client.configuration()
        self.assertIsNone(saved.get('preferred_download_source'))
        self.assertTrue(saved['sources'][0]['enabled'])
        self.assertFalse(any(source.get('enabled', True) for source in saved['sources'] if source.get('fallback_only')))

    def test_resource_page_can_save_and_restore_session(self):
        from app.ui.control_panel import load_window
        from app.ui.session_controls import SessionControls
        panels = []
        try:
            with patch('app.ui.update_controls.UpdateClient', return_value=self.client):
                first = load_window()
                panels.append(first)
                first.ensure_update_controls(show=True)
                session = SessionControls(first, self.root / 'delivery-session.dat')
                self.assertTrue(session.save())
                second = load_window()
                panels.append(second)
                restored = SessionControls(second, self.root / 'delivery-session.dat')
                self.assertTrue(restored.restore())
                self.assertEqual(second.findChild(QStackedWidget, 'pageStack').currentWidget().objectName(), 'deliveryPage')
        finally:
            self.app.processEvents()
            for panel in panels:
                panel.close()
                panel.deleteLater()

    def test_pause_requested_during_verification_does_not_launch_installer(self):
        self.ui.stop.set()
        with patch.object(self.ui, 'launch_updater') as launch:
            self.ui.on_finished('prepare', {'value': {'payload': self.payload}})
            launch.assert_not_called()
        self.assertIn('未启动安装', self.ui.state.text())

    def test_pause_during_handoff_preparation_does_not_start_updater(self):
        self.panel.show()
        self.ui.stop.set()
        with patch('app.ui.update_controls.subprocess.Popen') as launch:
            self.ui.on_finished('handoff', {'value': ['updater.exe']})
            launch.assert_not_called()
        self.assertTrue(self.panel.isVisible())
        self.assertIn('未启动安装', self.ui.state.text())

    def test_offline_import_confirms_verified_component_and_size_before_install(self):
        self.panel.show()
        with patch.object(self.ui, 'launch_updater') as launch, \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as question:
            self.ui.on_finished('import', {'value': {'payload': self.payload}})
            launch.assert_not_called()
            self.assertIn(self.payload['version'], question.call_args.args[2])
            self.assertIn('完整ZIP', question.call_args.args[2])
        self.assertTrue(self.panel.isVisible())

    def test_voice_button_downloads_real_http_bytes_and_verifies_before_handoff(self):
        payload, archive = bundle(component='voice', name='services/gpt_sovits/api_v2.py', base='*')
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        envelope = {'key_id': 'test', 'payload': payload,
                    'signature': base64.b64encode(key.sign(canonical(payload))).decode()}
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', str(len(archive)))
                self.send_header('ETag', '"qt-http-test"')
                self.end_headers()
                self.wfile.write(archive)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        origin = f'http://127.0.0.1:{server.server_port}'
        class LocalPolicy(Policy):
            def source_url(self, url, source):
                return origin + '/asset'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def local_downloader(configured, **kwargs):
            return Downloader(configured, policy=LocalPolicy(test_origin=origin), **kwargs)
        self.ui.envelopes['voice'] = envelope
        selected = self.client.configuration()['sources'][1]['name']
        config = self.client.configuration()
        config['preferred_download_source'] = selected
        atomic_json(self.client.config_path, config)
        selected_sources = []
        previous_downloader = local_downloader
        def selected_downloader(configured, **kwargs):
            selected_sources.extend(s['name'] for s in configured)
            return previous_downloader(configured, **kwargs)
        with patch('app.updates.client.Downloader', selected_downloader), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(self.ui, 'launch_updater') as launch:
            self.ui.install_button.click()
            self.wait_idle()
            launch.assert_called_once()
            prepared = launch.call_args.args[0]
            self.assertEqual(prepared['archive'].read_bytes(), archive)
        self.assertEqual(calls, ['/asset'])
        self.assertEqual(selected_sources, [selected])
        self.assertEqual(self.ui.progress_bar.value(), 1000)

    def test_wait_idle_tracks_detection_followed_by_download_worker(self):
        completed=threading.Event()
        payload, _ = bundle(component='voice', name='services/gpt_sovits/api_v2.py', base='*')
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        envelope = {'key_id': 'test', 'payload': payload,
                    'signature': base64.b64encode(key.sign(canonical(payload))).decode()}
        async def manifest(progress, **kwargs):
            return envelope
        async def prepare(envelope,progress,stop):
            await asyncio.sleep(.18)
            completed.set()
            return {'payload':payload,'archive':self.root/'package.zip','manifest':self.root/'manifest.json'}
        with patch.object(self.client, 'voice_manifest', manifest), \
             patch.object(self.client,'prepare',prepare), patch.object(self.ui,'launch_updater') as launch:
            self.ui.install_voice(confirm=False)
            # Force manifest discovery to finish before Qt handles its queued completion.
            # The helper must still wait for the next download operation.
            self.ui.thread.join(timeout=1)
            self.assertFalse(self.ui.thread.is_alive())
            self.wait_idle()
            self.assertTrue(completed.is_set())
            launch.assert_called_once()

    def test_legacy_installation_can_be_selected_without_copying_runtime(self):
        legacy = self.root / '旧安装 非默认路径'
        runtime = legacy / 'services/gpt_sovits/runtime/python.exe'
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b'legacy')
        atomic_json(self.root / 'data/settings/voice_location.json', {'installation': str(legacy)})
        self.assertEqual(voice_location(self.root, self.root / 'data'), legacy.resolve())
        local = self.root / 'services/gpt_sovits/runtime/python.exe'
        local.parent.mkdir(parents=True)
        local.write_bytes(b'new')
        self.assertEqual(voice_location(self.root, self.root / 'data'), self.root)

    def test_api_failure_does_not_disable_signed_attachment_checks(self):
        async def fetch(url, *args, **kwargs):
            if 'api.github.com' in url:
                raise ValueError('API unreachable')
            if 'voice-manifest' in url:
                raise ValueError('not published')
            return json.dumps(self.envelope).encode()
        with patch('app.updates.client.fetch_small', fetch):
            result = asyncio.run(self.client._discover_release())
        self.assertIn('main', result['manifests'])
        self.assertIn('api', result['errors'])

    def test_manifest_source_validation_rejects_html_and_tampering_before_fallback(self):
        tampered = json.loads(json.dumps(self.envelope))
        tampered['payload']['notes'] = 'tampered metadata'
        attempts = []
        async def fetch(url, *args, **kwargs):
            if 'api.github.com' in url:
                return b'{}'
            if 'voice-manifest' in url:
                raise ValueError('not published')
            validate_body = kwargs.get('validator', lambda body: None)
            for name, body in [('html', b'<html>proxy error</html>'),
                               ('tampered', json.dumps(tampered).encode()),
                               ('valid', json.dumps(self.envelope).encode())]:
                try:
                    validate_body(body)
                except ValueError:
                    attempts.append('rejected ' + name)
                    continue
                attempts.append('accepted ' + name)
                return body
            raise ValueError('all metadata invalid')
        with patch('app.updates.client.fetch_small', fetch):
            result = asyncio.run(self.client._discover_release())
        self.assertIn('main', result['manifests'])
        self.assertEqual(attempts, ['rejected html', 'rejected tampered', 'accepted valid'])
