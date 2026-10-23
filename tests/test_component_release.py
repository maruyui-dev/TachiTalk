from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from scripts.component_release import create_package, inventory, main_entries


class ComponentReleaseTests(unittest.TestCase):
    def test_main_delta_contains_only_changed_files_and_explicit_deletions(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / 'client'
            client.mkdir()
            (client / 'TachiTalk.exe').write_bytes(b'old')
            (client / 'README.md').write_bytes(b'old notes')
            (client / 'LICENSE').write_bytes(b'unchanged')
            voice = client / 'services/gpt_sovits/runtime/python.exe'
            voice.parent.mkdir(parents=True)
            voice.write_bytes(b'not part of main updates')
            base = inventory(main_entries(client))
            (client / 'README.md').unlink()
            (client / 'TachiTalk.exe').write_bytes(b'new')
            payload = create_package(main_entries(client), root / 'patch', 'main', '1.3.1', '1.3.0', base_files=base, part_bytes=100)
            self.assertEqual([r['path'] for r in payload['files']], ['TachiTalk.exe'])
            self.assertEqual(payload['delete'], ['README.md'])
            with zipfile.ZipFile(root / 'patch/main-1.3.1.zip') as archive:
                self.assertEqual(archive.namelist(), ['TachiTalk.exe'])
            combined = b''.join((root / 'patch' / part['name']).read_bytes() for part in payload['parts'])
            self.assertEqual(combined, (root / 'patch/main-1.3.1.zip').read_bytes())
