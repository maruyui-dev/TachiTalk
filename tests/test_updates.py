import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
import zipfile

from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.updates.download import Downloader, Paused, Policy, sources, fetch_small
from app.updates.install import InstallLock, apply_archive, local_version, recover, uninstall_voice
from app.updates.manifest import canonical, verify, validate, sha256, atomic_json, load_signed


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bundle(component='main', data=b'new executable', base='0.2.0', name='TachiTalk.exe'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as zipped:
        zipped.writestr(name, data)
    archive = output.getvalue()
    payload = {'schema': 1, 'component': component, 'version': '1.3.0', 'base_version': base,
        'title': '新版本', 'notes': '气泡和对话改进', 'published_at': '2026-10-22',
        'files': [{'path': name, 'size': len(data), 'sha256': digest(data)}], 'delete': [],
        'archive': {'size': len(archive), 'sha256': digest(archive)},
        'parts': [{'name': 'patch.zip', 'size': len(archive), 'sha256': digest(archive),
                   'url': 'https://github.com/maruyui-dev/TachiTalk/releases/download/v1.3.0/patch.zip'}]}
    return payload, archive


class ManifestTests(unittest.TestCase):
    def test_large_runtime_inventory_remains_bounded_and_signature_verified(self):
        payload, _ = bundle()
        payload['files'] = [{'path': f'_internal/large-runtime-directory-{index:05d}/dependency.dll',
                             'size': 0, 'sha256': digest(b'')} for index in range(65000)]
        key = Ed25519PrivateKey.generate()
        keys = {'test': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
        envelope = {'key_id': 'test', 'payload': payload,
                    'signature': base64.b64encode(key.sign(canonical(payload))).decode()}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'large.json'
            atomic_json(path, envelope)
            self.assertGreater(path.stat().st_size, 8 * 1024**2)
            self.assertEqual(len(load_signed(path, keys)[1]['files']), 65000)
    def test_standby_proxies_follow_primary_sources_and_explicit_disable_is_respected(self):
        configured = sources({'sources': [{'name': 'proxy', 'fallback_only': True, 'priority': -99},
            {'name': 'official', 'priority': 10}, {'name': 'disabled proxy', 'enabled': False, 'fallback_only': True}]})
        self.assertEqual([s['name'] for s in configured], ['official', 'proxy'])
    def test_signature_and_tampered_payload_and_unknown_key(self):
        payload, _ = bundle()
        private = Ed25519PrivateKey.generate()
        keys = {'test': base64.b64encode(private.public_key().public_bytes_raw()).decode()}
        envelope = {'key_id': 'test', 'payload': payload,
                    'signature': base64.b64encode(private.sign(canonical(payload))).decode()}
        self.assertEqual(verify(envelope, keys), payload)
        with self.assertRaises(ValueError):
            verify(envelope, {})
        payload['notes'] = 'tampered'
        with self.assertRaises(ValueError):
            verify(envelope, keys)

    def test_rejects_untrusted_urls_and_paths_and_user_data(self):
        for name in ('../escape', 'C:/test', 'NUL.txt', 'assets/custom.png', 'settings/user.json',
                     'services/gpt_sovits/runtime/python.exe', '_internal/../config.py', '_internal/CON.dll'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                payload, _ = bundle(name=name)
                validate(payload)
        payload, _ = bundle()
        payload['parts'][0]['url'] = 'https://evil.example/run.exe'
        with self.assertRaises(ValueError):
            validate(payload)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'TachiTalk.exe').write_bytes(b'old')
        self.payload, archive = bundle()
        self.archive = self.root / 'patch.zip'
        self.archive.write_bytes(archive)

    def test_main_patch_preserves_voice_and_user_resources_and_migrates_legacy(self):
        files = ['services/gpt_sovits/runtime/python.exe', 'assets/custom.png', 'logs/user.log', 'settings/user.json']
        for name in files:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'user data')
        apply_archive(self.root, self.archive, self.payload)
        self.assertEqual(local_version(self.root), '1.3.0')
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'new executable')
        for name in files:
            self.assertEqual((self.root / name).read_bytes(), b'user data')

    def test_failure_restores_original_files_and_version(self):
        def fault(*args):
            raise PermissionError('simulated occupied file')
        with self.assertRaises(PermissionError):
            apply_archive(self.root, self.archive, self.payload, fault=fault)
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'old')
        self.assertEqual(local_version(self.root), '0.2.0')
        self.assertFalse((self.root / '.tachitalk-pending.json').exists())

    def test_wrong_base_and_corrupt_archive_are_rejected(self):
        self.payload['base_version'] = '0.1.0'
        with self.assertRaises(ValueError):
            apply_archive(self.root, self.archive, self.payload)
        self.payload['base_version'] = '0.2.0'
        self.archive.write_bytes(b'bad')
        with self.assertRaises(ValueError):
            apply_archive(self.root, self.archive, self.payload)
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'old')

    def test_zip_hash_and_inventory_must_match_signed_manifest(self):
        self.payload['files'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            apply_archive(self.root, self.archive, self.payload)
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'old')

    def test_concurrent_installer_is_rejected(self):
        with InstallLock(self.root):
            with self.assertRaises(RuntimeError):
                apply_archive(self.root, self.archive, self.payload)

    def test_large_file_transaction_journal_writes_grow_linearly(self):
        output = io.BytesIO()
        records = []
        with zipfile.ZipFile(output, 'w') as zipped:
            for index in range(64):
                name = f'_internal/file-{index:03d}.bin'
                data = b'new contents'
                zipped.writestr(name, data)
                records.append({'path': name, 'size': len(data), 'sha256': digest(data)})
        data = output.getvalue()
        self.archive.write_bytes(data)
        self.payload['files'] = records
        self.payload['archive'] = {'size': len(data), 'sha256': digest(data)}
        self.payload['parts'][0].update(size=len(data), sha256=digest(data))
        writes = []
        def persist(path, value):
            if Path(path).name == '.tachitalk-pending.json':
                writes.append(len(canonical(value)))
            atomic_json(path, value)
        with patch('app.updates.install.atomic_json', persist):
            apply_archive(self.root, self.archive, self.payload)
        self.assertLessEqual(sum(writes), 3 * max(writes), '重写不断增长的全量journal会令数万文件安装出现平方级I/O')

    def test_explicit_delete_is_backed_up_and_failure_restores_it(self):
        (self.root / 'README.md').write_bytes(b'keep if failure')
        self.payload['delete'] = ['README.md']
        def fault(index, name):
            if name == 'README.md':
                raise OSError('disk failure')
        with self.assertRaises(OSError):
            apply_archive(self.root, self.archive, self.payload, fault=fault)
        self.assertEqual((self.root / 'README.md').read_bytes(), b'keep if failure')

    def test_process_crash_journal_can_be_replayed(self):
        saved = self.root / '.tachitalk-transactions/test/backup/TachiTalk.exe'
        saved.parent.mkdir(parents=True)
        saved.write_bytes(b'old')
        atomic_json(self.root / '.tachitalk-pending.json', {'component': 'main', 'state': 'applying',
            'backup': '.tachitalk-transactions/test/backup',
            'operations': [{'path': 'TachiTalk.exe', 'existed': True, 'sha256': sha256(saved)}]})
        (self.root / 'TachiTalk.exe').write_bytes(b'half updated')
        with InstallLock(self.root):
            recover(self.root)
        self.assertEqual((self.root / 'TachiTalk.exe').read_bytes(), b'old')

    def test_managed_voice_uninstall_preserves_modified_and_unowned_files(self):
        payload, archive = bundle(component='voice', name='services/gpt_sovits/runtime/python.exe', base='*')
        atomic_json(self.root / 'release-version.json', {'version': '1.3.0'})
        self.archive.write_bytes(archive)
        apply_archive(self.root, self.archive, payload)
        extra = self.root / 'services/gpt_sovits/user.ckpt'
        extra.write_bytes(b'user')
        uninstall_voice(self.root)
        self.assertFalse((self.root / payload['files'][0]['path']).exists())
        self.assertEqual(extra.read_bytes(), b'user')
        apply_archive(self.root, self.archive, payload)
        managed = self.root / payload['files'][0]['path']
        managed.write_bytes(b'user modified')
        preserved = uninstall_voice(self.root)
        self.assertIn(payload['files'][0]['path'], preserved)
        self.assertEqual(managed.read_bytes(), b'user modified')

    def test_voice_patch_checks_component_and_main_compatibility(self):
        payload, archive = bundle(component='voice', name='services/gpt_sovits/api_v2.py')
        self.archive.write_bytes(archive)
        with self.assertRaises(ValueError):
            apply_archive(self.root, self.archive, payload)
        atomic_json(self.root / 'release-version.json', {'version': '1.3.0'})
        payload['base_version'] = 'wrong-voice-version'
        with self.assertRaises(ValueError):
            apply_archive(self.root, self.archive, payload)


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'download.zip'
        self.data = bytes(range(256)) * 8192
        self.mode = 'range'
        self.requests = []
        self.etag = '"v1"'
        app = web.Application()
        app.router.add_get('/{path:.*}', self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.origin = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
        self.addAsyncCleanup(self.runner.cleanup)
        self.artifact = {'url': self.origin + '/file', 'size': len(self.data), 'sha256': digest(self.data)}
        self.source = sources({'sources': [{'name': 'local', 'retries': 0}]})
        self.policy = Policy(test_origin=self.origin)

    async def handle(self, request):
        self.requests.append((request.path, request.headers.get('Range')))
        if request.path == '/invalid-metadata':
            return web.Response(body=b'<html>proxy returned an error with status 200</html>')
        if request.path == '/fail':
            return web.Response(status=503)
        if self.mode == 'broken':
            return web.Response(body=b'X' * len(self.data), headers={'ETag': self.etag})
        offset = 0
        if self.mode != 'ignore' and request.headers.get('If-Range') == self.etag:
            offset = int(request.headers.get('Range', 'bytes=0-')[6:-1])
        headers = {'ETag': self.etag, 'Content-Length': str(len(self.data) - offset)}
        if offset:
            headers['Content-Range'] = f'bytes {offset}-{len(self.data)-1}/{len(self.data)}'
            if self.mode == 'bad-range':
                headers['Content-Range'] = f'bytes 0-{len(self.data)-1}/{len(self.data)}'
        response = web.StreamResponse(status=206 if offset else 200, headers=headers)
        await response.prepare(request)
        try:
            for position in range(offset, len(self.data), 32768):
                await response.write(self.data[position:position + 32768])
                if self.mode in ('disconnect', 'disconnect-once') and position > 100000:
                    if self.mode == 'disconnect-once':
                        self.mode = 'range'
                    request.transport.close()
                    break
                await asyncio.sleep(.001)
        except (ConnectionError, RuntimeError):
            pass
        return response

    async def paused(self):
        stop = Event()
        def progress(value):
            if value.get('done', 0) > 100000:
                stop.set()
        download = Downloader(self.source, policy=self.policy, stop=stop, progress=progress)
        with self.assertRaises(Paused):
            await download.download(self.artifact, self.path)
        self.assertGreater(self.path.with_suffix('.zip.part').stat().st_size, 0)

    async def test_pause_and_restart_resumes_and_verifies(self):
        await self.paused()
        await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertIsNotNone(self.requests[-1][1])

    async def test_invalid_200_metadata_falls_back_before_accepting_a_source(self):
        origin = self.origin
        class MetadataPolicy(Policy):
            def source_url(self, url, source):
                return origin + ('/invalid-metadata' if source['name'] == 'invalid' else '/file')
        configured = sources({'sources': [{'name': 'invalid', 'retries': 0}, {'name': 'valid', 'retries': 0}]})
        def validate_body(body):
            if digest(body) != digest(self.data):
                raise ValueError('metadata validation failed')
        body = await fetch_small(self.origin + '/file', configured,
                                 policy=MetadataPolicy(test_origin=origin), validator=validate_body)
        self.assertEqual(body, self.data)
        self.assertEqual([path for path, _ in self.requests], ['/invalid-metadata', '/file'])

    async def test_complete_partial_is_verified_without_downloading_again(self):
        self.path.with_suffix('.zip.part').write_bytes(self.data)
        await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertEqual(self.requests, [])

    async def test_network_disconnect_preserves_resumable_bytes(self):
        self.mode = 'disconnect'
        with self.assertRaises(ValueError):
            await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.mode = 'range'
        await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertIsNotNone(self.requests[-1][1])

    async def test_different_source_does_not_reuse_partial_prefix(self):
        await self.paused()
        self.artifact['url'] = self.origin + '/other'
        await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertIsNone(self.requests[-1][1])

    async def test_source_failure_advances_to_next_configured_source(self):
        origin = self.origin
        class SimulatedProxyPolicy(Policy):
            def source_url(self, url, source):
                return origin + '/fail' if source['name'] == 'unavailable proxy' else url
        configured = sources({'sources': [{'name': 'unavailable proxy', 'retries': 0},
                                           {'name': 'working source', 'priority': 1, 'retries': 0}]})
        await Downloader(configured, policy=SimulatedProxyPolicy(test_origin=origin)).download(self.artifact, self.path)
        self.assertEqual(self.requests[0][0], '/fail')
        self.assertEqual(self.path.read_bytes(), self.data)

    async def test_disconnect_after_progress_resumes_same_source_instead_of_switching(self):
        self.mode = 'disconnect-once'
        origin = self.origin
        class SourcePolicy(Policy):
            def source_url(self, url, source):
                return origin + ('/file' if source['name'] == 'primary' else '/fallback')
        configured = sources({'sources': [{'name':'primary','retries':0}, {'name':'fallback','priority':1,'retries':0}]})
        await Downloader(configured, policy=SourcePolicy(test_origin=origin)).download(self.artifact,self.path)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertEqual([p for p,_ in self.requests], ['/file','/file'])
        self.assertIsNotNone(self.requests[-1][1], 'same-source retry must resume verified ETag range')

    async def test_repeated_disconnects_never_switch_away_after_progress(self):
        self.mode = 'disconnect'
        origin = self.origin
        class SourcePolicy(Policy):
            def source_url(self, url, source):
                return origin + ('/file' if source['name'] == 'primary' else '/fallback')
        configured = sources({'sources': [{'name':'primary','retries':0}, {'name':'fallback','priority':1,'retries':0}]})
        with self.assertRaises(ValueError):
            await Downloader(configured, policy=SourcePolicy(test_origin=origin)).download(self.artifact,self.path)
        self.assertTrue(self.requests)
        self.assertTrue(all(p=='/file' for p,_ in self.requests), self.requests)
        self.assertGreater(self.path.with_suffix('.zip.part').stat().st_size,0)

    async def test_previous_partial_keeps_its_source_when_source_order_changes(self):
        await self.paused()
        origin = self.origin
        class SourcePolicy(Policy):
            def source_url(self, url, source):
                return origin + ('/file' if source['name'] == 'local' else '/fallback')
        configured = sources({'sources': [{'name':'fallback','retries':0}, {'name':'local','priority':1,'retries':0}]})
        await Downloader(configured,policy=SourcePolicy(test_origin=origin)).download(self.artifact,self.path)
        self.assertEqual(self.requests[-1][0],'/file')
        self.assertIsNotNone(self.requests[-1][1])

    async def test_source_lock_survives_completed_part_and_application_restart(self):
        origin = self.origin
        class SourcePolicy(Policy):
            recovered = False
            def source_url(self, url, source):
                return origin + ('/file' if self.recovered else '/fail') if source['name']=='primary' else origin+'/fallback'
        configured = sources({'sources':[{'name':'primary','retries':0},{'name':'fallback','priority':1,'retries':0}]})
        policy=SourcePolicy(test_origin=origin)
        lock=self.path.parent/'source-lock.json'
        await Downloader(configured,policy=policy,source_lock=lock).download(self.artifact,self.path)
        policy.recovered=True
        self.requests.clear()
        await Downloader(configured,policy=policy,source_lock=lock).download(self.artifact,self.path.parent/'part2.bin')
        self.assertEqual([p for p,_ in self.requests],['/fallback'])

    async def test_complete_legacy_partial_retains_source_for_the_next_part(self):
        self.path.with_suffix('.zip.part').write_bytes(self.data)
        atomic_json(self.path.with_suffix('.zip.state.json'),{'url':self.artifact['url'],
            'etag':self.etag,'sha256':self.artifact['sha256'],'size':self.artifact['size']})
        origin=self.origin
        class SourcePolicy(Policy):
            def source_url(self,url,source):
                return origin+('/file' if source['name']=='local' else '/fallback')
        configured=sources({'sources':[{'name':'fallback','retries':0},{'name':'local','priority':1,'retries':0}]})
        lock=self.path.parent/'source-lock.json'
        await Downloader(configured,policy=SourcePolicy(test_origin=origin),source_lock=lock).download(self.artifact,self.path)
        self.assertTrue(lock.exists(),'completed legacy partial must retain its known source')
        await Downloader(configured,policy=SourcePolicy(test_origin=origin),source_lock=lock).download(self.artifact,self.path.parent/'part2.bin')
        self.assertEqual(self.requests[-1][0],'/file')

    async def test_pause_during_same_source_retry_keeps_partial_without_switching(self):
        self.mode='disconnect'
        stop=Event()
        def progress(value):
            if '同源重试' in value.get('status',''):
                stop.set()
        with self.assertRaises(Paused):
            await Downloader(self.source,policy=self.policy,stop=stop,progress=progress).download(self.artifact,self.path)
        self.assertEqual(len(self.requests),1)
        self.assertGreater(self.path.with_suffix('.zip.part').stat().st_size,0)

    async def test_ignored_range_truncates_instead_of_appending(self):
        await self.paused()
        self.mode = 'ignore'
        await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertEqual(self.path.read_bytes(), self.data)

    async def test_changed_etag_forces_full_download(self):
        await self.paused()
        self.etag = '"changed"'
        await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertEqual(self.path.read_bytes(), self.data)

    async def test_bad_range_rejected_then_clean_retry_works(self):
        await self.paused()
        self.mode = 'bad-range'
        with self.assertRaises(ValueError):
            await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.mode = 'range'
        await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertIsNone(self.requests[-1][1])

    async def test_failure_falls_back_to_next_official_attachment(self):
        self.artifact['url'] = self.origin + '/fail'
        self.artifact['urls'] = [self.origin + '/file']
        await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertEqual(self.requests[0][0], '/fail')

    async def test_corruption_never_yields_verified_destination(self):
        self.mode = 'broken'
        with self.assertRaises(ValueError):
            await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        self.assertFalse(self.path.exists())

    async def test_all_sources_fail_without_affecting_other_work(self):
        self.artifact['url'] = self.origin + '/fail'
        with self.assertRaises(ValueError):
            await Downloader(self.source, policy=self.policy).download(self.artifact, self.path)
        await asyncio.sleep(0)
        self.assertFalse(self.path.exists())
