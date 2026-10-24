"""Offline regressions for first-run diagnostics and signed in-app main updates."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.updates import main_feed
from app.updates.client import UpdateClient
from app.updates.manifest import canonical
from app.version import VERSION
from tests.test_updates import bundle


class MainUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = UpdateClient(root=self.root, data=self.root / 'data')
        self.key = Ed25519PrivateKey.generate()
        self.client.keys = {'fixture': base64.b64encode(self.key.public_key().public_bytes_raw()).decode()}

    def signed(self, component='main'):
        payload, archive = bundle(component=component, base=VERSION if component == 'main' else '*',
            name='TachiTalk.exe' if component == 'main' else 'services/gpt_sovits/api_v2.py')
        if component == 'main':
            payload['version'] = '2.0.1'
        return {'key_id': 'fixture', 'payload': payload,
            'signature': base64.b64encode(self.key.sign(canonical(payload))).decode()}, archive

    async def test_first_run_diagnostics_obtains_verified_manifest_before_probing_parts(self):
        envelope, _ = self.signed('voice')
        manifest = AsyncMock(return_value=envelope)
        probe = AsyncMock(return_value={'state': 'ok', 'latency_ms': 3})
        with patch.object(self.client, 'voice_manifest', manifest), \
             patch('app.updates.diagnostics.probe_url', probe):
            result = await self.client.diagnose()
        manifest.assert_awaited_once()
        self.assertEqual(result['modelscope']['artifact']['state'], 'ok')
        self.assertTrue(any(c.kwargs['kind'] == 'artifact' for c in probe.await_args_list))

    async def test_missing_modelscope_feed_falls_back_to_official_release_metadata_only(self):
        release = {'tag_name': 'v2.0.1', 'draft': False, 'prerelease': False,
            'name': '正式版', 'body': '新版说明', 'published_at': '2026-10-24T12:00:00Z'}
        async def fetch(url, configured, **kwargs):
            if url.startswith('https://modelscope.cn/'):
                raise ValueError('HTTP 404')
            self.assertEqual(url, 'https://api.github.com/repos/maruyui-dev/TachiTalk/releases/latest')
            body = json.dumps(release).encode()
            kwargs['validator'](body)
            return body
        with patch('app.updates.main_feed.fetch_small', fetch):
            result = await main_feed.check()
        self.assertEqual(result['main']['state'], 'update_available')
        self.assertEqual(result['main']['source'], 'GitHub')
        self.assertEqual(result['manifests'], {})
        self.assertNotIn('archive', result['main'])

    async def test_known_delivery_filename_is_accepted_only_as_metadata_alias(self):
        from app.updates.download import Policy
        from app.updates.modelscope import ENTRY
        alias = ENTRY + f'TachiTalk-v{VERSION}-main-latest.json'
        metadata = {'schema': 1, 'component': 'main', 'channel': 'stable', 'version': VERSION,
            'title': '正式版', 'notes': '', 'published_at': '2026-10-24'}
        async def fetch(url, configured, **kwargs):
            if url == main_feed.URL:
                raise ValueError('HTTP 404')
            self.assertEqual(url, alias)
            Policy().redirect(url, url)
            body = json.dumps(metadata).encode()
            kwargs['validator'](body)
            return body
        with patch('app.updates.main_feed.fetch_small', fetch):
            result = await main_feed.check()
        self.assertEqual(result['main']['source'], '魔搭社区')
        self.assertEqual(result['main']['state'], 'current')
        self.assertEqual(result['errors'], {})
        self.assertEqual(result['manifests'], {})

    async def test_selected_main_channel_fetches_signed_version_pinned_manifest(self):
        envelope, _ = self.signed()
        async def fetch(url, configured, **kwargs):
            self.assertEqual(url, 'https://github.com/maruyui-dev/TachiTalk/releases/download/v2.0.1/main-from-2.0.0.json')
            self.assertEqual([s['name'] for s in configured], ['魔搭'])
            body = json.dumps(envelope).encode()
            kwargs['validator'](body)
            return body
        with patch('app.updates.client.fetch_small', fetch):
            got = await self.client.main_manifest('2.0.1', selected_source='魔搭')
        self.assertEqual(got, envelope)
        self.assertEqual(self.client.cached('main'), envelope)

    async def test_unsigned_or_wrong_version_main_manifest_cannot_be_used(self):
        envelope, _ = self.signed()
        envelope['payload']['version'] = '2.0.2'
        async def fetch(url, configured, **kwargs):
            body = json.dumps(envelope).encode()
            kwargs['validator'](body)
            return body
        with patch('app.updates.client.fetch_small', fetch):
            with self.assertRaises(ValueError):
                await self.client.main_manifest('2.0.1', selected_source='GitHub')
        self.assertFalse((self.client.directory / 'main-manifest.json').exists())

    async def test_verified_wrong_base_is_rejected_and_source_change_marks_only_its_cache(self):
        from app.updates.download import Downloader
        from app.updates.manifest import atomic_json
        envelope, _ = self.signed()
        cache = self.client.directory / 'downloads' / envelope['payload']['archive']['sha256']
        atomic_json(cache / 'source-lock.json', Downloader.source_identity({'name': 'GitHub'}))
        (cache / '0000.bin.part').write_bytes(b'keep until user-confirmed worker reset')
        async def fetch(url, configured, **kwargs):
            body = json.dumps(envelope).encode()
            kwargs['validator'](body)
            return body
        with patch('app.updates.client.fetch_small', fetch):
            await self.client.main_manifest('2.0.1', selected_source='魔搭')
        config = self.client.configuration()
        self.assertEqual(config['restart_archives'], [envelope['payload']['archive']['sha256']])
        self.assertNotIn('preferred_download_source', config, 'Main selection must not change voice preferences')
        self.assertTrue((cache / '0000.bin.part').exists())
        envelope['payload']['base_version'] = '1.0.0'
        envelope['signature'] = base64.b64encode(self.key.sign(canonical(envelope['payload']))).decode()
        with patch('app.updates.client.fetch_small', fetch), self.assertRaisesRegex(ValueError, '版本'):
            await self.client.main_manifest('2.0.1', selected_source='GitHub')

    async def test_signed_full_main_archive_overwrites_program_and_preserves_user_data(self):
        from app.updates.install import apply_archive
        from app.updates.manifest import atomic_json, verify
        envelope, archive = self.signed()
        (self.root / 'TachiTalk.exe').write_bytes(b'old executable')
        atomic_json(self.root / 'release-version.json', {'version': VERSION})
        protected = {'user_data/settings.json': b'local settings', 'assets/portrait.png': b'portrait',
            'services/gpt_sovits/model.pth': b'unchanged voice', 'assets/audio/source.wav': b'source'}
        for name, value in protected.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        package = self.root / 'update.zip'
        package.write_bytes(archive)
        apply_archive(self.root, package, verify(envelope, self.client.keys))
        self.assertNotEqual((self.root / 'TachiTalk.exe').read_bytes(), b'old executable')
        self.assertEqual(json.loads((self.root / 'release-version.json').read_text())['version'], '2.0.1')
        for name, value in protected.items():
            self.assertEqual((self.root / name).read_bytes(), value)

    async def test_modelscope_main_mapping_is_version_scoped_and_rejects_unrelated_files(self):
        from app.updates.modelscope import ENTRY, resolve, trusted_redirect
        source = {'prefix': ENTRY, 'layout': 'modelscope'}
        base = 'https://github.com/maruyui-dev/TachiTalk/releases/download/v2.0.1/'
        for name in ('main-from-2.0.0.json', 'main-2.0.1.zip.part000'):
            target = ENTRY + 'main/v2.0.1/' + name
            self.assertEqual(resolve(base + name, source), target)
            self.assertTrue(trusted_redirect(target, target))
        for name in ('voice-manifest.json', 'main-2.0.2.zip.part000', '../bad.exe'):
            with self.assertRaises(ValueError):
                resolve(base + name, source)


class SystemProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_use_system_proxy_and_recheck_redirect_host_bypass(self):
        from app.updates.download import Policy, request
        from aiohttp import web
        seen = []
        async def handler(req):
            seen.append(req.raw_path)
            return web.Response(body=b'proxy fixture')
        app = web.Application()
        app.router.add_route('*', '/{tail:.*}', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        self.addAsyncCleanup(runner.cleanup)
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        proxy = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
        import aiohttp
        with patch('urllib.request.getproxies', return_value={'http': proxy}), \
             patch('urllib.request.proxy_bypass', return_value=False):
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
                response = await request(session, 'http://unresolvable.invalid/fixture', {},
                    Policy(test_origin='http://unresolvable.invalid'))
                try:
                    self.assertEqual(await response.read(), b'proxy fixture')
                finally:
                    response.close()
        self.assertEqual(seen, ['http://unresolvable.invalid/fixture'])


class MainUpdateUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tests.test_main_feed_ui import Panel
        from app.ui.update_controls import UpdateControls
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = UpdateClient(root=self.root, data=self.root / 'data')
        self.panel = Panel()
        self.ui = UpdateControls(self.panel, self.client)
        self.addCleanup(self.cleanup_ui)

    def cleanup_ui(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QEvent
        self.ui.shutdown()
        if self.ui.thread:
            self.ui.thread.join(timeout=3)
        self.ui.deleteLater()
        self.panel.close()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_metadata_can_offer_update_but_cannot_start_install_without_signed_fetch(self):
        from tests.test_main_feed_ui import result
        self.ui.on_finished('main-check', {'value': result()})
        self.assertTrue(self.ui.update_button.isEnabled())
        self.assertIsNone(self.ui.prompt)
        with patch('app.ui.update_controls.FROZEN', True), \
             patch('app.ui.update_controls.QInputDialog.getItem', return_value=('魔搭', True)), \
             patch.object(self.ui, 'start') as start, patch.object(self.ui, 'launch_updater') as install:
            self.ui.update_main()
        self.assertEqual(start.call_args.args[0], 'main-manifest')
        install.assert_not_called()
        self.assertEqual(self.ui.main_source, '魔搭')

    def test_source_checkout_does_not_replace_itself_with_binary_update(self):
        with patch('app.ui.update_controls.FROZEN', False), patch.object(self.ui, 'start') as start:
            self.ui.update_main()
        start.assert_not_called()
        self.assertIn('源码', self.ui.state.text())

    def test_supplied_icon_is_used_by_ui_and_build_does_not_overwrite_it(self):
        from PIL import Image
        from app.paths import PROJECT_ROOT
        from app.ui.control_panel import make_icon
        png = PROJECT_ROOT / 'resources/control_panel/assets/tachitalk.png'
        self.assertTrue(png.is_file())
        self.assertFalse(make_icon('cat', size=48).isNull())
        with Image.open(png) as image, Image.open(PROJECT_ROOT / 'packaging/app.ico') as icon:
            self.assertEqual(image.size, (1254, 1254))
            self.assertIn((256, 256), icon.ico.sizes())
        from scripts.build_release import icon
        before = png.read_bytes()
        icon()
        self.assertEqual(png.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
