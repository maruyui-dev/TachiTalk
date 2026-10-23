import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer, Signal, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QDialog, QMessageBox, QPlainTextEdit
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.ui.update_controls import UpdateControls, UpdatePrompt
from app.updates.client import UpdateClient
from app.updates.download import Downloader, Policy
from app.updates.manifest import canonical, atomic_json
from app.paths import voice_location
from tests.test_updates import bundle


class Panel(QMainWindow):
    closing = Signal()


class UpdateUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = Panel()
        self.addCleanup(self.panel.close)
        self.client = UpdateClient(root=self.root, data=self.root / 'data')
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        self.payload, _ = bundle(base='1.3.0')
        self.payload['version'] = '1.3.1'
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
        while self.ui.thread and self.ui.thread.is_alive() and time.monotonic() < deadline:
            QTest.qWait(10)
        QTest.qWait(50)
        self.assertFalse(self.ui.thread.is_alive())

    def test_update_prompt_includes_metadata_and_later_keeps_panel_alive(self):
        self.panel.show()
        prompt = UpdatePrompt(self.payload, self.panel)
        prompt.show()
        self.assertIn('1.3.0', prompt.details.text())
        self.assertIn('1.3.1', prompt.details.text())
        self.assertIn('2026-10-22', prompt.details.text())
        self.assertEqual(prompt.findChild(QPlainTextEdit).toPlainText(), self.payload['notes'])
        prompt.reject()
        self.assertEqual(prompt.result(), QDialog.DialogCode.Rejected)
        self.assertTrue(self.panel.isVisible())
        prompt.deleteLater()

    def test_check_and_download_workers_keep_qt_heartbeat_running(self):
        calls, beats = [], []
        async def check(progress):
            calls.append(threading.get_ident())
            await asyncio.sleep(.18)
            return {'manifests': {'main': self.envelope}, 'errors': {}}
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: beats.append(1))
        timer.start()
        with patch.object(self.client, 'check', check):
            self.ui.check()
            self.wait_idle()
        timer.stop()
        self.assertNotEqual(calls[0], threading.get_ident())
        self.assertGreater(len(beats), 4)
        self.assertTrue(self.ui.prompt.isVisible())
        self.ui.prompt.reject()

        payload, _ = bundle(component='voice', name='services/gpt_sovits/api_v2.py')
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        envelope = {'key_id': 'test', 'payload': payload,
                    'signature': base64.b64encode(key.sign(canonical(payload))).decode()}
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
        async def fail(progress):
            raise ValueError('all sources unavailable')
        with patch.object(self.client, 'check', fail):
            self.ui.check()
            self.wait_idle()
        self.assertIn('all sources unavailable', self.ui.state.text())
        self.assertTrue(self.ui.check_button.isEnabled())
        self.assertTrue(self.ui.config.isEnabled())
        self.assertTrue(self.panel.isVisible())

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
            self.assertIn('1.3.1', question.call_args.args[2])
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
        with patch('app.updates.client.Downloader', local_downloader), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(self.ui, 'launch_updater') as launch:
            self.ui.install_button.click()
            self.wait_idle()
            launch.assert_called_once()
            prepared = launch.call_args.args[0]
            self.assertEqual(prepared['archive'].read_bytes(), archive)
        self.assertEqual(calls, ['/asset'])
        self.assertEqual(self.ui.progress_bar.value(), 1000)

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
            result = asyncio.run(self.client.check())
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
            result = asyncio.run(self.client.check())
        self.assertIn('main', result['manifests'])
        self.assertEqual(attempts, ['rejected html', 'rejected tampered', 'accepted valid'])
