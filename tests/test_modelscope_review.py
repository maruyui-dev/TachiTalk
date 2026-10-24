"""Independent review regressions for user-selected and persisted voice routing."""
import asyncio
import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import AsyncMock, patch
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QApplication, QMainWindow

from app.ui.update_controls import UpdateControls
from app.updates.client import UpdateClient
from app.updates.download import Downloader, HTTPDownloadError
from app.updates.manifest import atomic_json, canonical
from tests.test_updates import bundle


class ReviewPanel(QMainWindow):
    closing = Signal()


class VoiceRoutingReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = UpdateClient(root=self.root, data=self.root / 'data')
        self.payload, self.archive = bundle(component='voice', base='*',
                                           name='services/gpt_sovits/api_v2.py')
        self.payload['parts'][0].update(
            name='voice-v2ProPlus-cu128-runtime-1.zip.part000',
            url='https://github.com/maruyui-dev/TachiTalk/releases/download/v1.3.0/'
                'voice-v2ProPlus-cu128-runtime-1.zip.part000')
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'review': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        self.envelope = {'key_id': 'review', 'payload': self.payload,
                         'signature': base64.b64encode(key.sign(canonical(self.payload))).decode()}
        self.cache = self.client.directory / 'downloads' / self.payload['archive']['sha256']

    def prepare_with(self, transfer, route='GitHub'):
        probe = AsyncMock(return_value={'source': route})
        with patch('app.updates.diagnostics.select_voice_source', probe), \
             patch.object(Downloader, '_transfer', transfer):
            result = asyncio.run(self.client.prepare(self.envelope, lambda value: None, Event()))
        return result, probe

    def transfer(self, attempted, *, fail_before=False, fail_after=False):
        archive = self.archive
        async def perform(downloader, artifact, partial, state, url, source):
            attempted.append(source['name'])
            if source['name'] == 'GitHub' and fail_before:
                raise HTTPDownloadError(403)
            if source['name'] == 'GitHub' and fail_after:
                partial.write_bytes(archive[:1])
                downloader.pin(source)
                raise HTTPDownloadError(403)
            partial.write_bytes(archive)
            downloader.pin(source)
        return perform

    def test_first_manual_source_choice_before_manifest_is_honored_without_probe(self):
        panel = ReviewPanel()
        ui = UpdateControls(panel, self.client)
        try:
            with patch('app.ui.update_controls.QInputDialog.getItem', return_value=('魔搭', True)):
                ui.select_source()
            attempted = []
            _, probe = self.prepare_with(self.transfer(attempted), route='GitHub')
            self.assertEqual(attempted, ['魔搭'])
            probe.assert_not_awaited()
        finally:
            ui.pause()
            ui.deleteLater()
            panel.close()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_cached_modelscope_source_remains_after_global_manual_choice_changes(self):
        config = self.client.configuration()
        config['preferred_download_source'] = 'GitHub'
        atomic_json(self.client.config_path, config)
        mirror = next(s for s in config['sources'] if s.get('layout') == 'modelscope')
        atomic_json(self.cache / 'source-lock.json', Downloader.source_identity(mirror))
        attempted = []
        _, probe = self.prepare_with(self.transfer(attempted))
        self.assertEqual(attempted, ['魔搭'])
        probe.assert_not_awaited()

    def test_manual_source_switch_after_restart_clears_previous_voice_cache(self):
        config = self.client.configuration()
        github = next(s for s in config['sources'] if not s.get('prefix'))
        atomic_json(self.cache / 'source-lock.json', Downloader.source_identity(github))
        (self.cache / '0000.bin.part').write_bytes(b'old-source-bytes')
        panel = ReviewPanel()
        ui = UpdateControls(panel, self.client)
        attempted, old_partial_present = [], []
        perform = self.transfer(attempted)
        async def transfer(downloader, artifact, partial, state, url, source):
            old_partial_present.append(partial.exists())
            await perform(downloader, artifact, partial, state, url, source)
        probe = AsyncMock(side_effect=AssertionError('Explicit manual choice needs no probe'))
        try:
            self.assertFalse(ui.envelopes)
            self.assertIsNone(ui.last_component)
            with patch('app.ui.update_controls.QInputDialog.getItem', return_value=('魔搭', True)):
                ui.select_source()
            with patch.object(self.client, 'voice_manifest', AsyncMock(return_value=self.envelope)), \
                 patch('app.updates.diagnostics.select_voice_source', probe), \
                 patch.object(Downloader, '_transfer', transfer), \
                 patch.object(ui, 'launch_updater') as launch:
                ui.install_voice(confirm=False)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(.001)
                    if not ui.busy and not (ui.thread and ui.thread.is_alive()):
                        break
                self.assertFalse(ui.busy, ui.state.text())
                launch.assert_called_once()
            self.assertEqual(attempted, ['魔搭'])
            self.assertEqual(old_partial_present, [False])
            probe.assert_not_awaited()
        finally:
            ui.pause()
            if ui.thread:
                ui.thread.join(timeout=3)
            ui.deleteLater()
            panel.close()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_github_failure_before_first_byte_can_fallback_to_modelscope(self):
        attempted = []
        self.prepare_with(self.transfer(attempted, fail_before=True))
        self.assertEqual(attempted, ['GitHub', '魔搭'])

    def test_github_failure_after_first_byte_keeps_source_and_cache(self):
        attempted = []
        with self.assertRaisesRegex(ValueError, '未自动切源'):
            self.prepare_with(self.transfer(attempted, fail_after=True))
        self.assertEqual(attempted, ['GitHub'])
        self.assertEqual((self.cache / '0000.bin.part').read_bytes(), self.archive[:1])
        self.assertEqual(self.client.configuration().get('restart_archives', []), [])


if __name__ == '__main__':
    unittest.main()
