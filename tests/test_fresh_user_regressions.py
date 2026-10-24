"""Fresh-profile desktop startup/restart regressions; no models, devices, or network.

Each probe runs the real desktop construction/normal-close path in a separate
Python process. Only the voice-component availability boundary and worker start
are replaced; Qt, resource persistence, session validation, and DPAPI are real.
"""
import json
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
RESULT_PREFIX = 'FRESH_USER_RESULT='


def desktop_probe(root, action, *, frozen_paths=False, result_file=None):
    """Child-process entry point; all writable paths belong to the fixture."""
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                                  QLabel, QLineEdit, QSlider, QPushButton)
    from app.ui import control_panel, desktop
    from app.ui.pet.expressions import ExpressionCatalog
    from app.updates import main_feed
    from config import Settings

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ('assets', 'bubbles'):
        (root / name).mkdir(exist_ok=True)
    values = {}
    component_status = {'installed': action not in ('missing', 'disable-missing', 'install-live',
                                                   'install-busy', 'install-save-failure'),
                        'version': 'fixture', 'missing': []}
    panels = []
    original_load = desktop.load_window

    def load(*args, **kwargs):
        panel = original_load(*args, **kwargs)
        panels.append(panel)
        return panel

    def start_without_services(worker):
        # No background event loop means no ASR/model/device/network activity.
        worker.thread = SimpleNamespace(join=lambda **_: None,
                                        is_alive=lambda: False)

    def event_loop():
        panel = panels[0]
        app = QApplication.instance()
        session = panel.session_controls
        if action in ('change', 'export'):
            panel.findChild(QLineEdit, 'userNameEdit').setText('独立进程测试称呼')
            panel.findChild(QSlider, 'scaleSlider').setValue(137)
            panel.findChild(QSlider, 'inputVolumeSlider').setValue(31)
            panel.findChild(QSlider, 'outputVolumeSlider').setValue(43)
            panel.findChild(QCheckBox, 'recordingEnabledCheck').setChecked(False)
            panel.findChild(QLineEdit, 'apiKeyEdit').setText('fixture-ai-not-a-secret')
            panel.findChild(QComboBox, 'llmModelCombo').setCurrentText('fixture-model')
            panel.ai_controls.save()
            output = panel.findChild(QComboBox, 'speakerCombo')
            output.addItem('fixture output', 9)
            output.setCurrentIndex(output.findData(9))
            for expression in ('平常', '开心'):
                combo = panel.resource_controls.mapping[expression]
                combo.setCurrentIndex(combo.findData('builtin:portrait:欣慰'))
        if action in ('disable', 'disable-missing', 'install-live', 'install-busy', 'install-save-failure'):
            panel.findChild(QCheckBox, 'autoReadCheck').setChecked(False)
        if action == 'install-live':
            component_status['installed'] = True
            controller = getattr(panel, 'voice_install_controls', None)
            if controller is not None:
                controller.refresh()
            values['tts_service_ready_after_detection'] = panel.voice_controls.inputs.service_ready('TTS')
        if action in ('install-busy', 'install-save-failure'):
            component_status['installed'] = True
            controller = panel.voice_install_controls
            if action == 'install-busy':
                installation = root / 'busy-install'
                installation.mkdir()
                controller.service_root = installation / 'services/gpt_sovits'
                (installation / '.tachitalk-pending.json').write_text('{"state":"applying"}', encoding='utf-8')
                controller.refresh()
            else:
                with patch.object(panel.session_controls, 'save', return_value=False):
                    controller.refresh()
            values['activation_state'] = json.loads(controller.record.read_text(encoding='utf-8'))
        if action in ('reset-resources', 'reset-resources-export'):
            panel.findChild(QPushButton, 'navAssets').click()
            panel.findChild(QPushButton, 'resetButton').click()
            values['reset_feedback'] = panel.findChild(QLabel, 'footerHint').text()
            values['mapping_on_disk_after_reset'] = json.loads(
                panel.resource_controls.library.original.state_file.read_text(encoding='utf-8'))['mapping']
            if action == 'reset-resources-export':
                values['export_saved'] = panel.settings_controls.save_to(root / 'after-reset.json')
        if action == 'export':
            values['export_saved'] = panel.settings_controls.save_to(root / 'explicit.json')
        if action == 'write-failure':
            with patch.object(session.file, 'write', side_effect=PermissionError('fixture denied')):
                values['save_result'] = session.save()
                values['save_feedback'] = panel.findChild(QLabel, 'footerHint').text()

        controls = panel.resource_controls
        values.update(loaded=session.loaded, mapping=dict(controls.library.state['mapping']),
                      dropdown={name: combo.currentData() for name, combo in controls.mapping.items()},
                      pages=panel.settings_controls.values.capture(),
                      tts_auto_read=panel.voice_controls.voices.snapshot().tts.auto_read,
                      profile_auto_read=panel.settings_controls.snapshot()['profiles']['tts']['gpt_sovits']['auto_read'])
        rendered = {}
        pet = panel.character_controls.pet
        for expression in ('平常', '开心'):
            pet.preview_expression(expression)
            deadline = monotonic() + 2
            while monotonic() < deadline:
                app.processEvents()
                if not pet.character._switching:
                    break
                QTest.qWait(10)
            expected = controls.library.catalog().paths[expression]
            current = pet.character._current_pixmap.toImage()
            expected_image = QImage(str(expected)).convertToFormat(current.format())
            rendered[expression] = {'filename': expected.name,
                                    'expression': pet.character.current_expression,
                                    'image_matches_catalog': current == expected_image,
                                    'transition_finished': not pet.character._switching}
        values['rendered'] = rendered
        if frozen_paths:
            from PySide6.QtWidgets import QStyle, QStyleOptionButton
            values.update(frozen=control_panel.FROZEN, data_root=str(control_panel.DATA_ROOT),
                          resource_state=str(control_panel.RESOURCE_STATE),
                          session_path=str(session.file.path), dpr=panel.devicePixelRatioF())
            check = panel.findChild(QCheckBox, 'recordingEnabledCheck')
            old = check.isChecked(), check.isEnabled()
            values['indicator'] = []
            for enabled in (True, False):
                for checked in (False, True):
                    check.setEnabled(enabled)
                    check.setChecked(checked)
                    app.processEvents()
                    option = QStyleOptionButton()
                    check.initStyleOption(option)
                    rect = check.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, check)
                    image = check.grab().toImage()
                    dpr = image.devicePixelRatio()
                    crop = image.copy(round(rect.x()*dpr), round(rect.y()*dpr),
                                      round(rect.width()*dpr), round(rect.height()*dpr))
                    ink = sum(crop.pixelColor(x, y).alpha() > 0 and crop.pixelColor(x, y).lightness() < 230
                              for x in range(crop.width()) for y in range(crop.height()))
                    values['indicator'].append({'enabled': enabled, 'checked': checked, 'ink': ink})
                    crop.save(str(root / f'{action}-indicator-{enabled}-{checked}.png'))
            check.setChecked(old[0])
            check.setEnabled(old[1])
            panel.grab().save(str(root / f'{action}-panel.png'))
            # Exercise the real frozen scroll area; only the HTTP boundary is a fixture.
            import asyncio
            import time
            updates = panel.ensure_update_controls(show=True)
            async def diagnose(*args, **kwargs):
                await asyncio.sleep(.1)
                probe = {'state': 'ok', 'latency_ms': 300, 'detail': 'HTTP 206 fixture'}
                return {'state': 'ok', 'manifest': probe, 'artifact': probe,
                        'modelscope': {'manifest': probe, 'artifact': probe},
                        'proxy': {'state': 'not_found', 'summary': '未发现代理'}, 'manifest_error': ''}
            updates.client.diagnose = diagnose
            app.processEvents()
            bar = updates.verticalScrollBar()
            bar.setValue(0)
            QTest.mouseClick(updates.network_check_button, Qt.MouseButton.LeftButton)
            app.processEvents()
            values['scroll_start'] = bar.value()
            deadline = time.monotonic() + 3
            while updates.busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.005)
            app.processEvents()
            values['scroll_finished'] = bar.value()
            values['network_fixture_finished'] = not updates.busy
            panel.grab().save(str(root / f'{action}-network.png'))
        panel.close()  # Real closing signal and real encrypted session write.
        values['session_exists'] = session.file.path.is_file()
        QCoreApplication.processEvents()
        return 0

    data = root / 'runtime'
    with ExitStack() as changes:
        if not frozen_paths:
            for module in (control_panel, desktop):
                for name, value in (('DATA_ROOT', data), ('RESOURCE_STATE', root / 'library.json'),
                                    ('RESOURCE_DIRECTORY', root / 'assets'),
                                    ('RESOURCE_BUBBLE_DIRECTORY', root / 'bubbles')):
                    changes.enter_context(patch.object(module, name, value))
            changes.enter_context(patch.object(desktop, 'FROZEN', False))
        for change in (patch.object(desktop, 'load_window', side_effect=load),
                       patch.object(desktop.VoiceWorker, 'start', start_without_services),
                       patch.object(QApplication, 'exec', side_effect=event_loop),
                       patch.object(main_feed, 'ENABLED', False),
                       patch('app.core.components.voice_status', side_effect=lambda *args: dict(component_status))):
            changes.enter_context(change)
        desktop.run_desktop(Settings(), ExpressionCatalog())
    if result_file is not None:
        Path(result_file).write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        print(RESULT_PREFIX + json.dumps(values, ensure_ascii=True))


class FreshUserProcessRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='tachitalk-fresh-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def probe(self, action):
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8',
                   LOCALAPPDATA=str(self.root / 'local-app-data'),
                   APPDATA=str(self.root / 'roaming-app-data'))
        command = [sys.executable, '-B', '-c',
                   'from tests.test_fresh_user_regressions import desktop_probe; '
                   'import sys; desktop_probe(sys.argv[1], sys.argv[2])',
                   str(self.root), action]
        completed = subprocess.run(command, cwd=PROJECT, env=env, capture_output=True,
                                   text=True, encoding='utf-8', timeout=45)
        self.assertEqual(completed.returncode, 0, completed.stderr[-5000:] + completed.stdout[-2000:])
        lines = [line[len(RESULT_PREFIX):] for line in completed.stdout.splitlines()
                 if line.startswith(RESULT_PREFIX)]
        self.assertEqual(len(lines), 1, completed.stdout[-2000:])
        return json.loads(lines[0])

    def test_fresh_defaults_and_actual_portraits_survive_independent_restart(self):
        first = self.probe('inspect')
        second = self.probe('inspect')
        self.assertFalse(first['loaded'])
        self.assertTrue(first['session_exists'])
        self.assertTrue(second['loaded'])
        for result in (first, second):
            self.assertEqual(result['mapping'], {})
            self.assertTrue(result['dropdown'])
            self.assertTrue(all(key is None for key in result['dropdown'].values()))
            for name in ('平常', '开心'):
                self.assertEqual(result['rendered'][name], {
                    'filename': name + '.png', 'expression': name,
                    'image_matches_catalog': True, 'transition_finished': True})

    def assert_saved_values(self, result):
        self.assertTrue(result['loaded'])
        pages = result['pages']
        self.assertEqual(pages['dialoguePage']['userNameEdit'], '独立进程测试称呼')
        self.assertEqual(pages['characterPage']['scaleSlider'], 137)
        self.assertFalse(pages['characterPage']['recordingEnabledCheck'])
        self.assertEqual(pages['audioPage']['inputVolumeSlider'], 31)
        self.assertEqual(pages['audioPage']['outputVolumeSlider'], 43)
        self.assertEqual(pages['audioPage']['speakerCombo'], 9)
        self.assertEqual(pages['aiPage']['llmModelCombo'], 'fixture-model')
        self.assertEqual(pages['aiPage']['apiKeyEdit'], 'fixture-ai-not-a-secret')
        self.assertEqual(result['mapping'], {'平常': 'builtin:portrait:欣慰', '开心': 'builtin:portrait:欣慰'})
        for name in ('平常', '开心'):
            self.assertEqual(result['dropdown'][name], 'builtin:portrait:欣慰')
            self.assertEqual(result['rendered'][name]['filename'], '欣慰.png')
            self.assertTrue(result['rendered'][name]['image_matches_catalog'])

    def test_normal_close_restores_ui_devices_ai_and_user_mappings_in_new_process(self):
        self.assertTrue(self.probe('change')['session_exists'])
        self.assert_saved_values(self.probe('inspect'))

    def assert_resource_reset_survives_restart(self, action):
        self.probe('change')
        reset = self.probe(action)
        self.assertEqual(reset['mapping'], {})
        self.assertTrue(all(value is None for value in reset['dropdown'].values()))
        self.assertEqual(reset['mapping_on_disk_after_reset'], {}, 'Reset must persist before reporting success')
        restarted = self.probe('inspect')
        self.assertTrue(restarted['loaded'])
        self.assertEqual(restarted['mapping'], {}, 'Resource reset must replace the old on-disk mappings')
        self.assertTrue(all(value is None for value in restarted['dropdown'].values()))
        self.assertEqual(restarted['pages']['dialoguePage']['userNameEdit'], '独立进程测试称呼')
        for name in ('平常', '开心'):
            self.assertEqual(restarted['rendered'][name]['filename'], name + '.png')
            self.assertTrue(restarted['rendered'][name]['image_matches_catalog'])

    def test_resource_page_reset_survives_normal_close_and_independent_restart(self):
        self.assert_resource_reset_survives_restart('reset-resources')

    def test_resource_page_reset_survives_explicit_save_and_independent_restart(self):
        self.assert_resource_reset_survives_restart('reset-resources-export')

    def test_explicit_save_then_close_restores_in_new_process(self):
        saved = self.probe('export')
        self.assertTrue(saved['export_saved'])
        self.assertTrue((self.root / 'explicit.json').is_file())
        self.assert_saved_values(self.probe('inspect'))

    def test_missing_component_does_not_persist_text_fallback_as_user_preference(self):
        missing = self.probe('missing')
        self.assertFalse(missing['tts_auto_read'], 'Missing local runtime must still degrade safely to text')
        self.assertTrue(missing['pages']['audioPage']['autoReadCheck'],
                        'Temporary runtime absence must not clear the user auto-read checkbox')
        self.assertTrue(missing['profile_auto_read'],
                        'Temporary runtime absence must not be exported as a disabled user preference')
        installed = self.probe('inspect')
        self.assertTrue(installed['loaded'])
        self.assertTrue(installed['tts_auto_read'],
                        'After installing voice and restarting, dialogue must request TTS without opening preview')

    def test_user_explicitly_disabled_speech_stays_disabled_after_restart(self):
        self.probe('disable')
        restarted = self.probe('inspect')
        self.assertTrue(restarted['loaded'])
        self.assertFalse(restarted['pages']['audioPage']['autoReadCheck'])
        self.assertFalse(restarted['tts_auto_read'])

    def test_newly_installed_voice_enables_replies_once_after_independent_restart(self):
        missing = self.probe('disable-missing')
        self.assertFalse(missing['pages']['audioPage']['autoReadCheck'])
        installed = self.probe('inspect')
        self.assertTrue(installed['pages']['audioPage']['autoReadCheck'])
        self.assertTrue(installed['tts_auto_read'])
        self.probe('disable')
        self.assertFalse(self.probe('inspect')['pages']['audioPage']['autoReadCheck'])

    def test_running_program_detects_voice_without_faking_model_readiness(self):
        result = self.probe('install-live')
        self.assertTrue(result['pages']['audioPage']['autoReadCheck'])
        self.assertTrue(result['tts_auto_read'])
        self.assertFalse(result['tts_service_ready_after_detection'])

    def test_live_install_transaction_does_not_enable_or_consume_activation(self):
        result = self.probe('install-busy')
        self.assertFalse(result['pages']['audioPage']['autoReadCheck'])
        self.assertFalse(result['activation_state']['installed'])

    def test_failed_preference_save_does_not_consume_install_activation(self):
        result = self.probe('install-save-failure')
        self.assertTrue(result['pages']['audioPage']['autoReadCheck'])
        self.assertFalse(result['activation_state']['installed'])

    def test_session_write_error_reports_failure(self):
        result = self.probe('write-failure')
        self.assertFalse(result['save_result'])
        self.assertIn('自动保存失败', result['save_feedback'])
        self.assertIn('PermissionError', result['save_feedback'])


if __name__ == '__main__':
    unittest.main()
