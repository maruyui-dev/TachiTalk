"""Native Inno regression: nested UI assets install; user root assets survive."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

PROJECT = Path(__file__).resolve().parents[1]
COMPILER = Path(os.environ.get('TACHITALK_INNO_COMPILER',
    str(PROJECT / 'tools/inno/ISCC.exe')))


@unittest.skipUnless(os.name == 'nt' and COMPILER.is_file(), 'native Windows Inno compiler is required')
class InstallerAssetTests(unittest.TestCase):
    def test_nested_ui_assets_are_installed_and_root_user_assets_preserved(self):
        with TemporaryDirectory(prefix='tachitalk-installer-assets-') as temporary:
            root = Path(temporary)
            release = root / 'release'
            ui_assets = release / 'resources/control_panel/assets'
            ui_assets.mkdir(parents=True)
            names = ('arrow_down.svg', 'arrow_up.svg', 'switch_off.svg', 'switch_on.svg',
                'tachitalk.png', 'tachitalk.ico')
            for name in names:
                (ui_assets / name).write_bytes((PROJECT / 'resources/control_panel/assets' / name).read_bytes())
            (release / 'TachiTalk.exe').write_bytes(b'installer payload fixture - never executed')
            (release / 'assets').mkdir()
            (release / 'assets/portrait.png').write_bytes(b'builtin fixture')
            (release / 'user_data/settings').mkdir(parents=True)
            (release / 'user_data/settings/profile.json').write_bytes(b'private build profile')
            (release / 'user_data/settings/vendor-only.json').write_bytes(b'must not ship')
            install = root / 'installed 用户目录'
            (install / 'assets').mkdir(parents=True)
            (install / 'assets/portrait.png').write_bytes(b'keep user portrait')
            (install / 'user_data/settings').mkdir(parents=True)
            (install / 'user_data/settings/profile.json').write_bytes(b'keep user profile')
            compile_result = subprocess.run([str(COMPILER), '/DReleaseDir=' + str(release),
                '/DMainOnly=1', '/DQAMode=1', '/DTestBuild=1', '/DOutputDirectory=' + str(root / 'setup'),
                str(PROJECT / 'packaging/TachiTalk.iss')], cwd=PROJECT,
                capture_output=True, text=True, errors='replace', timeout=60)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout[-3000:]+compile_result.stderr[-1000:])
            installed = subprocess.run([str(root / 'setup/TachiTalk_main_setup.exe'), '/VERYSILENT',
                '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/NOCLOSEAPPLICATIONS',
                '/NORESTARTAPPLICATIONS', '/DIR=' + str(install)], cwd=PROJECT,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=60)
            self.assertEqual(installed.returncode, 0)
            for name in names:
                with self.subTest(asset=name):
                    target = install / 'resources/control_panel/assets' / name
                    self.assertTrue(target.is_file(), f'安装器遗漏 UI 图标：{name}')
                    self.assertEqual(target.read_bytes(), (ui_assets / name).read_bytes())
            self.assertEqual((install / 'assets/portrait.png').read_bytes(), b'keep user portrait')
            self.assertEqual((install / 'user_data/settings/profile.json').read_bytes(), b'keep user profile')
            self.assertFalse((install / 'user_data/settings/vendor-only.json').exists())
