"""Dormant release discovery stays verified while the production check entry is disabled."""
import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.updates.client import UpdateClient
from app.updates.manifest import atomic_json, canonical
from tests.test_updates import bundle


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = UpdateClient(root=self.root, data=self.root / 'data')
        config = self.client.configuration()
        # Main-update routes are absent from production defaults. Only this dormant
        # discovery fixture opts in so its signature and metadata rules stay tested.
        config['api_sources'] = [{'name': 'GitHub API', 'enabled': True, 'prefix': ''}]
        atomic_json(self.client.config_path, config)
        self.key = Ed25519PrivateKey.generate()
        self.client.keys = {'test': base64.b64encode(self.key.public_key().public_bytes_raw()).decode()}
        self.version = patch('app.updates.client.VERSION', '1.3.0')
        self.version.start()
        self.addCleanup(self.version.stop)
        self.voice = self.signed(*bundle(component='voice', name='services/gpt_sovits/api_v2.py', base='*'))
        payload, archive = bundle(base='1.3.0')
        payload['version'] = '1.3.1'
        self.main = self.signed(payload, archive)
        self.calls = []

    def signed(self, payload, _archive):
        return {'key_id': 'test', 'payload': payload,
                'signature': base64.b64encode(self.key.sign(canonical(payload))).decode()}

    def check(self, release, main=None, voice=None):
        async def fetch(url, *args, **kwargs):
            self.calls.append(url)
            if 'api.github.com' in url:
                value = release
            elif 'voice-manifest' in url:
                value = self.voice if voice is None else voice
            else:
                value = ValueError('HTTP 404') if main is None else main
            if isinstance(value, Exception):
                raise value
            body = json.dumps(value).encode()
            if kwargs.get('validator'):
                kwargs['validator'](body)
            return body
        with patch('app.updates.client.fetch_small', fetch):
            # Exercise retained discovery explicitly; production callers use disabled check().
            return asyncio.run(self.client._discover_release())

    def test_current_release_does_not_request_nonexistent_main_patch(self):
        result = self.check({'tag_name': 'v1.3.0', 'assets': []})
        self.assertFalse(any('main-from-' in url for url in self.calls), self.calls)
        self.assertNotIn('main', result['errors'])
        self.assertEqual(result['main']['state'], 'current')
        self.assertIn('voice', result['manifests'])

    def test_new_release_without_supported_base_is_not_a_network_error(self):
        result = self.check({'tag_name': 'v1.3.1', 'assets': [{'name': 'voice-manifest.json'}]})
        self.assertEqual(result['main']['state'], 'no_patch')
        self.assertNotIn('main', result['errors'])
        self.assertFalse(any('main-from-' in url for url in self.calls))
        self.assertIn('voice', result['manifests'])

    def test_supported_patch_is_pinned_to_release_and_verified(self):
        result = self.check({'tag_name': 'v1.3.1', 'assets': [{'name': 'main-from-1.3.0.json'}]}, self.main)
        self.assertEqual(result['main']['state'], 'update_available')
        self.assertIn('main', result['manifests'])
        self.assertTrue(any('/download/v1.3.1/main-from-' in url for url in self.calls))

    def test_api_unavailable_preserves_signed_attachment_fallback(self):
        result = self.check(ValueError('API unreachable'), self.main)
        self.assertIn('main', result['manifests'])
        self.assertEqual(result['main']['state'], 'update_available')
        self.assertIn('api', result['errors'])

    def test_api_failure_and_main_404_cannot_claim_latest(self):
        result = self.check(ValueError('API unreachable'))
        self.assertEqual(result['main']['state'], 'unknown')
        self.assertIn('main', result['errors'])
        self.assertIn('voice', result['manifests'])

    def test_published_patch_404_and_signature_failures_remain_errors(self):
        release = {'tag_name': 'v1.3.1', 'assets': [{'name': 'main-from-1.3.0.json'}]}
        for failure in (ValueError('HTTP 404'), ValueError('connection timeout'),
                        dict(self.main, signature='broken')):
            with self.subTest(failure=str(failure)[:40]):
                result = self.check(release, failure)
                self.assertEqual(result['main']['state'], 'error')
                self.assertIn('main', result['errors'])
                self.assertIn('voice', result['manifests'])

    def test_invalid_api_body_falls_back_instead_of_claiming_latest(self):
        result = self.check({'tag_name': 'v1.3.0', 'assets': 'invalid'}, self.main)
        self.assertEqual(result['main']['state'], 'update_available')
        self.assertIn('api', result['errors'])

    def test_wrong_base_and_release_version_mismatch_are_rejected(self):
        release = {'tag_name': 'v1.3.1', 'assets': [{'name': 'main-from-1.3.0.json'}]}
        for field, value in [('base_version', '0.2.0'), ('version', '1.3.2')]:
            payload = dict(self.main['payload'], **{field: value})
            result = self.check(release, self.signed(payload, b''))
            self.assertNotIn('main', result['manifests'])
            self.assertIn('main', result['errors'])

    def test_voice_failure_does_not_change_current_main_state(self):
        result = self.check({'tag_name': 'v1.3.0', 'assets': []}, voice=ValueError('voice timeout'))
        self.assertEqual(result['main']['state'], 'current')
        self.assertIn('voice', result['errors'])
        self.assertNotIn('main', result['errors'])
