"""项目自包含：运行模块、立绘、气泡和参考音频均由当前项目提供。"""
import inspect
from pathlib import Path
import unittest

from config import REF_MAP
from app.core.resources import ExpressionCatalog
from app.ui.desktop_pet import DesktopPetWindow
from app.ui.bubble_display import ScaledBubbleCard
from app.core.resources import ResourceLibrary
from app.core.portrait_packs import PackResources
from app.paths import ASSET_DIR, BUBBLE_DIR, TTS_SERVICE_DIR, PROJECT_ROOT, DATA_ROOT
from scripts.start_tts import service_command, service_environment
from tempfile import TemporaryDirectory
import os


ROOT = Path(__file__).resolve().parents[1]


class ProjectLayoutTests(unittest.TestCase):
    def test_portrait_runtime_code_is_inside_this_project(self):
        for cls in (ExpressionCatalog, DesktopPetWindow.__bases__[0], ScaledBubbleCard.__bases__[0]):
            with self.subTest(module=cls.__module__):
                path = Path(inspect.getfile(cls)).resolve()
                self.assertTrue(path.is_relative_to(ROOT), f'运行代码仍来自项目外：{path}')

    def test_builtin_portraits_and_references_are_inside_this_project(self):
        for path in ExpressionCatalog().paths.values():
            self.assertTrue(path.resolve().is_relative_to(ROOT), f'立绘仍来自项目外：{path}')
            self.assertTrue(path.is_file())
        for name, (filename, _) in REF_MAP.items():
            path = Path(filename).resolve()
            with self.subTest(reference=name):
                self.assertTrue(path.is_relative_to(ROOT), f'参考音频仍来自项目外：{path}')
                self.assertTrue(path.is_file())

    def test_builtin_resources_are_not_duplicated_in_their_own_folder(self):
        with TemporaryDirectory() as folder:
            library = ResourceLibrary(ASSET_DIR, Path(folder) / 'library.json')
            paths = [record.path.resolve() for record in library.records.values()]
            self.assertEqual(len(paths), len(set(paths)))
            self.assertEqual(len(library.records), len(library.base.paths) + 2)
            packs = PackResources(library, bubble_directory=BUBBLE_DIR)
            self.assertEqual(packs.global_resources.directory, BUBBLE_DIR)
            self.assertTrue(all(record.kind != 'portrait'
                                for record in packs.global_resources.records.values()))

    def test_importing_an_existing_builtin_reuses_its_registered_key(self):
        with TemporaryDirectory() as folder:
            library = ResourceLibrary(ASSET_DIR, Path(folder) / 'library.json')
            key = library.import_png(ASSET_DIR / '平常.png')
            self.assertEqual(key, 'builtin:portrait:平常')
            self.assertIn(key, library.records)

    def test_tts_launcher_uses_only_project_runtime_and_process_environment(self):
        command = service_command(port=19880)
        self.assertEqual(Path(command[0]), TTS_SERVICE_DIR / 'runtime/python.exe')
        self.assertEqual(Path(command[3]), PROJECT_ROOT / 'scripts/tts_service_entry.py')
        self.assertEqual(Path(command[command.index('--state-dir') + 1]), DATA_ROOT / 'tts')
        self.assertIn('19880', command)
        original_path = os.environ.get('PATH')
        env = service_environment()
        self.assertEqual(os.environ.get('PATH'), original_path)
        self.assertTrue(env['PATH'].startswith(str(TTS_SERVICE_DIR / 'runtime') + os.pathsep))
