"""Removed Cloudflare defaults and retained dormant discovery; no Internet traffic."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import subprocess
import sys
from unittest.mock import patch

from app.updates.client import UpdateClient
from app.updates.download import sources
from app.updates.manifest import atomic_json
from tests import test_update_discovery as discovery


class CloudflareDefaults(unittest.TestCase):
    def test_new_profile_has_github_modelscope_and_no_version_api_route(self):
        with TemporaryDirectory() as folder:
            client = UpdateClient(root=folder, data=folder)
            config = client.configuration()
            self.assertTrue(any(s['name'] == 'GitHub' and s.get('enabled') for s in config['sources']))
            self.assertTrue(any(s.get('layout') == 'modelscope' and s.get('enabled') for s in config['sources']))
            self.assertFalse(any(s.get('layout') == 'r2' for s in config['sources']))
            self.assertEqual(config['api_sources'], [])
            self.assertFalse(config.get('preferred_download_source'))

    def test_users_public_download_relays_remain_configurable(self):
        with TemporaryDirectory() as folder:
            client = UpdateClient(root=folder, data=folder)
            config = client.configuration()
            relay = {'name': 'GHFast custom', 'prefix': 'https://ghfast.top/',
                     'enabled': True, 'fallback_only': True, 'priority': 20}
            config['sources'].append(relay)
            atomic_json(client.config_path, config)
            migrated = UpdateClient(root=folder, data=folder).configuration()
            self.assertIn(relay, migrated['sources'])
            self.assertTrue(any(s['name'] == relay['name'] for s in sources(migrated)))

    def test_startup_does_not_restore_download_page_or_wait_for_network(self):
        script = '''
import asyncio, tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QStackedWidget
from app.ui import desktop, control_panel
from app.updates.client import UpdateClient
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
original_remember = desktop.remember_session
original_worker = desktop.VoiceWorker
async def idle(settings, ui):
    await asyncio.Event().wait()
async def slow_check(self, progress):
    await asyncio.sleep(4)
    return {'manifests': {}, 'errors': {}, 'main': {'state':'current','version':'1.3.0'}}
def restore(panel):
    original_remember(panel)
    panel.ensure_update_controls(show=True)
def worker(settings, ui, signals, audio=None):
    return original_worker(settings,ui,signals,audio=audio,application=idle)
class App(QApplication):
    def exec(self):
        def inspect():
            panel = next(w for w in self.topLevelWidgets() if hasattr(w,'session_controls'))
            page = panel.findChild(QStackedWidget,'pageStack').currentWidget().objectName()
            print('START_PAGE='+page,flush=True)
            panel.close()
        QTimer.singleShot(1500,inspect)
        QTimer.singleShot(5000,self.quit)
        return super().exec()
with patch.object(desktop,'QApplication',App), patch.object(desktop,'remember_session',restore), \
     patch.object(desktop,'VoiceWorker',worker), patch.object(UpdateClient,'check',slow_check), \
     patch('app.updates.main_feed.ENABLED', False):
    desktop.run_desktop(Settings(),ExpressionCatalog())
'''
        result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn('START_PAGE=characterPage', result.stdout)

    def test_existing_v2_preference_is_migrated_once_without_losing_custom_sources(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            client = UpdateClient(root=root, data=root)
            config = client.configuration()
            config['config_version'] = 2
            config['preferred_download_source'] = 'GHFast'
            for kind in ('sources', 'manifest_sources', 'api_sources'):
                config[kind] = [s for s in config[kind] if 'jieyiblog.me' not in s.get('prefix', '')]
            config['sources'].append({'name': 'My mirror', 'prefix': 'https://example.com/', 'enabled': False})
            config['restart_archives'] = ['a' * 64]
            atomic_json(client.config_path, config)
            migrated = UpdateClient(root=root, data=root).configuration()
            self.assertGreaterEqual(migrated['config_version'], 5)
            self.assertFalse(migrated.get('preferred_download_source'))
            for kind in ('sources', 'manifest_sources', 'api_sources'):
                self.assertFalse(any(s.get('layout') == 'r2' or 'jieyiblog.me' in s.get('prefix', '')
                                     for s in migrated[kind]), migrated[kind])
            self.assertIn(config['sources'][-1], migrated['sources'])
            self.assertEqual(migrated['restart_archives'], ['a' * 64])
            migrated['preferred_download_source'] = 'GitHub'
            atomic_json(client.config_path, migrated)
            self.assertEqual(UpdateClient(root=root, data=root).configuration()['preferred_download_source'], 'GitHub')

    def test_cloudflare_only_legacy_metadata_has_no_usable_source(self):
        config = {'api_sources': [{'name': 'Cloudflare 版本信息', 'layout': 'r2',
                                  'prefix': 'https://download.jieyiblog.me/', 'enabled': True}]}
        self.assertEqual(sources(config, 'api_sources'), [])

    def test_source_profile_does_not_load_developer_portrait_mapping(self):
        from app.ui import control_panel
        from app.paths import DATA_ROOT
        self.assertEqual(control_panel.RESOURCE_STATE, DATA_ROOT / 'resources/resource_library.json')


class CloudflareDiscovery(discovery.DiscoveryTests):
    def test_invalid_release_notes_fall_back_instead_of_crashing_popup(self):
        result = self.check({'tag_name':'v1.3.1','body':['bad'],'assets':[]},self.main)
        self.assertIn('api', result['errors'])
        self.assertIn('main', result['manifests'])

    def test_retained_discovery_uses_github_without_cloudflare(self):
        async def fetch(url, configured, **kwargs):
            self.assertFalse(any(s.get('layout') == 'r2' for s in configured))
            self.assertEqual(configured[0]['prefix'], '')
            value = {'tag_name': 'v1.3.0', 'assets': []} if 'api.github.com' in url else self.voice
            body = json.dumps(value).encode()
            kwargs['validator'](body)
            return body
        with patch('app.updates.client.fetch_small', fetch):
            result = asyncio.run(self.client._discover_release())
        self.assertEqual(result['main']['state'], 'current')
        self.assertIn('voice', result['manifests'])

    def test_full_main_installer_is_offered_without_a_patch(self):
        result = self.check({'tag_name': 'v1.3.1', 'name': '改进下载', 'body': '更新说明',
            'assets': [{'name': 'TachiTalk-v1.3.1-main.zip', 'size': 100,
                'browser_download_url': 'https://github.com/maruyui-dev/TachiTalk/releases/download/v1.3.1/TachiTalk-v1.3.1-main.zip'}]})
        self.assertEqual(result['main']['state'], 'no_patch')
        self.assertEqual(result['main'].get('installer', {}).get('size'), 100)
        self.assertEqual(result['main'].get('installer', {}).get('url'),
            'https://github.com/maruyui-dev/TachiTalk/releases/download/v1.3.1/TachiTalk-v1.3.1-main.zip')

    def test_release_metadata_cannot_supply_arbitrary_installer_url(self):
        result = self.check({'tag_name': 'v1.3.1', 'assets': [{'name': 'TachiTalk-v1.3.1-main.zip',
            'size': 100, 'browser_download_url': 'https://untrusted.invalid/evil.exe'}]})
        self.assertNotIn('installer', result['main'])


