"""Voice routing remains independent of the temporarily disabled main updater."""
import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.updates.client import UpdateClient
from app.updates import diagnostics
from app.updates.download import Paused, Policy, sources
from app.updates.install import apply_archive
from app.updates.manifest import atomic_json, canonical
from app.version import VERSION
from tests.test_updates import bundle


CLOUDFLARE_PREFIXES = ('https://download.jieyiblog.me/', 'https://dl.jieyiblog.me/')


def legacy_config(version=4):
    return {
        'config_version': version,
        'preferred_download_source': 'Cloudflare 官方下载',
        'restart_archives': ['a' * 64],
        **{kind: [
            {'name': 'Cloudflare 官方下载', 'prefix': CLOUDFLARE_PREFIXES[0],
             'layout': 'r2', 'enabled': True, 'priority': -100},
            {'name': 'old domain', 'prefix': CLOUDFLARE_PREFIXES[1],
             'layout': 'r2', 'enabled': True, 'priority': -99},
            {'name': 'GitHub', 'prefix': '', 'enabled': True, 'priority': 0},
            {'name': 'custom disabled mirror', 'prefix': 'https://example.org/',
             'enabled': False, 'priority': 50},
        ] for kind in ('sources', 'api_sources', 'manifest_sources')},
    }


class RemovedCloudflareTests(unittest.TestCase):
    def test_fresh_client_has_no_cloudflare_download_or_metadata_route(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            config = UpdateClient(root=root, data=root / 'data').configuration()
            for kind in ('sources', 'api_sources', 'manifest_sources'):
                with self.subTest(kind=kind):
                    self.assertFalse(any(item.get('prefix') in CLOUDFLARE_PREFIXES
                                         or item.get('layout') == 'r2'
                                         for item in config[kind]), config[kind])

    def test_every_legacy_config_migrates_without_reenabling_cloudflare(self):
        for version in (1, 2, 3, 4):
            with self.subTest(version=version), TemporaryDirectory() as folder:
                root = Path(folder)
                config_path = root / 'data/updates/download_sources.json'
                atomic_json(config_path, legacy_config(version))
                config = UpdateClient(root=root, data=root / 'data').configuration()
                self.assertNotEqual(config.get('preferred_download_source'), 'Cloudflare 官方下载')
                self.assertEqual(config['restart_archives'], ['a' * 64])
                for kind in ('sources', 'api_sources', 'manifest_sources'):
                    self.assertFalse(any(item.get('prefix') in CLOUDFLARE_PREFIXES
                                         or item.get('layout') == 'r2'
                                         for item in config[kind]), config[kind])
                    self.assertIn({'name': 'custom disabled mirror', 'prefix': 'https://example.org/',
                                   'enabled': False, 'priority': 50}, config[kind])
                self.assertEqual(UpdateClient(root=root, data=root / 'data').configuration(), config)

    def test_stale_in_memory_config_cannot_reintroduce_cloudflare_as_fallback(self):
        config = legacy_config()
        for kind in ('sources', 'api_sources', 'manifest_sources'):
            with self.subTest(kind=kind):
                configured = sources(config, kind)
                self.assertFalse(any(item.get('prefix') in CLOUDFLARE_PREFIXES
                                     or item.get('layout') == 'r2' for item in configured), configured)
                self.assertEqual([item['name'] for item in configured], ['GitHub'])


class IndependentVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        gate = patch('app.updates.main_feed.ENABLED', False)
        gate.start()
        self.addCleanup(gate.stop)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = UpdateClient(root=self.root, data=self.root / 'data')
        self.key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(self.key.public_key().public_bytes_raw()).decode()}
        self.payload, self.archive = bundle(component='voice', name='services/gpt_sovits/api_v2.py', base='*')
        self.envelope = {'key_id': 'test', 'payload': self.payload,
                         'signature': base64.b64encode(self.key.sign(canonical(self.payload))).decode()}

    async def test_check_is_disabled_and_makes_no_version_or_manifest_http_request(self):
        requested = []

        async def fetch(url, *args, **kwargs):
            requested.append(url)
            value = {'tag_name': 'v' + VERSION, 'assets': []} if 'api.github.com' in url else self.envelope
            body = json.dumps(value).encode()
            if kwargs.get('validator'):
                kwargs['validator'](body)
            return body

        with patch('app.updates.client.fetch_small', fetch):
            result = await self.client.check()
        self.assertEqual(requested, [], 'Disabled main update checks must not make HTTP requests')
        self.assertEqual(result['main']['state'], 'disabled')
        self.assertEqual(result['manifests'], {})
        self.assertEqual(result['errors'], {})

    async def test_signed_offline_import_and_verified_cached_voice_install_do_not_need_update_check(self):
        imported = self.root / 'offline-manifest.json'
        atomic_json(imported, self.envelope)
        self.assertEqual(self.client.import_manifest(imported), self.envelope)
        self.assertEqual(self.client.cached('voice'), self.envelope)
        cache = self.client.directory / 'downloads' / self.payload['archive']['sha256']
        cache.mkdir(parents=True)
        (cache / '0000.bin').write_bytes(self.archive)
        before = canonical(self.envelope)
        requested = []

        async def forbidden(url, *args, **kwargs):
            requested.append(url)
            raise AssertionError('A fully cached signed voice package needs no HTTP')

        with patch('app.updates.client.fetch_small', forbidden), \
             patch('app.updates.download.request', forbidden):
            prepared = await self.client.prepare(self.envelope, lambda value: None, Event())
        self.assertEqual(requested, [])
        self.assertEqual(canonical(self.envelope), before, 'Changing channels must preserve the signed payload')
        atomic_json(self.root / 'release-version.json', {'version': self.payload['version']})
        apply_archive(self.root, prepared['archive'], prepared['payload'])
        self.assertEqual((self.root / 'services/gpt_sovits/api_v2.py').read_bytes(), b'new executable')

    async def test_voice_manifest_can_be_fetched_directly_without_check_or_version_api(self):
        requested = []

        async def fetch(url, configured, **kwargs):
            requested.append(url)
            self.assertTrue(url.endswith('/voice-manifest.json'), url)
            self.assertFalse(any(item.get('layout') == 'r2' for item in configured))
            body = json.dumps(self.envelope).encode()
            if kwargs.get('validator'):
                kwargs['validator'](body)
            return body

        with patch.object(self.client, 'check', new=AsyncMock(side_effect=AssertionError('No update prerequisite'))), \
             patch('app.updates.client.fetch_small', fetch):
            fetched = await self.client.voice_manifest()
        self.assertEqual(fetched, self.envelope)
        self.assertTrue(requested)
        self.assertTrue(all('/voice-manifest.json' in url and 'api.github.com' not in url
                            and 'main-from-' not in url for url in requested), requested)
        self.assertEqual(self.client.cached('voice'), self.envelope)

    async def test_direct_voice_fetch_rejects_tampered_signature_without_replacing_cached_manifest(self):
        atomic_json(self.client.directory / 'voice-manifest.json', self.envelope)
        tampered = dict(self.envelope, payload=dict(self.payload, notes='changed without signing'))

        async def fetch(*args, **kwargs):
            body = json.dumps(tampered).encode()
            if kwargs.get('validator'):
                kwargs['validator'](body)
            return body

        with patch('app.updates.client.fetch_small', fetch), self.assertRaises(ValueError):
            await self.client.voice_manifest()
        self.assertEqual(self.client.cached('voice'), self.envelope)

    async def test_direct_voice_fetch_rejects_a_validly_signed_main_manifest(self):
        payload, _ = bundle()
        wrong = {'key_id': 'test', 'payload': payload,
                 'signature': base64.b64encode(self.key.sign(canonical(payload))).decode()}

        async def fetch(*args, **kwargs):
            body = json.dumps(wrong).encode()
            if kwargs.get('validator'):
                kwargs['validator'](body)
            return body

        with patch('app.updates.client.fetch_small', fetch), self.assertRaises(ValueError):
            await self.client.voice_manifest()
        self.assertFalse((self.client.directory / 'voice-manifest.json').exists())

    async def test_resuming_pinned_voice_task_preserves_prefix_and_does_not_probe_again(self):
        cache = self.client.directory / 'downloads' / self.payload['archive']['sha256']
        cache.mkdir(parents=True)
        partial = cache / '0000.bin.part'
        partial.write_bytes(self.archive[:10])
        part = self.payload['parts'][0]
        atomic_json(cache / '0000.bin.state.json', {'url': part['url'], 'etag': '"voice-v1"',
                    'sha256': part['sha256'], 'size': part['size']})
        identity = {'name': 'GitHub', 'prefix': '', 'layout': 'prefix'}
        atomic_json(cache / 'source-lock.json', identity)
        probe = AsyncMock(side_effect=AssertionError('A resumed task must retain its original source'))
        request = AsyncMock(side_effect=Paused('Test stops at the HTTP boundary'))
        with patch('app.updates.diagnostics.select_voice_source', probe), \
             patch('app.updates.download.request', request), self.assertRaises(Paused):
            await self.client.prepare(self.envelope, lambda value: None, Event())
        probe.assert_not_awaited()
        self.assertEqual(request.await_args.args[1], part['url'])
        self.assertEqual(request.await_args.args[2], {'Range': 'bytes=10-', 'If-Range': '"voice-v1"'})
        self.assertEqual(partial.read_bytes(), self.archive[:10])
        self.assertEqual(json.loads((cache / 'source-lock.json').read_text()), identity)


class GithubResponseRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.artifact = {
            'url': 'https://github.com/maruyui-dev/TachiTalk/releases/download/v1.3.0/voice.zip.part000',
            'size': 123456, 'sha256': 'b' * 64,
        }

    async def select(self, probe_result):
        probe = AsyncMock(return_value=probe_result)
        progress = []
        with patch('app.updates.diagnostics.probe_url', probe):
            result = await diagnostics.select_voice_source(self.artifact, progress=progress.append)
        args, kwargs = probe.await_args
        self.assertEqual(args[0], self.artifact['url'], 'Probe the actual signed attachment download URL')
        self.assertEqual(kwargs['kind'], 'artifact')
        self.assertEqual(kwargs['expected_size'], self.artifact['size'])
        self.assertGreater(kwargs['timeout'], 0)
        self.assertLessEqual(kwargs['timeout'], 3)
        self.assertFalse(kwargs.get('source', {}).get('prefix'), 'Measure the direct GitHub channel')
        self.assertEqual(result['probe'], probe_result)
        self.assertTrue(result.get('reason'))
        self.assertTrue(progress, 'The worker must report its detection state for the UI')
        return result

    async def test_249_ms_uses_github(self):
        result = await self.select({'state': 'ok', 'latency_ms': 249, 'bytes_read': 1024})
        self.assertEqual(result['source'], 'GitHub')

    async def test_exactly_250_ms_uses_modelscope(self):
        result = await self.select({'state': 'ok', 'latency_ms': 250, 'bytes_read': 1024})
        self.assertEqual(result['source'], '魔搭')

    async def test_fractional_ms_below_250_is_not_rounded_up_before_selection(self):
        result = await self.select({'state': 'ok', 'latency_ms': 249.9999, 'bytes_read': 1024})
        self.assertEqual(result['source'], 'GitHub')

    async def test_fractional_ms_above_250_uses_modelscope(self):
        result = await self.select({'state': 'ok', 'latency_ms': 250.0001, 'bytes_read': 1024})
        self.assertEqual(result['source'], '魔搭')

    async def test_slow_github_uses_modelscope(self):
        result = await self.select({'state': 'ok', 'latency_ms': 850, 'bytes_read': 1024})
        self.assertEqual(result['source'], '魔搭')

    async def test_github_timeout_uses_modelscope_without_fabricating_zero_ms(self):
        result = await self.select({'state': 'timeout', 'detail': 'connection or first byte timeout'})
        self.assertEqual(result['source'], '魔搭')
        self.assertNotIn('latency_ms', result['probe'])

    async def test_connection_failure_uses_modelscope_without_fabricating_zero_ms(self):
        result = await self.select({'state': 'error', 'detail': 'connection failed'})
        self.assertEqual(result['source'], '魔搭')
        self.assertNotIn('latency_ms', result['probe'])

    async def test_abnormal_response_uses_modelscope_even_if_it_failed_quickly(self):
        result = await self.select({'state': 'error', 'latency_ms': 10, 'detail': 'HTTP 403'})
        self.assertEqual(result['source'], '魔搭')

    async def test_first_byte_metric_includes_request_setup_but_not_the_rest_of_probe_body(self):
        clock = [10.0]
        reads = []

        class Content:
            async def read(self, size):
                reads.append(size)
                if len(reads) == 1:
                    clock[0] += .049
                    return b'x'
                clock[0] += 7
                return b'x' * min(size, 1023)

        class Response:
            status = 206
            headers = {'Content-Range': 'bytes 0-1023/123456', 'Content-Type': 'application/octet-stream'}
            content_length = 1024
            content = Content()

            def close(self):
                pass

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        async def response(*args, **kwargs):
            clock[0] += .2  # Connection and the redirect chain precede the first body byte.
            return Response()

        with patch('app.updates.diagnostics.monotonic', side_effect=lambda: clock[0]), \
             patch('app.updates.diagnostics.session_for', return_value=Session()), \
             patch('app.updates.diagnostics.request', response):
            result = await diagnostics.probe_url(self.artifact['url'], kind='artifact',
                                                 expected_size=self.artifact['size'])
        self.assertEqual(result['state'], 'ok', result)
        # monotonic() subtraction uses binary floats; 248.99999999999878 is 249 ms.
        # Routing above deliberately tests the unrounded value at the strict boundary.
        self.assertAlmostEqual(result['latency_ms'], 249, places=6)
        self.assertEqual(result['bytes_read'], 1024)


if __name__ == '__main__':
    unittest.main()
