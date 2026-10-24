"""The enabled main feed refreshes panel state silently and leaves voice independent."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
import subprocess
import sys
from unittest.mock import AsyncMock, patch

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget

from app.ui.update_controls import UpdateControls
from app.updates.client import UpdateClient
from app.updates import main_feed
from tests.test_updates import bundle


class Panel(QMainWindow):
    closing = Signal()


def result(state='update_available', version='99.0.0'):
    return {'manifests': {}, 'errors': {}, 'main': {'state': state, 'version': version,
            'title': '测试版本提示', 'notes': '只更新状态', 'published_at': '2026-10-24', 'source': '魔搭社区'}}


class MainFeedUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        gate = patch.object(main_feed, 'ENABLED', True)
        gate.start()
        self.addCleanup(gate.stop)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.client = UpdateClient(root=root, data=root / 'data')
        self.panel = Panel()
        self.stack = QStackedWidget()
        self.stack.addWidget(QWidget())
        self.stack.addWidget(QWidget())
        self.panel.setCentralWidget(self.stack)
        self.ui = UpdateControls(self.panel, self.client)
        self.addCleanup(self.cleanup_ui)

    def cleanup_ui(self):
        self.ui.shutdown()
        if self.ui.thread:
            self.ui.thread.join(timeout=3)
        main_thread = getattr(self.ui, 'main_thread', None)
        if main_thread:
            main_thread.join(timeout=3)
        QApplication.processEvents()
        self.ui.deleteLater()
        self.panel.close()
        self.panel.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wait_idle(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(.001)
            main_thread = getattr(self.ui, 'main_thread', None)
            if (not self.ui.busy and not (self.ui.thread and self.ui.thread.is_alive())
                    and not getattr(self.ui, 'main_check_running', False)
                    and not (main_thread and main_thread.is_alive())):
                return
        self.fail('Main-feed worker did not finish within the test deadline')

    def test_enabled_automatic_check_runs_on_worker_without_popup_navigation_or_legacy_api(self):
        calls, beats = [], []

        async def metadata(progress=lambda value: None):
            calls.append(threading.get_ident())
            await asyncio.sleep(.15)
            return result()

        self.panel.show()
        self.stack.setCurrentIndex(0)
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: beats.append(1))
        timer.start()
        try:
            with patch.object(main_feed, 'check', metadata), \
                 patch.object(self.client, '_discover_release', new=AsyncMock(side_effect=AssertionError('No legacy API'))), \
                 patch.object(self.ui, 'begin_download') as download, \
                 patch.object(self.ui, 'launch_updater') as updater, \
                 patch('app.updates.client.fetch_small', new=AsyncMock(side_effect=AssertionError('No voice HTTP'))):
                self.ui.check(automatic=True)
                self.assertTrue(self.ui.install_button.isEnabled())
                self.assertTrue(self.ui.import_button.isEnabled())
                self.assertTrue(self.ui.legacy_button.isEnabled())
                self.wait_idle()
                download.assert_not_called()
                updater.assert_not_called()
        finally:
            timer.stop()
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0], threading.get_ident())
        self.assertGreater(len(beats), 4)
        self.assertIsNone(self.ui.prompt)
        self.assertEqual(self.stack.currentIndex(), 0)
        self.assertTrue(self.panel.isVisible())
        self.assertIn('99.0.0', self.ui.main_status.text() + self.ui.main_detail.text())
        self.assertIn('魔搭社区', self.ui.main_status.text() + self.ui.main_detail.text())

    def test_main_check_result_updates_only_panel_metadata_and_preserves_voice_state(self):
        payload, _ = bundle(component='voice', name='services/gpt_sovits/api_v2.py', base='*')
        voice = {'payload': payload}
        self.ui.envelopes['voice'] = voice
        self.ui.check_errors['voice'] = 'retained voice message'
        with patch.object(self.client, 'voice_manifest', new=AsyncMock(side_effect=AssertionError('No voice refresh'))), \
             patch.object(self.ui, 'begin_download') as download, patch.object(self.ui, 'launch_updater') as updater:
            self.ui.on_finished('main-check', {'value': result()})
            download.assert_not_called()
            updater.assert_not_called()
        self.assertEqual(self.ui.main_result['state'], 'update_available')
        self.assertEqual(self.ui.main_result['source'], '魔搭社区')
        self.assertIs(self.ui.envelopes['voice'], voice)
        self.assertEqual(self.ui.check_errors['voice'], 'retained voice message')
        self.assertFalse(self.ui.update_button.isEnabled(), 'Unsigned metadata cannot enable executable patching')
        self.assertIsNone(self.ui.prompt)

    def test_long_main_notes_wrap_without_vertical_clipping(self):
        self.panel.setCentralWidget(self.ui)
        self.panel.resize(1100,920)
        self.panel.show()
        metadata = result()
        metadata['main']['notes'] = '\n'.join(['长版本说明需要自动换行并完整显示。'*9]*3)
        self.ui.on_finished('main-check', {'value':metadata})
        QApplication.processEvents()
        detail=self.ui.main_detail
        self.assertGreaterEqual(detail.height(),detail.heightForWidth(detail.width()))
        self.assertEqual(self.ui.horizontalScrollBar().maximum(),0)

    def test_disabled_entry_stays_closed_and_never_dispatches(self):
        check = AsyncMock(side_effect=AssertionError('Disabled entry cannot request metadata'))
        with patch.object(main_feed, 'ENABLED', False), patch.object(self.client, 'check', check):
            self.ui.check(automatic=True)
            self.ui.check(automatic=False)
            self.wait_idle()
        check.assert_not_awaited()
        self.assertIn('暂未开放', self.ui.main_status.text())
        self.assertTrue(self.ui.check_button.isHidden() or not self.ui.check_button.isEnabled())
        self.assertIsNone(self.ui.prompt)

    def test_feed_failure_is_a_panel_error_without_popup_or_voice_side_effect(self):
        failure = {'manifests': {}, 'errors': {'main': 'ModelScope unavailable'},
                   'main': {'state': 'error', 'version': None, 'source': '魔搭社区'}}
        with patch.object(self.ui, 'begin_download') as download, patch.object(self.ui, 'launch_updater') as updater:
            self.ui.on_finished('main-check', {'value': failure})
            download.assert_not_called()
            updater.assert_not_called()
        self.assertEqual(self.ui.main_result['state'], 'error')
        self.assertIn('ModelScope unavailable', self.ui.main_detail.text() + self.ui.state.text())
        self.assertIsNone(self.ui.prompt)
        self.assertTrue(self.ui.install_button.isEnabled())

    def test_main_result_cannot_release_or_overwrite_an_active_voice_download(self):
        self.ui.operation = 'prepare'
        self.ui.last_component = 'voice'
        self.ui.set_busy(True)
        self.ui.state.setText('语音分卷正在下载')
        self.ui.progress_bar.setValue(320)
        stop = self.ui.stop
        with patch.object(self.ui, 'begin_download') as download, patch.object(self.ui, 'launch_updater') as updater:
            self.ui.on_finished('main-check', {'value': result()})
            download.assert_not_called()
            updater.assert_not_called()
        self.assertTrue(self.ui.busy, 'Finishing main metadata must not release the voice worker gate')
        self.assertEqual(self.ui.operation, 'prepare')
        self.assertEqual(self.ui.last_component, 'voice')
        self.assertEqual(self.ui.state.text(), '语音分卷正在下载')
        self.assertEqual(self.ui.progress_bar.value(), 320)
        self.assertIs(self.ui.stop, stop)
        self.assertFalse(self.ui.install_button.isEnabled())

    def test_enabled_startup_checks_in_background_without_changing_the_restored_page(self):
        script = r'''
import asyncio, tempfile, threading
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QStackedWidget
from app.ui import desktop, control_panel
from app.updates.client import UpdateClient
from app.updates import main_feed
from app.ui.pet.expressions import ExpressionCatalog
from config import Settings
folder = tempfile.TemporaryDirectory()
root = Path(folder.name)
for module in (desktop, control_panel):
    module.RESOURCE_STATE = root / 'resources/library.json'
    module.RESOURCE_DIRECTORY = root / 'assets'
    module.RESOURCE_BUBBLE_DIRECTORY = root / 'bubbles'
control_panel.DATA_ROOT = root
desktop.DATA_ROOT = root
original_worker = desktop.VoiceWorker
checks = []
async def idle(settings, ui):
    await asyncio.Event().wait()
async def check(self, progress=lambda value: None):
    checks.append(threading.get_ident())
    return {'manifests': {}, 'errors': {}, 'main': {'state':'update_available','version':'99.0.0',
        'title':'isolated fixture','notes':'','published_at':'2026-10-24','source':'魔搭社区'}}
def worker(settings, ui, signals, audio=None):
    return original_worker(settings,ui,signals,audio=audio,application=idle)
class App(QApplication):
    def exec(self):
        def inspect():
            panel = next(w for w in self.topLevelWidgets() if hasattr(w,'session_controls'))
            page = panel.findChild(QStackedWidget,'pageStack').currentWidget().objectName()
            print('START_PAGE='+page,flush=True)
            print('CHECK_COUNT='+str(len(checks)),flush=True)
            print('CHECK_WORKER='+str(bool(checks and checks[0] != threading.get_ident())),flush=True)
            controls = panel.update_controls
            print('NO_PROMPT='+str(controls.prompt is None),flush=True)
            print('VOICE_AVAILABLE='+str(controls.install_button.isEnabled()),flush=True)
            panel.close()
        QTimer.singleShot(2100,inspect)
        QTimer.singleShot(6000,self.quit)
        return super().exec()
with patch.object(desktop,'QApplication',App), patch.object(desktop,'VoiceWorker',worker), \
     patch.object(UpdateClient,'check',check), patch.object(main_feed,'ENABLED',True), \
     patch('app.ui.update_controls.UpdateClient',side_effect=lambda:UpdateClient(root=root,data=root)):
    desktop.run_desktop(Settings(),ExpressionCatalog())
'''
        completed = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr[-2500:])
        for marker in ('START_PAGE=characterPage', 'CHECK_COUNT=1', 'CHECK_WORKER=True',
                       'NO_PROMPT=True', 'VOICE_AVAILABLE=True'):
            self.assertIn(marker, completed.stdout)


if __name__ == '__main__':
    unittest.main()
