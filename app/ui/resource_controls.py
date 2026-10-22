"""资源页：真实列表、PNG导入、预览、目录与即时生效的神态映射。"""
from functools import partial
import logging

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmapCache
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGridLayout, QInputDialog, QLabel,
                QLineEdit, QPushButton, QTableWidget, QTableWidgetItem)

from app.core.resources import KINDS
from app.core.expressions import ExpressionStore

LOG = logging.getLogger('tachitalk.resources')


class ResourceControls(QObject):
    def __init__(self, panel, pet, library):
        super().__init__(panel)
        self.panel, self.pet, self.library = panel, pet, library
        self.expressions = ExpressionStore(library.active_expressions, library.base.default)
        self._skin_signatures = None
        self._portrait_signature = None
        self.table = panel.findChild(QTableWidget, 'resourceTable')
        self.search = panel.findChild(QLineEdit, 'resourceSearchEdit')
        self.directory = panel.findChild(QLineEdit, 'resourceDirectoryEdit')
        self.status = panel.findChild(QLabel, 'resourceStatus')
        self.kind = panel.findChild(QComboBox, 'importResourceKind')
        self.pack_combo = panel.findChild(QComboBox, 'portraitPackCombo')
        self.scope = panel.findChild(QComboBox, 'resourceScopeCombo')
        for key, title in KINDS.items():
            self.kind.addItem(title, key)
        self.pack_combo.currentIndexChanged.connect(self.select_pack)
        self.scope.currentIndexChanged.connect(self.scope_changed)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.mapping = {}
        self.mapping_grid = panel.findChild(QGridLayout, 'expressionMappingGrid')
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.preview_selected)
        self.table.cellDoubleClicked.connect(lambda *_: self.set_default())
        self.search.textChanged.connect(self.filter_rows)
        self.directory.editingFinished.connect(self.change_directory)
        for name, callback in (
                ('importResourceButton', self.import_images), ('setDefaultResourceButton', self.set_default),
                ('removeResourceButton', self.remove), ('browseResourceDirectoryButton', self.browse_directory),
                ('importPortraitPackButton', self.import_pack), ('renamePortraitPackButton', self.rename_pack),
                ('removePortraitPackButton', self.remove_pack), ('renameResourceButton', self.rename_image),
                ('replaceResourceButton', self.replace_image),
                ('openResourceFolderButton', self.open_directory)):
            panel.findChild(QPushButton, name).clicked.connect(callback)
        self.expression_combo = panel.findChild(QComboBox, 'expressionCombo')
        self.expression_combo.currentTextChanged.connect(self.preview_expression)
        if pet is not None:
            pet.expression_changed.connect(self.sync_expression)
        self.refresh()
        self.apply()
        if library.warning:
            self.report(library.warning, error=True)

    def report(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet('color: #b56826;' if error else 'color: #42946d;')
        (LOG.warning if error else LOG.info)(text)

    def selected(self):
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            return None
        cell = self.table.item(row, 0)
        return self.library.records.get(cell.data(Qt.ItemDataRole.UserRole)) if cell else None

    def refresh(self, selected_key=None):
        selected_key = selected_key or (self.selected().key if self.selected() else None)
        library = self.library
        item = library.records.get(selected_key)
        if item is not None:
            with QSignalBlocker(self.scope):
                self.scope.setCurrentIndex(0 if item.kind == 'portrait' else 1)
        with QSignalBlocker(self.pack_combo):
            self.pack_combo.clear()
            for key, name in library.packs.items():
                self.pack_combo.addItem(name, key)
            self.pack_combo.setCurrentIndex(self.pack_combo.findData(library.active_id))
        self.panel.findChild(QPushButton, 'removePortraitPackButton').setEnabled(library.active_id != 'default')
        self.sync_choices()
        global_bubbles = self.scope.currentIndex() == 1
        self.panel.findChild(QLabel, 'resourceLibraryCardTitle').setText(
            '全局气泡' if global_bubbles else library.packs[library.active_id] + ' · 立绘')
        self.panel.findChild(QLabel, 'expressionMappingCardTitle').setText('神态映射 · ' + library.packs[library.active_id])
        if (self.kind.currentData() != 'portrait') != global_bubbles:
            with QSignalBlocker(self.kind):
                self.kind.setCurrentIndex(1 if global_bubbles else 0)
        self.directory.setText(str(library.global_resources.directory if global_bubbles else library.directory))
        self.panel.findChild(QLabel, 'resourceDirectoryHint').setText(
            '全局气泡目录：此处更改只影响气泡，切换角色不会更换气泡。' if global_bubbles else
            f'当前角色：{library.packs[library.active_id]}。图片与神态映射独立保存，气泡另行管理。')
        with QSignalBlocker(self.table):
            self.table.setRowCount(0)
            items = [item for item in library.records.values() if (item.kind != 'portrait') == global_bubbles]
            for row, item in enumerate(items):
                self.table.insertRow(row)
                assigned = [name for name in library.expressions if library.expression_key(name) == item.key]
                state = ('默认' if library.expression_key(library.base.default) == item.key else
                         '已映射：' + '、'.join(assigned) if assigned else '可用')
                if item.kind != 'portrait' and library.skin_key(item.kind) == item.key:
                    state = '默认皮肤'
                if item.builtin:
                    state += ' · 内置'
                for column, text in enumerate((item.path.stem, KINDS[item.kind], item.path.name, state)):
                    cell = QTableWidgetItem(text)
                    cell.setData(Qt.ItemDataRole.UserRole, item.key)
                    cell.setToolTip(str(item.path))
                    self.table.setItem(row, column, cell)
                if item.key == selected_key:
                    self.table.setCurrentCell(row, 0)
            if self.table.currentRow() < 0 and self.table.rowCount():
                self.table.setCurrentCell(0, 0)
        portraits = [item for item in library.records.values() if item.kind == 'portrait']
        for expression, combo in self.mapping.items():
            with QSignalBlocker(combo):
                combo.clear()
                combo.addItem('自动匹配（内置／同名／平常）', None)
                for item in portraits:
                    combo.addItem(item.path.name + (' · 内置' if item.builtin else ''), item.key)
                key = library.state['mapping'].get(expression)
                index = combo.findData(key) if isinstance(key, str) else 0
                combo.setCurrentIndex(max(0, index))
        self.filter_rows()

    def scope_changed(self, *_):
        with QSignalBlocker(self.kind):
            self.kind.setCurrentIndex(1 if self.scope.currentIndex() == 1 else 0)
        self.table.setCurrentCell(-1, -1)
        self.refresh()

    def kind_changed(self, *_):
        index = 0 if self.kind.currentData() == 'portrait' else 1
        if index != self.scope.currentIndex():
            with QSignalBlocker(self.scope):
                self.scope.setCurrentIndex(index)
            self.table.setCurrentCell(-1, -1)
            self.refresh()

    def select_pack(self, *_):
        key = self.pack_combo.currentData()
        if key is None or key == self.library.active_id:
            return
        self.table.setCurrentCell(-1, -1)
        self.search.clear()
        if self.perform(lambda: self.library.select_pack(key), '角色立绘包已切换，气泡保持原样；LLM神态已同步'):
            self.preview_expression(self.library.base.default)

    def import_pack(self):
        folder = QFileDialog.getExistingDirectory(self.panel, '导入角色立绘包：选择直接包含PNG的文件夹', '')
        if folder:
            with QSignalBlocker(self.scope):
                self.scope.setCurrentIndex(0)
            self.table.setCurrentCell(-1, -1)
            self.search.clear()
            if self.perform(lambda: self.library.import_pack(folder), '角色包已复制导入并启用，原文件夹保留；气泡保持原样'):
                self.preview_expression(self.library.base.default)

    def rename_pack(self):
        key = self.library.active_id
        name, ok = QInputDialog.getText(self.panel, '重命名立绘包', '角色包名称：', text=self.library.packs[key])
        if ok:
            self.perform(lambda: self.library.rename_pack(key, name.strip()), '立绘包已重命名，图片及气泡引用保留')

    def remove_pack(self):
        self.table.setCurrentCell(-1, -1)
        self.perform(lambda: self.library.remove_pack(self.library.active_id), '角色包已移除并回到默认角色，气泡保持原样')

    def rename_image(self):
        item = self.selected()
        if item:
            name, ok = QInputDialog.getText(self.panel, '重命名图片／神态', '名称（不含.png）：', text=item.path.stem)
            if ok:
                keys = []
                if self.perform(lambda: keys.append(self.library.rename_image(item.key, name.strip())),
                                '图片已重命名，映射及LLM可用神态已同步'):
                    self.refresh(keys[0])

    def replace_image(self):
        item = self.selected()
        if item:
            path, _ = QFileDialog.getOpenFileName(self.panel, '替换导入的图片副本（保留神态名与映射）', '', 'PNG (*.png)')
            if path:
                def update():
                    self.library.replace_image(item.key, path)
                    self.panel.preview_image.source = None
                    self.panel.resource_preview_image.source = None
                    if item.kind != 'portrait':
                        self._skin_signatures = None
                    else:
                        self._portrait_signature = None
                self.perform(update, '图片已替换，神态名与映射保留')

    def sync_choices(self):
        names = self.library.expressions
        if tuple(self.mapping) != names:
            while self.mapping_grid.count():
                widget = self.mapping_grid.takeAt(0).widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
            self.mapping = {}
            for row, expression in enumerate(names):
                caption = QLabel(expression, self.panel)
                caption.setMinimumWidth(70)
                combo = QComboBox(self.panel)
                combo.setObjectName(f'resourceMapping{row}')
                combo.setToolTip('选择后即时应用；LLM可用神态会随实际图片与映射同步更新')
                combo.currentIndexChanged.connect(partial(self.map_expression, expression))
                self.mapping_grid.addWidget(caption, row, 0)
                self.mapping_grid.addWidget(combo, row, 1)
                self.mapping[expression] = combo
        expression = self.pet.character.current_expression if self.pet else self.expression_combo.currentText()
        with QSignalBlocker(self.expression_combo):
            self.expression_combo.clear()
            self.expression_combo.addItems(self.library.active_expressions)
            self.expression_combo.setCurrentText(expression if expression in self.library.active_expressions
                                                 else self.library.base.default)

    def bind_expressions(self, expressions):
        self.expressions = expressions
        self.expressions.update(self.library.active_expressions, self.library.base.default)

    def filter_rows(self, *_):
        query = self.search.text().strip().casefold()
        visible = []
        for row in range(self.table.rowCount()):
            hide = query not in ' '.join(self.table.item(row, col).text() for col in range(4)).casefold()
            self.table.setRowHidden(row, hide)
            if not hide:
                visible.append(row)
        self.panel.findChild(QLabel, 'resourceCountLabel').setText(
            f'{len(visible)} / {self.table.rowCount()} 个资源 · PNG图片')
        if visible and (self.table.currentRow() not in visible):
            self.table.setCurrentCell(visible[0], 0)
        self.preview_selected()

    def preview_selected(self):
        item = self.selected()
        self.panel.findChild(QPushButton, 'setDefaultResourceButton').setEnabled(item is not None)
        remove = self.panel.findChild(QPushButton, 'removeResourceButton')
        remove.setEnabled(item is not None and not item.builtin)
        remove.setToolTip('删除导入的副本，原文件保留；目录中已有的图片只从资源库移除')
        for name in ('renameResourceButton', 'replaceResourceButton'):
            button = self.panel.findChild(QPushButton, name)
            button.setEnabled(item is not None and not item.builtin and item.owned)
            button.setToolTip('仅修改导入的副本；内置图片或外部原图请先导入')
        if item is None:
            self.panel.resource_preview_image.clear()
            self.panel.findChild(QLabel, 'resourcePreviewName').setText('没有匹配的资源')
            self.panel.findChild(QLabel, 'resourcePreviewFile').clear()
            return
        try:
            self.panel.resource_preview_image.set_source(item.path, whole=True)
            self.panel.findChild(QLabel, 'resourcePreviewName').setText(item.path.stem)
            self.panel.findChild(QLabel, 'resourcePreviewFile').setText(f'{item.path.name} · {KINDS[item.kind]}')
        except (OSError, ValueError) as error:
            self.panel.resource_preview_image.clear()
            self.report(str(error), error=True)

    def apply(self):
        catalog = self.library.catalog()
        skins = {color: self.library.records[self.library.skin_key(color)].path for color in ('pink', 'blue')}
        portrait_signature = (self.library.active_id, catalog.default,
                              tuple((name, path, path.stat().st_mtime_ns, path.stat().st_size)
                                    for name, path in catalog.paths.items()))
        if portrait_signature != self._portrait_signature:
            if self.pet is not None:
                self.pet.apply_catalog(catalog)
            self._portrait_signature = portrait_signature
        signature = tuple((color, path, path.stat().st_mtime_ns, path.stat().st_size) for color, path in skins.items())
        if signature != self._skin_signatures:
            QPixmapCache.clear()
            if self.pet is not None:
                self.pet.set_bubble_skins(skins)
            self.panel.bubble_preview.set_skins(skins, force=True)
            self._skin_signatures = signature
        # 立绘成功加载后再发布名称，后台不会先选到尚未能显示的新图片。
        self.expressions.update(self.library.active_expressions, self.library.base.default)
        expression = self.pet.character.current_expression if self.pet else self.expression_combo.currentText()
        self.sync_expression(expression)

    def sync_expression(self, expression):
        with QSignalBlocker(self.expression_combo):
            self.expression_combo.setCurrentText(expression)
        path = self.library.catalog().paths.get(expression)
        if path:
            try:
                self.panel.preview_image.set_source(path)
            except (OSError, ValueError) as error:
                self.report(f'立绘预览不可用：{error}', error=True)

    def preview_expression(self, expression):
        if self.pet:
            self.pet.preview_expression(expression)
        else:
            self.sync_expression(expression)

    def import_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self.panel, '导入PNG资源（复制到资源目录）', '', 'PNG (*.png)')
        keys, errors = [], []
        kind = self.kind.currentData()
        for path in paths:
            try:
                keys.append(self.library.import_png(path, kind))
            except (OSError, ValueError) as error:
                errors.append(str(error))
        if keys:
            self.refresh(keys[-1])
            try:
                self.apply()
            except (OSError, ValueError) as error:
                errors.append(str(error))
        if paths:
            self.report(f'已导入{len(keys)}张。可用人物神态已同步给LLM；也可设为默认或调整映射。' +
                        (' 未导入：' + '；'.join(errors) if errors else ''), error=bool(errors))

    def map_expression(self, expression, _index):
        self.perform(lambda: self.library.set_mapping(expression, self.mapping[expression].currentData()),
                     f'已保存并应用“{expression}”立绘')

    def set_default(self):
        item = self.selected()
        if item:
            if self.perform(lambda: self.library.set_default(item.key), f'{item.path.name} 已设为默认并应用'):
                if item.kind == 'portrait':
                    self.preview_expression(self.library.base.default)

    def remove(self):
        item = self.selected()
        if item:
            self.perform(lambda: self.library.remove(item.key), '已移除资源，相关神态已回退；原文件保留')

    def perform(self, action, message):
        try:
            action()
            self.library.refresh()
            self.apply()
            self.refresh()
            self.report(message)
            return True
        except (OSError, ValueError, KeyError) as error:
            self.refresh()
            self.report(str(error), error=True)
            return False

    def browse_directory(self):
        path = QFileDialog.getExistingDirectory(self.panel, '选择当前分类的资源目录', self.directory.text())
        if path:
            self.directory.setText(path)
            self.change_directory()

    def change_directory(self):
        self.perform(lambda: self.library.change_directory(self.directory.text().strip(), self.scope.currentIndex() == 1),
                     '资源目录已刷新，原目录中的图片保留；请按需设置映射')

    def open_directory(self):
        try:
            directory = self.library.global_resources.directory if self.scope.currentIndex() == 1 else self.library.directory
            directory.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
                raise OSError('无法打开资源目录')
        except OSError as error:
            self.report(str(error), error=True)

