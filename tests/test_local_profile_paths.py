"""Installation-local profiles must not inherit a previous AppData identity."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]


class LocalProfilePathTests(unittest.TestCase):
    def probe(self, installation, appdata):
        env = dict(os.environ, LOCALAPPDATA=str(appdata))
        script = ('import sys,json; sys.frozen=True; sys.executable=sys.argv[1]; '
                  'from app.paths import DATA_ROOT,VOICE_ROOT; '
                  'print(json.dumps({"data":str(DATA_ROOT),"voice":str(VOICE_ROOT)}))')
        result = subprocess.run([sys.executable, '-B', '-c', script, str(installation / 'TachiTalk.exe')],
                                cwd=PROJECT, env=env, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_frozen_profile_belongs_to_the_executable_directory(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / 'installed'
            install.mkdir()
            result = self.probe(install, root / 'appdata')
            self.assertEqual(Path(result['data']), install.resolve() / 'user_data')

    def test_separate_installs_with_shared_appdata_have_separate_profiles(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = []
            for name in ('first', 'second'):
                installation = root / name
                installation.mkdir()
                results.append(self.probe(installation, root / 'appdata'))
            self.assertNotEqual(results[0]['data'], results[1]['data'])

    def test_old_appdata_voice_selection_is_not_automatically_imported(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / 'new-install'
            install.mkdir()
            legacy = root / 'legacy/services/gpt_sovits/runtime'
            legacy.mkdir(parents=True)
            (legacy / 'python.exe').write_bytes(b'path-only fixture; never executed')
            old_settings = root / 'appdata/TachiTalk/settings'
            old_settings.mkdir(parents=True)
            (old_settings / 'voice_location.json').write_text(
                json.dumps({'installation': str(root / 'legacy')}), encoding='utf-8')
            result = self.probe(install, root / 'appdata')
            self.assertEqual(Path(result['voice']), install.resolve())

    def test_removing_installation_removes_its_profile_for_a_fresh_download(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            install = root / 'installed'
            install.mkdir()
            first = self.probe(install, root / 'appdata')
            profile = Path(first['data'])
            profile.mkdir(parents=True)
            (profile / 'fixture-profile.txt').write_text('old identity', encoding='utf-8')
            self.assertTrue(install.resolve().is_relative_to(root))
            shutil.rmtree(install)
            install.mkdir()
            second = self.probe(install, root / 'appdata')
            self.assertFalse((Path(second['data']) / 'fixture-profile.txt').exists())

    def test_bootstrap_reports_profile_write_failure_without_appdata_fallback(self):
        from app import bootstrap
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'installation/user_data'
            with patch('app.paths.PROJECT_ROOT', root / 'installation'), \
                    patch('app.paths.DATA_ROOT', data), \
                    patch('app.paths.ensure_data_root', side_effect=PermissionError('fixture denied')), \
                    patch.object(sys, 'frozen', True, create=True), \
                    patch('ctypes.windll.user32.MessageBoxW') as message:
                self.assertEqual(bootstrap.main(), 1)
            self.assertIn('无法在程序目录保存本机数据', message.call_args.args[1])
            self.assertIn('fixture denied', message.call_args.args[1])
            self.assertFalse(data.exists())
