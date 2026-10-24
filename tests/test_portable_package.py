from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.package_portable import files, split_archive, sha256, runtime_libraries, MSVC_LIBRARIES, release_assets, entries


class PortablePackageTests(unittest.TestCase):
    def test_complete_portable_has_unique_docs_with_new_and_legacy_clients(self):
        for client_has_docs in (False, True):
            with self.subTest(client_has_docs=client_has_docs), TemporaryDirectory() as directory:
                root = Path(directory)
                client = root / 'dist/TachiTalk'
                client.mkdir(parents=True)
                (client / 'TachiTalk.exe').write_bytes(b'fixture')
                for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
                    (root / name).write_bytes(b'project documentation')
                    if client_has_docs:
                        (client / name).write_bytes(b'project documentation')
                voice = []
                for name in ('services/gpt_sovits/runtime/python.exe', 'assets/audio/tts_reference/base.wav'):
                    path = client / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'legacy client may already contain voice files')
                    voice.append((path, Path(name)))
                with patch('scripts.component_release.voice_entries', return_value=voice):
                    paths = [path.as_posix() for _, path in entries(root)]
                self.assertEqual(len(paths), len(set(paths)), '完整ZIP不能有同名的重复文件')
                for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
                    self.assertEqual(paths.count('TachiTalk/' + name), 1)

    def test_merge_script_uses_a_github_safe_ascii_filename(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = root / 'services/gpt_sovits'
            service.mkdir(parents=True)
            (service / 'distribution.json').write_text('{}', encoding='utf-8')
            archive = root / 'TachiTalk.zip'
            archive.write_bytes(b'archive-fixture')
            release = root / 'release'
            release_assets(root, archive, release, 1)
            self.assertTrue((release / 'Merge-TachiTalk.cmd').is_file())

    def test_missing_inference_msvc_libraries_are_supplied_without_duplicate_entries(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / 'dist/TachiTalk/_internal/PySide6'
            client.mkdir(parents=True)
            for name in MSVC_LIBRARIES:
                (client / name).write_bytes(b'redistributable')
            runtime = root / 'services/gpt_sovits/runtime'
            runtime.mkdir(parents=True)
            (runtime / MSVC_LIBRARIES[0]).write_bytes(b'already bundled')
            self.assertEqual({name.name for _, name in runtime_libraries(root)}, set(MSVC_LIBRARIES[1:]))
            (client / MSVC_LIBRARIES[1]).unlink()
            with self.assertRaises(ValueError):
                list(runtime_libraries(root))

    def test_user_state_and_cache_are_excluded_but_runtime_sources_are_kept(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('runtime/python.exe', 'runtime/package.py', 'runtime/package.pyc',
                         'scratch/key.txt', '_qt_runtime_tmp/last_session.dat',
                         'user_data/settings/voice-component.json', 'user_data/resources/resource_library.json',
                         'runtime/__pycache__/module.pyc', 'runtime/.env', 'runtime/.env.secret', 'runtime/client.log'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'test')
            names = {relative.as_posix() for _, relative in files(root)}
            self.assertEqual(names, {'runtime/python.exe', 'runtime/package.py', 'runtime/package.pyc'})

    def test_private_profile_directory_is_excluded_regardless_of_windows_case(self):
        with TemporaryDirectory() as directory:
            for index, name in enumerate(('USER_DATA', 'User_Data', 'user_data', 'TEMP', 'Temp', 'temp')):
                root = Path(directory) / str(index)
                private = root / name / 'settings' / 'profile.json'
                private.parent.mkdir(parents=True)
                private.write_bytes(b'private fixture')
                (root / 'client.txt').write_bytes(b'public fixture')
                with self.subTest(name=name):
                    self.assertEqual({p.as_posix() for _, p in files(root)}, {'client.txt'})

    def test_split_rejoins_exact_bytes_and_does_not_overwrite_existing_part(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'TachiTalk.zip'
            archive.write_bytes(bytes(range(256)) * 31)
            parts = split_archive(archive, root / 'parts', part_bytes=1000)
            self.assertTrue(all(p.stat().st_size <= 1000 for p in parts))
            merged = root / 'merged.zip'
            merged.write_bytes(b''.join(p.read_bytes() for p in parts))
            self.assertEqual(sha256(merged), sha256(archive))
            with self.assertRaises(FileExistsError):
                split_archive(archive, root / 'parts', part_bytes=1000)
