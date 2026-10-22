"""资源导入、持久化和真实立绘应用；所有文件写入临时目录。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import unittest
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QLabel, QLineEdit, QPushButton, QTableWidget
from app.core.resources import ResourceLibrary
from app.ui.pet.expressions import ExpressionCatalog

from app.ui import control_panel
from app.ui.desktop_pet import DesktopPetWindow


class ResourceImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / '新神态.png'
        image = QImage(80, 160, QImage.Format.Format_ARGB32)
        image.fill(QColor('#e05070'))
        self.assertTrue(image.save(str(self.image), 'PNG'))
        self.patches = [patch.object(control_panel, 'RESOURCE_STATE', self.root / 'library.json', create=True),
                        patch.object(control_panel, 'RESOURCE_BUBBLE_DIRECTORY', self.root / 'bubbles', create=True),
                        patch.object(control_panel, 'RESOURCE_DIRECTORY', self.root / 'assets', create=True)]
        for item in self.patches:
            item.start()
        self.pet = DesktopPetWindow()
        # 固定旧测试所需的三张内置图；用户增加其他PNG不应改变故障/回退场景。
        base = ExpressionCatalog(allowed_names=('平常', '疑问', '紧张'))
        from config import REF_MAP
        library = ResourceLibrary(self.root / 'assets', self.root / 'library.json', catalog=base, expressions=REF_MAP)
        self.panel = control_panel.load_window(pet=self.pet, library=library)

    def tearDown(self):
        self.panel.close()
        self.pet.shutdown()
        self.panel.deleteLater()
        self.pet.deleteLater()
        self.app.processEvents()
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def test_import_button_registers_real_png(self):
        with patch.object(QFileDialog, 'getOpenFileNames', return_value=([str(self.image)], 'PNG (*.png)')) as dialog:
            self.panel.findChild(QPushButton, 'importResourceButton').click()
        table = self.panel.findChild(QTableWidget, 'resourceTable')
        filenames = [table.item(row, 2).text() for row in range(table.rowCount())]
        self.assertIn(self.image.name, filenames)
        dialog.assert_called_once()

    def import_image(self, source=None, kind='portrait'):
        controls = self.panel.resource_controls
        key = controls.library.import_png(source or self.image, kind)
        controls.refresh(key)
        controls.apply()
        return key

    def assert_pet_color(self, color='#e05070'):
        self.wait_for_transition()
        pixmap = self.pet.character.ui.petLable.pixmap()
        self.assertEqual(pixmap.toImage().pixelColor(pixmap.width() // 2, pixmap.height() // 2), QColor(color))

    def wait_for_transition(self):
        # Qt首帧会排在布局事件后；230ms墙钟时间不保证200ms动画已完成。
        # 等实际完成后仍严格检查神态和像素，立绘业务代码及动画时长不变。
        deadline = perf_counter() + 1
        while self.pet.character._switching and perf_counter() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.pet.character._switching, '立绘过渡动画未正常结束')

    def test_set_default_updates_real_portrait_and_restores_after_restart(self):
        key = self.import_image()
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').click()
        self.assert_pet_color()
        controls = self.panel.resource_controls
        self.assertEqual(controls.library.expression_key('平常'), key)
        restored = ResourceLibrary(self.root / 'unused', self.root / 'library.json', expressions=controls.library.expressions)
        # Windows的TEMP可能使用8.3短路径；比较解析后的实际路径。
        self.assertEqual(restored.catalog().paths['平常'], (self.root / 'assets' / self.image.name).resolve())
        self.pet.apply_catalog(restored.catalog())
        self.assert_pet_color()
        self.assertTrue(self.image.exists(), '导入原文件必须保留')
        self.assertEqual(self.pet.display_percent, 50)

    def test_mapping_reaches_dialogue_expression_and_return_to_default(self):
        key = self.import_image()
        controls = self.panel.resource_controls
        combo = controls.mapping['开心']
        combo.setCurrentIndex(combo.findData(key))
        self.pet.play_expression(91, '开心')
        self.assert_pet_color()
        self.assertEqual(self.pet.character.current_expression, '开心')
        preview = self.panel.preview_image.full_image.toImage()
        self.assertEqual(preview.pixelColor(2, 2), QColor('#e05070'))
        self.pet.finish_expression(91)
        self.wait_for_transition()
        self.assertEqual(self.pet.character.current_expression, '平常')
        self.assertNotEqual(self.pet.character._current_pixmap.toImage().pixelColor(2, 2), QColor('#e05070'))

    def test_removing_active_resource_restores_builtin_without_removing_source(self):
        key = self.import_image()
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').click()
        self.assert_pet_color()
        copy_path = self.panel.resource_controls.library.records[key].path
        self.panel.findChild(QPushButton, 'removeResourceButton').click()
        self.assertTrue(self.image.exists())
        self.assertFalse(copy_path.exists())
        self.assertNotIn(key, self.panel.resource_controls.library.records)
        self.assertEqual(self.pet.character.catalog.paths['平常'], self.panel.resource_controls.library.base.paths['平常'])
        self.assertFalse(self.pet.character.ui.petLable.pixmap().isNull())

    def test_import_duplicate_and_invalid_png(self):
        library = self.panel.resource_controls.library
        one = library.import_png(self.image)
        two = library.import_png(self.image)
        self.assertNotEqual(one, two)
        self.assertEqual(library.records[one].path.read_bytes(), self.image.read_bytes())
        self.assertEqual(library.records[two].path.read_bytes(), self.image.read_bytes())
        invalid = self.root / 'fake.png'
        invalid.write_text('not a png', encoding='utf-8')
        with self.assertRaises(ValueError):
            library.import_png(invalid)
        self.assertFalse((library.directory / invalid.name).exists())
        with self.assertRaises(ValueError):
            library.remove('builtin:portrait:平常')

    def test_search_preview_and_manual_expression_control(self):
        self.import_image()
        self.panel.findChild(QLineEdit, 'resourceSearchEdit').setText('新神态')
        table = self.panel.findChild(QTableWidget, 'resourceTable')
        shown = [r for r in range(table.rowCount()) if not table.isRowHidden(r)]
        self.assertEqual(len(shown), 1)
        preview = self.panel.resource_preview_image.full_image.toImage()
        self.assertEqual(preview.size(), QImage(str(self.image)).size(), '资源预览必须使用完整图片')
        self.panel.findChild(QLineEdit, 'resourceSearchEdit').setText('没有这个资源')
        self.panel.resource_preview_image.fit()
        self.assertTrue(self.panel.findChild(QLabel, 'resourceAvatarLabel').pixmap().isNull())
        self.assertFalse(self.panel.findChild(QPushButton, 'setDefaultResourceButton').isEnabled())
        self.panel.findChild(QComboBox, 'expressionCombo').setCurrentText('疑问')
        self.wait_for_transition()
        self.assertEqual(self.pet.character.current_expression, '疑问')

    def test_external_directory_images_are_never_deleted(self):
        library = self.panel.resource_controls.library
        library.change_directory(self.root)
        key = f'file:{self.image.name}'
        self.assertIn(key, library.records)
        library.set_mapping('平常', key)
        library.remove(key)
        self.assertTrue(self.image.exists())
        library.refresh()
        self.assertNotIn(key, library.records)
        self.assertEqual(library.catalog().paths['平常'], library.base.paths['平常'])

    def test_corrupt_saved_image_and_path_escape_fall_back(self):
        import json
        library = self.panel.resource_controls.library
        key = library.import_png(self.image)
        library.set_mapping('平常', key)
        library.records[key].path.write_bytes(b'broken png')
        data = json.loads(library.state_file.read_text(encoding='utf-8'))
        data['mapping']['开心'] = 'file:../outside.png'
        library.state_file.write_text(json.dumps(data), encoding='utf-8')
        restored = ResourceLibrary(library.directory, library.state_file, catalog=library.base, expressions=library.expressions)
        self.assertEqual(restored.catalog().paths['平常'], restored.base.paths['平常'])
        self.assertEqual(restored.catalog().paths['开心'], restored.base.paths['平常'])
        self.assertTrue(restored.warning)

    def test_switching_default_during_fade_does_not_restore_stale_image(self):
        self.pet.preview_expression('疑问')
        self.import_image()
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').click()
        self.assert_pet_color()
        self.assertEqual(self.pet.character.current_expression, '平常')

    def test_failed_save_rolls_back_import_and_keeps_original(self):
        library = self.panel.resource_controls.library
        # 包管理层把保存委托给当前包的资源库；故障仍注入实际保存位置。
        with patch.object(library.active, '_commit', side_effect=OSError('只读目录')):
            with self.assertRaises(OSError):
                library.import_png(self.image)
        self.assertTrue(self.image.exists())
        self.assertFalse((library.directory / self.image.name).exists())

    def test_skin_updates_existing_and_future_bubbles_and_preview(self):
        self.pet.add_message('pink', '已有气泡')
        QTest.qWait(250)
        key = self.import_image(kind='pink')
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').click()
        card = self.pet.bubbles[-1]
        image = card.background_label.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2), QColor('#e05070'))
        self.pet.add_message('pink', '新的气泡')
        QTest.qWait(250)
        image = self.pet.bubbles[-1].background_label.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2), QColor('#e05070'))
        self.assertEqual(self.panel.bubble_preview._skins['pink'], self.panel.resource_controls.library.records[key].path)
        self.assertEqual(self.panel.resource_controls.library.skin_key('pink'), key)

    def test_bad_optional_metadata_does_not_crash_resource_scan(self):
        import json
        library = self.panel.resource_controls.library
        key = library.import_png(self.image)
        data = json.loads(library.state_file.read_text(encoding='utf-8'))
        data['files'][self.image.name]['kind'] = ['invalid type']
        library.state_file.write_text(json.dumps(data), encoding='utf-8')
        restored = ResourceLibrary(library.directory, library.state_file)
        self.assertEqual(restored.records[key].kind, 'portrait')

    def test_new_portrait_name_becomes_a_real_expression(self):
        from shutil import copyfile
        source = self.root / '害羞.png'
        copyfile(self.image, source)
        self.import_image(source)
        self.assertIn('害羞', self.panel.resource_controls.library.catalog().names)
        self.pet.play_expression(92, '害羞')
        self.assert_pet_color()
        self.assertEqual(self.pet.character.current_expression, '害羞')

    def test_resource_changes_publish_only_real_expressions_and_remove_stale_names(self):
        from app.core.expressions import ExpressionStore
        from shutil import copyfile
        controls = self.panel.resource_controls
        store = ExpressionStore()
        controls.bind_expressions(store)
        self.assertIn('平常', store.snapshot().names)
        self.assertNotIn('开心', store.snapshot().names, '未配图片的TTS情绪不能作为实际立绘宣传给LLM')
        source = self.root / '害羞.png'
        copyfile(self.image, source)
        key = self.import_image(source)
        before = store.snapshot()
        self.assertIn('害羞', before.names)
        self.assertIn('害羞', controls.mapping)
        controls.mapping['开心'].setCurrentIndex(controls.mapping['开心'].findData(key))
        self.assertIn('开心', store.snapshot().names)
        controls.library.remove(key)
        controls.refresh()
        controls.apply()
        self.assertNotIn('害羞', store.snapshot().names)
        self.assertNotIn('开心', store.snapshot().names)
        self.assertNotIn('害羞', controls.mapping)
        self.assertIn('害羞', before.names, '已经用于请求的快照不应被后续修改污染')
        restored = ResourceLibrary(controls.library.directory, controls.library.state_file,
                                   expressions=controls.library._base_expressions)
        self.assertNotIn('害羞', restored.active_expressions)

    def test_skin_names_never_enter_llm_choices(self):
        self.import_image(kind='pink')
        self.assertNotIn('新神态', self.panel.resource_controls.expressions.snapshot().names)

    def test_switching_directory_rebuilds_live_expression_choices(self):
        from shutil import copyfile
        controls = self.panel.resource_controls
        alternate = self.root / 'alternate'
        alternate.mkdir()
        copyfile(self.image, alternate / '害羞.png')
        controls.directory.setText(str(alternate))
        controls.change_directory()
        self.assertIn('害羞', controls.expressions.snapshot().names)
        self.assertIn('害羞', controls.mapping)
        self.assertEqual(self.pet.character.catalog.paths['害羞'], (alternate / '害羞.png').resolve())
        controls.directory.setText(str(self.root))
        controls.change_directory()
        self.assertNotIn('害羞', controls.expressions.snapshot().names)

    def test_resource_ui_exposes_portrait_packages_and_global_bubbles(self):
        packages = self.panel.findChild(QComboBox, 'portraitPackCombo')
        self.assertIsNotNone(packages, '资源页应提供角色立绘包选择，而不是混放全部角色')
        self.assertEqual(packages.currentText(), '茉子')
        scope = self.panel.findChild(QComboBox, 'resourceScopeCombo')
        self.assertEqual([scope.itemText(i) for i in range(scope.count())], ['当前角色立绘', '全局气泡'])

    def make_pack(self, name, color, expressions=('平常', '害羞')):
        folder = self.root / 'source_packs' / name
        folder.mkdir(parents=True)
        for expression in expressions:
            image = QImage(80, 160, QImage.Format.Format_ARGB32)
            image.fill(QColor(color))
            self.assertTrue(image.save(str(folder / (expression + '.png')), 'PNG'))
        return folder

    def import_pack_ui(self, folder):
        with patch.object(QFileDialog, 'getExistingDirectory', return_value=str(folder)):
            self.panel.findChild(QPushButton, 'importPortraitPackButton').click()
        self.assertEqual(self.panel.findChild(QComboBox, 'portraitPackCombo').currentText(), folder.name)
        return self.panel.resource_controls.library.active_id

    def test_switching_packages_isolates_same_named_portraits_and_keeps_global_bubbles(self):
        controls = self.panel.resource_controls
        self.import_image(kind='pink')
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').click()
        self.pet.add_message('pink', '原气泡保留')
        self.wait_for_transition()
        skins = dict(self.pet.bubble_skins)
        card = self.pet.bubbles[-1]
        style = card.background_label.styleSheet()
        a = self.import_pack_ui(self.make_pack('亚托利', '#d04050'))
        self.assert_pet_color('#d04050')
        b = self.import_pack_ui(self.make_pack('丛雨', '#4080d0', ('平常', '生气')))
        self.assert_pet_color('#4080d0')
        self.assertNotIn('害羞', controls.expressions.snapshot().names)
        self.assertIn('生气', controls.expressions.snapshot().names)
        with patch.object(self.pet, 'set_bubble_skins', wraps=self.pet.set_bubble_skins) as change_skin:
            combo = self.panel.findChild(QComboBox, 'portraitPackCombo')
            combo.setCurrentIndex(combo.findData(a))
            change_skin.assert_not_called()
        self.assert_pet_color('#d04050')
        self.assertIn('害羞', controls.expressions.snapshot().names)
        self.assertNotIn('生气', controls.expressions.snapshot().names)
        self.assertEqual(self.pet.bubble_skins, skins)
        self.assertIs(self.pet.bubbles[-1], card)
        self.assertEqual(card.text, '原气泡保留')
        self.assertEqual(card.background_label.styleSheet(), style)
        self.assertNotEqual(a, b)

    def test_package_mapping_rename_and_selection_survive_restart(self):
        from app.core.portrait_packs import PackResources
        controls = self.panel.resource_controls
        a = self.import_pack_ui(self.make_pack('亚托利', '#d04050'))
        controls.mapping['开心'].setCurrentIndex(controls.mapping['开心'].findData('file:害羞.png'))
        self.import_pack_ui(self.make_pack('丛雨', '#4080d0', ('平常', '生气')))
        self.assertNotIn('开心', controls.expressions.snapshot().names)
        controls.library.rename_pack(a, '亚托利日常')
        restored = PackResources(ResourceLibrary(self.root / 'assets', self.root / 'library.json',
                                                 expressions=controls.library._base_expressions))
        self.assertEqual(restored.packs[a], '亚托利日常')
        self.assertEqual(restored.packs[restored.active_id], '丛雨')
        restored.select_pack(a)
        self.assertEqual(restored.state['mapping']['开心'], 'file:害羞.png')
        self.assertIn('开心', restored.active_expressions)
        self.assertNotIn('生气', restored.active_expressions)

    def test_remove_active_package_falls_back_and_preserves_source_and_global_skin(self):
        controls = self.panel.resource_controls
        key = self.import_image(kind='pink')
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').click()
        skin = controls.library.records[key].path
        folder = self.make_pack('亚托利', '#d04050')
        pack = self.import_pack_ui(folder)
        managed = controls.library.directory
        self.panel.findChild(QPushButton, 'removePortraitPackButton').click()
        self.assertEqual(controls.library.active_id, 'default')
        self.assertNotIn(pack, controls.library.packs)
        self.assertTrue(all((folder / name).is_file() for name in ('平常.png', '害羞.png')))
        self.assertFalse(managed.exists())
        self.assertTrue(skin.is_file())
        self.assertEqual(controls.library.skin_key('pink'), key)

    def test_pack_without_normal_uses_own_image_and_rejects_removing_last_image(self):
        controls = self.panel.resource_controls
        self.import_pack_ui(self.make_pack('亚托利', '#d04050', ('微笑',)))
        self.assert_pet_color('#d04050')
        self.assertEqual(controls.library.catalog().paths['平常'], controls.library.directory / '微笑.png')
        with self.assertRaises(ValueError):
            controls.library.remove('file:微笑.png')
        self.assert_pet_color('#d04050')

    def test_portrait_rename_and_replacement_update_live_image_and_llm(self):
        from PySide6.QtWidgets import QInputDialog
        controls = self.panel.resource_controls
        self.import_pack_ui(self.make_pack('亚托利', '#d04050'))
        controls.refresh('file:害羞.png')
        with patch.object(QInputDialog, 'getText', return_value=('羞涩', True)):
            self.panel.findChild(QPushButton, 'renameResourceButton').click()
        self.assertIn('羞涩', controls.expressions.snapshot().names)
        self.assertNotIn('害羞', controls.expressions.snapshot().names)
        self.assertTrue((controls.library.directory / '羞涩.png').is_file())
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(self.image), 'PNG (*.png)')):
            self.panel.findChild(QPushButton, 'replaceResourceButton').click()
        self.pet.preview_expression('羞涩')
        self.assert_pet_color()
        self.assertTrue(self.image.is_file())
        self.assertIn('羞涩', controls.expressions.snapshot().names)

    def test_global_skin_replace_is_visible_without_changing_current_portrait(self):
        controls = self.panel.resource_controls
        key = self.import_image(kind='pink')
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').click()
        self.import_pack_ui(self.make_pack('亚托利', '#d04050'))
        self.pet.add_message('pink', '气泡')
        self.wait_for_transition()
        replacement = self.root / '新气泡.png'
        image = QImage(80, 160, QImage.Format.Format_ARGB32)
        image.fill(QColor('#40d090'))
        self.assertTrue(image.save(str(replacement), 'PNG'))
        controls.refresh(key)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(replacement), 'PNG (*.png)')):
            self.panel.findChild(QPushButton, 'replaceResourceButton').click()
        self.assert_pet_color('#d04050')
        rendered = self.pet.bubbles[-1].background_label.grab().toImage()
        self.assertEqual(rendered.pixelColor(rendered.width() // 2, rendered.height() // 2), QColor('#40d090'))
        self.assertEqual(controls.library.packs[controls.library.active_id], '亚托利')

    def test_failed_pack_import_keeps_selection_and_does_not_leave_copies(self):
        controls = self.panel.resource_controls
        folder = self.make_pack('亚托利', '#d04050')
        with patch.object(controls.library, '_commit_manifest', side_effect=OSError('保存失败')):
            with self.assertRaises(OSError):
                controls.library.import_pack(folder)
        self.assertEqual(controls.library.active_id, 'default')
        self.assertEqual(list(controls.library.pack_root.iterdir()), [])
        self.assertTrue(all((folder / name).is_file() for name in ('平常.png', '害羞.png')))

    def test_old_flat_configuration_migrates_without_rewriting_originals_or_skin(self):
        from app.core.portrait_packs import PackResources
        original = ResourceLibrary(self.root / 'legacy_assets', self.root / 'legacy.json')
        portrait = original.import_png(self.image)
        original.set_default(portrait)
        skin = original.import_png(self.image, 'pink')
        original.set_default(skin)
        before = original.state_file.read_bytes()
        skin_path = original.records[skin].path
        packs = PackResources(ResourceLibrary(self.root / 'ignored', original.state_file))
        self.assertEqual(packs.catalog().paths['平常'], original.records[portrait].path)
        self.assertEqual(packs.records[packs.skin_key('pink')].path, skin_path)
        self.assertEqual(packs.packs, {'default': '茉子'})
        self.assertEqual(original.state_file.read_bytes(), before)
        packs.import_pack(self.make_pack('亚托利', '#d04050'))
        self.assertEqual(packs.records[packs.skin_key('pink')].path, skin_path)
        self.assertTrue(original.records[portrait].path.is_file())
        self.assertTrue(skin_path.is_file())
        self.assertEqual(original.state_file.read_bytes(), before)

    def test_removing_package_keeps_unmanaged_files_and_rejects_escaping_directory(self):
        controls = self.panel.resource_controls
        folder = self.make_pack('亚托利', '#d04050')
        key = self.import_pack_ui(folder)
        managed = controls.library.directory
        personal = managed / '个人文件.txt'
        personal.write_text('保留', encoding='utf-8')
        entry = dict(controls.library.manifest['packs'][key])
        entry['directory'] = str(folder)
        with self.assertRaises(ValueError):
            controls.library._managed_directory(key, entry)
        controls.library.remove_pack(key)
        self.assertEqual(personal.read_text(encoding='utf-8'), '保留')
        self.assertTrue(all((folder / name).is_file() for name in ('平常.png', '害羞.png')))

    def test_default_portrait_directory_change_cannot_change_global_bubble_directory(self):
        from app.core.portrait_packs import PackResources
        controls = self.panel.resource_controls
        key = self.import_image(kind='pink')
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').click()
        skin = controls.library.records[key].path
        portrait_folder = self.make_pack('单独立绘目录', '#d04050')
        controls.library.change_directory(portrait_folder)
        controls.apply()
        self.assertEqual(controls.library.records[controls.library.skin_key('pink')].path, skin)
        restored = PackResources(ResourceLibrary(self.root / 'assets', self.root / 'library.json'))
        self.assertEqual(restored.directory, portrait_folder.resolve())
        self.assertEqual(restored.records[restored.skin_key('pink')].path, skin)
