"""The public main feed is bounded display metadata, never an updater authority."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from app.updates import main_feed
from app.updates.client import UpdateClient
from app.updates.modelscope import ENTRY


def feed(**changes):
    value = {'schema': 1, 'component': 'main', 'version': '1.3.6', 'channel': 'testing',
             'title': '主程序测试版', 'notes': '修复语音来源选择', 'published_at': '2026-10-24'}
    value.update(changes)
    return value


class MainFeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enabled = patch.object(main_feed, 'ENABLED', True)
        self.enabled.start()
        self.addCleanup(self.enabled.stop)
        self.version = patch.object(main_feed, 'VERSION', '1.3.6')
        self.version.start()
        self.addCleanup(self.version.stop)

    async def check_body(self, body):
        requests = []

        async def fetch(url, configured, **kwargs):
            requests.append((url, copy.deepcopy(configured), dict(kwargs)))
            self.assertEqual(url, ENTRY + 'main-latest.json')
            self.assertEqual(main_feed.URL, url)
            self.assertEqual(len(configured), 1, 'There must be no API, GitHub or proxy fallback')
            self.assertGreater(kwargs['limit'], 0)
            self.assertLessEqual(kwargs['limit'], 64 * 1024)
            if len(body) > kwargs['limit']:
                raise ValueError('Remote response exceeds its configured byte limit')
            if kwargs.get('validator'):
                kwargs['validator'](body)
            return body

        with patch('app.updates.main_feed.fetch_small', fetch):
            result = await main_feed.check()
        self.assertEqual(len(requests), 1, 'The metadata checker must use only the fixed public feed')
        self.assertEqual(result['manifests'], {}, 'Unsigned metadata must not produce an executable manifest')
        self.assertNotIn('installer', result.get('main', {}))
        self.assertNotIn('archive', result.get('main', {}))
        self.assertNotIn('parts', result.get('main', {}))
        return result

    async def check_value(self, value):
        return await self.check_body(json.dumps(value, ensure_ascii=False).encode('utf-8'))

    async def test_gate_closed_never_requests_the_feed(self):
        transport = AsyncMock(side_effect=AssertionError('The closed gate must never perform HTTP'))
        with patch.object(main_feed, 'ENABLED', False), patch('app.updates.main_feed.fetch_small', transport):
            result = await main_feed.check()
        transport.assert_not_awaited()
        self.assertEqual(result['main']['state'], 'disabled')
        self.assertEqual(result['manifests'], {})

    async def test_equal_version_is_current_and_reports_fixed_source(self):
        result = await self.check_value(feed())
        self.assertEqual(result['main']['state'], 'current')
        self.assertEqual(result['main']['version'], '1.3.6')
        self.assertEqual(result['main']['source'], '魔搭社区')
        self.assertEqual(result['errors'], {})

    async def test_newer_version_reports_an_update_without_any_installer_authority(self):
        metadata = feed(version='1.3.7')
        result = await self.check_value(metadata)
        self.assertEqual(result['main']['state'], 'update_available')
        for field in ('version', 'title', 'notes', 'published_at'):
            self.assertEqual(result['main'][field], metadata[field])
        self.assertEqual(result['main']['source'], '魔搭社区')

    async def test_version_comparison_is_numeric_rather_than_lexicographic(self):
        result = await self.check_value(feed(version='1.3.10'))
        self.assertEqual(result['main']['state'], 'update_available')

    async def test_older_feed_never_claims_an_update_or_downgrade(self):
        result = await self.check_value(feed(version='1.3.5'))
        self.assertEqual(result['main']['state'], 'current')
        self.assertEqual(result['main']['version'], '1.3.5')

    async def test_network_failure_returns_error_without_falling_back_to_other_services(self):
        transport = AsyncMock(side_effect=ValueError('HTTP 503 from ModelScope'))
        with patch('app.updates.main_feed.fetch_small', transport):
            result = await main_feed.check()
        self.assertEqual(transport.await_count, 1)
        self.assertEqual(transport.await_args.args[0], ENTRY + 'main-latest.json')
        self.assertEqual(result['main']['state'], 'error')
        self.assertEqual(result['manifests'], {})
        self.assertTrue(result['errors'])
        self.assertNotIn('installer', result['main'])

    async def test_malformed_json_or_html_is_an_error(self):
        for body in (b'<html>gateway failure</html>', b'{', b'[]', b'null'):
            with self.subTest(body=body):
                result = await self.check_body(body)
                self.assertEqual(result['main']['state'], 'error')
                self.assertTrue(result['errors'])

    async def test_invalid_schema_component_or_channel_is_an_error(self):
        for field, value in [('schema', 2), ('schema', True), ('component', 'voice'),
                             ('channel', 'not-a-release-channel')]:
            with self.subTest(field=field, value=value):
                result = await self.check_value(feed(**{field: value}))
                self.assertEqual(result['main']['state'], 'error')
                self.assertTrue(result['errors'])

    async def test_only_a_numeric_three_part_version_is_accepted(self):
        for version in ('v1.3.7', '1.3', '1.3.7.1', '1.3.7-rc1', '1.3.x', '1.-3.7', '', 137, None):
            with self.subTest(version=version):
                result = await self.check_value(feed(version=version))
                self.assertEqual(result['main']['state'], 'error')

    async def test_title_notes_and_publication_fields_are_validated(self):
        for field, value in [('title', 'x' * 513), ('title', ['text']), ('notes', ['text']),
                             ('notes', 'x' * 65537), ('published_at', None),
                             ('published_at', '2026-99-99')]:
            with self.subTest(field=field, type=type(value).__name__):
                result = await self.check_value(feed(**{field: value}))
                self.assertEqual(result['main']['state'], 'error')

    async def test_title_at_the_documented_limit_is_preserved(self):
        title = 'x' * 512
        result = await self.check_value(feed(title=title))
        self.assertEqual(result['main']['state'], 'current')
        self.assertEqual(result['main']['title'], title)

    async def test_missing_required_metadata_is_rejected(self):
        for field in ('schema', 'component', 'version', 'channel', 'title', 'notes', 'published_at'):
            with self.subTest(field=field):
                value = feed()
                del value[field]
                result = await self.check_value(value)
                self.assertEqual(result['main']['state'], 'error')

    async def test_response_above_64_kib_returns_error(self):
        result = await self.check_body(b' ' * (64 * 1024) + json.dumps(feed()).encode())
        self.assertEqual(result['main']['state'], 'error')
        self.assertTrue(result['errors'])

    async def test_unsigned_extra_installer_fields_never_become_an_updater_payload(self):
        result = await self.check_value(feed(version='1.3.7', source='attacker supplied source',
            installer={'url': 'https://evil.example/installer.exe', 'size': 100},
            archive={'url': 'https://evil.example/archive.zip'}, parts=[{'url': 'https://evil.example/part'}]))
        self.assertEqual(result['main']['state'], 'error')
        self.assertTrue(result['errors'])


class MainFeedClientGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.client = UpdateClient(root=root, data=root / 'data')

    async def test_client_closed_gate_returns_disabled_without_dispatching(self):
        check = AsyncMock(side_effect=AssertionError('Closed gate must not dispatch a feed check'))
        with patch.object(main_feed, 'ENABLED', False), patch.object(main_feed, 'check', check):
            result = await self.client.check()
        check.assert_not_awaited()
        self.assertEqual(result['main']['state'], 'disabled')

    async def test_client_enabled_gate_dispatches_only_the_public_metadata_checker(self):
        expected = {'manifests': {}, 'errors': {}, 'main': {'state': 'current', 'version': '1.3.6',
                    'title': 'test', 'notes': '', 'published_at': '2026-10-24', 'source': '魔搭社区'}}
        check = AsyncMock(return_value=expected)
        legacy = AsyncMock(side_effect=AssertionError('No legacy GitHub/API discovery'))
        with patch.object(main_feed, 'ENABLED', True), patch.object(main_feed, 'check', check), \
             patch.object(self.client, '_discover_release', legacy):
            result = await self.client.check()
        check.assert_awaited_once()
        legacy.assert_not_awaited()
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
