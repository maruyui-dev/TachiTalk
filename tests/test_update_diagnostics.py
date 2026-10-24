import asyncio
import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.updates.client import UpdateClient
from app.updates.download import Policy
from app.updates.manifest import canonical
from tests.test_updates import bundle


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.client = UpdateClient(root=root, data=root / 'data')
        key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        self.payload, _ = bundle(component='voice', name='services/gpt_sovits/api_v2.py', base='*')
        self.envelope = {'key_id': 'test', 'payload': self.payload,
            'signature': base64.b64encode(key.sign(canonical(self.payload))).decode()}

    async def test_real_resource_failure_is_not_hidden_by_manifest_success(self):
        self.assertTrue(callable(getattr(self.client, 'diagnose', None)), 'client needs a resource preflight')
        async def probe(url, **kwargs):
            return {'state': 'ok', 'latency_ms': 2} if url.endswith('.json') else {'state': 'timeout', 'detail': 'timeout'}
        with patch('app.updates.diagnostics.probe_url', probe):
            result = await self.client.diagnose(self.envelope)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['manifest']['state'], 'ok')
        self.assertEqual(result['artifact']['state'], 'timeout')

    async def test_manual_diagnostics_probe_github_and_modelscope_without_cloudflare(self):
        seen = []
        async def probe(url, **kwargs):
            seen.append(kwargs.get('source', {}).get('prefix'))
            return {'state': 'ok', 'latency_ms': 2}
        with patch('app.updates.diagnostics.probe_url', probe):
            result = await self.client.diagnose(self.envelope)
        self.assertEqual(seen.count(''), 2)
        self.assertEqual(seen.count('https://modelscope.cn/models/MaruYui/TachiTalk-Voice-Runtime/resolve/master/'), 2)
        self.assertEqual(result.get('channel'), 'GitHub')
        self.assertEqual(result['modelscope']['artifact']['state'], 'ok')
        self.assertFalse(any('jieyiblog.me' in (prefix or '') for prefix in seen))

    async def test_tampered_manifest_never_supplies_probe_artifact(self):
        self.assertTrue(callable(getattr(self.client, 'diagnose', None)), 'client needs a resource preflight')
        self.envelope['payload']['notes'] = 'tampered'
        seen = []
        async def probe(url, **kwargs):
            seen.append(url)
            return {'state': 'ok', 'latency_ms': 2}
        with patch('app.updates.diagnostics.probe_url', probe):
            result = await self.client.diagnose(self.envelope)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['artifact']['state'], 'unknown')
        self.assertTrue(result['manifest_error'])
        self.assertEqual(len(seen), 2, 'Both configured channels may probe only the fixed manifest endpoint')
        self.assertTrue(all(url.endswith('voice-manifest.json') for url in seen), seen)

    async def test_cancelled_diagnostics_never_probes(self):
        self.assertTrue(callable(getattr(self.client, 'diagnose', None)), 'client needs a resource preflight')
        stop = Event()
        stop.set()
        async def unexpected(*args, **kwargs):
            self.fail('cancelled preflight must not start HTTP')
        with patch('app.updates.diagnostics.probe_url', unexpected):
            result = await self.client.diagnose(self.envelope, stop=stop)
        self.assertEqual(result['state'], 'cancelled')

    async def serve(self, handler):
        app = web.Application()
        app.router.add_get('/{name}', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        self.addAsyncCleanup(runner.cleanup)
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        origin = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
        return origin

    async def test_proxy_presence_is_not_confused_with_public_download_relays(self):
        from app.updates.diagnostics import proxy_status
        with patch('app.updates.diagnostics.getproxies', return_value={'no': 'localhost'}), \
             patch('app.updates.diagnostics.pac_configured', return_value=False):
            self.assertEqual(proxy_status()['state'], 'not_found')
        with patch('app.updates.diagnostics.getproxies', return_value={'https': 'http://user:secret@127.0.0.1:1234'}), \
             patch('app.updates.diagnostics.pac_configured', return_value=False):
            result = proxy_status()
            self.assertEqual(result['state'], 'detected')
            self.assertNotIn('secret', str(result))
        with patch('app.updates.diagnostics.getproxies', side_effect=PermissionError('registry')):
            self.assertEqual(proxy_status()['state'], 'unknown')

    async def test_first_run_canonical_latest_manifest_reaches_transport_but_arbitrary_url_does_not(self):
        from unittest.mock import AsyncMock
        from app.updates.diagnostics import probe_url
        latest = 'https://github.com/maruyui-dev/TachiTalk/releases/latest/download/voice-manifest.json'
        with patch('app.updates.diagnostics.request', new=AsyncMock(side_effect=OSError('transport reached'))) as request:
            result = await probe_url(latest, kind='manifest')
            self.assertIn('transport reached', result['detail'])
            request.assert_awaited_once()
        with patch('app.updates.diagnostics.request', new=AsyncMock()) as request:
            result = await probe_url('https://evil.example/voice-manifest.json', kind='manifest')
            self.assertEqual(result['state'], 'error')
            request.assert_not_awaited()

    async def test_reset_cancel_preserves_cache_and_reset_removes_only_this_archive(self):
        cache = self.client.directory / 'downloads' / self.payload['archive']['sha256']
        cache.mkdir(parents=True)
        (cache / '0000.bin.part').write_bytes(b'old source prefix')
        stop = Event()
        stop.set()
        from app.updates.download import Paused
        with self.assertRaises(Paused):
            self.client.reset_download(self.envelope, stop)
        self.assertTrue(cache.is_dir())
        stop.clear()
        self.client.reset_download(self.envelope, stop)
        self.assertFalse(cache.exists())

    async def test_reset_rejects_a_linked_download_directory(self):
        from subprocess import run, CREATE_NO_WINDOW
        downloads = self.client.directory / 'downloads'
        external = self.client.root / 'outside-cache'
        external.mkdir()
        target = external / self.payload['archive']['sha256']
        target.mkdir()
        (target / 'keep').write_text('preserve')
        run(['cmd', '/c', 'mklink', '/J', str(downloads), str(external)], check=True,
            capture_output=True, creationflags=CREATE_NO_WINDOW)
        self.addCleanup(downloads.rmdir)
        with self.assertRaises(ValueError):
            self.client.reset_download(self.envelope, Event())
        self.assertEqual((target / 'keep').read_text(), 'preserve')

    async def test_cancel_during_cache_scan_prevents_deletion(self):
        from app.updates.download import Paused
        cache = self.client.directory / 'downloads' / self.payload['archive']['sha256']
        cache.mkdir(parents=True)
        stop = Event()
        def scan(*args):
            stop.set()
            return iter(())
        with patch.object(Path, 'rglob', scan):
            with self.assertRaises(Paused):
                self.client.reset_download(self.envelope, stop)
        self.assertTrue(cache.exists())

    async def test_pending_source_reset_survives_app_restart_before_prepare(self):
        from unittest.mock import AsyncMock
        from app.updates.download import Paused
        from app.updates.manifest import atomic_json
        cache = self.client.directory / 'downloads' / self.payload['archive']['sha256']
        cache.mkdir(parents=True)
        (cache / '0000.bin.part').write_bytes(b'old source')
        config = self.client.configuration()
        config['restart_archives'] = [self.payload['archive']['sha256'], 'e' * 64]
        atomic_json(self.client.config_path, config)
        restarted = UpdateClient(root=self.client.root, data=self.client.data)
        restarted.keys = self.client.keys
        with patch('app.updates.diagnostics.select_voice_source', new=AsyncMock(return_value={'source': '魔搭'})), \
             patch('app.updates.client.Downloader.download', new=AsyncMock(side_effect=Paused('test ends before network'))):
            with self.assertRaises(Paused):
                await restarted.prepare(self.envelope, lambda value: None, Event())
        self.assertFalse((cache / '0000.bin.part').exists(), 'pending source change must clear old prefix after restart')
        self.assertEqual(restarted.configuration()['restart_archives'], ['e' * 64])

    async def test_probe_uses_bounded_range_and_accepts_real_206(self):
        self.assertTrue(callable(getattr(self.client, 'diagnose', None)), 'client needs a resource preflight')
        from app.updates.diagnostics import probe_url
        received = []
        async def handler(request):
            received.append(request.headers.get('Range'))
            return web.Response(status=206, body=b'x' * 1024,
                headers={'Content-Range': 'bytes 0-1023/5000', 'Content-Type': 'application/octet-stream'})
        origin = await self.serve(handler)
        result = await probe_url(origin + '/part', kind='artifact', expected_size=5000, policy=Policy(origin))
        self.assertEqual(received, ['bytes=0-1023'])
        self.assertEqual(result['state'], 'ok')
        self.assertLessEqual(result['bytes_read'], 1024)
        self.assertGreaterEqual(result['latency_ms'], 0)

    async def test_probe_rejects_html_wrong_range_404_and_has_total_timeout(self):
        self.assertTrue(callable(getattr(self.client, 'diagnose', None)), 'client needs a resource preflight')
        from app.updates.diagnostics import probe_url
        async def handler(request):
            if request.match_info['name'] == 'html':
                return web.Response(text='<html>gateway error</html>', content_type='text/html')
            if request.match_info['name'] == 'range':
                return web.Response(status=206, body=b'x' * 8, headers={'Content-Range': 'bytes 4-11/5000'})
            if request.match_info['name'] == 'slow':
                await asyncio.sleep(.1)
                return web.Response(body=b'x')
            return web.Response(status=404)
        origin = await self.serve(handler)
        for name in ('html', 'range', 'missing'):
            with self.subTest(name=name):
                result = await probe_url(origin + '/' + name, kind='artifact', expected_size=5000, policy=Policy(origin))
                self.assertEqual(result['state'], 'error')
        result = await probe_url(origin + '/slow', kind='artifact', policy=Policy(origin), timeout=.025)
        self.assertEqual(result['state'], 'timeout')

    async def test_server_ignoring_range_is_sampled_and_does_not_become_a_full_download(self):
        from app.updates.diagnostics import probe_url
        async def handler(request):
            return web.Response(body=b'x' * 100000, content_type='application/octet-stream')
        origin = await self.serve(handler)
        result = await probe_url(origin + '/part', kind='artifact', expected_size=100000, policy=Policy(origin))
        self.assertEqual(result['state'], 'ok')
        self.assertEqual(result['bytes_read'], 1024)


if __name__ == '__main__':
    unittest.main()
