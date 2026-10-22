"""角色包目录与选择清单；每包独立映射，全局气泡由独立资源库持有。"""
from copy import deepcopy
from dataclasses import replace
import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import QFile

from app.core.expressions import valid_expression_name
from app.core.resources import ResourceLibrary, check_png, save_resource_json

LOG = logging.getLogger('tachitalk.resources')


class PackResources:
    MAX_PACKS = 32

    def __init__(self, original, bubble_directory=None):
        self.original = original
        self.base = original.base
        self._base_expressions = original._base_expressions
        self.manifest_file = original.state_file.with_stem(original.state_file.stem + '_packs')
        self.pack_root = self.manifest_file.parent / 'portrait_packs'
        bubble_file = original.state_file.with_stem(original.state_file.stem + '_bubbles')
        self.global_resources = ResourceLibrary(bubble_directory or original.directory, bubble_file, catalog=self.base,
                                                 expressions=self._base_expressions, include_builtin=False)
        if not bubble_file.exists():
            # 原来的平铺配置只读迁移；第一次修改时再分别落盘，原图片不移动。
            legacy_skins = any(item.kind != 'portrait' and not item.builtin for item in original.records.values())
            if bubble_directory is None or legacy_skins:
                self.global_resources.state = deepcopy(original.state)
            else:
                self.global_resources.state['skins'] = deepcopy(original.state['skins'])
            self.global_resources.state['mapping'] = {}
        self.manifest = {'active': 'default', 'packs': {'default': {'name': '茉子'}}}
        self._warning = ''
        self._loaded_libraries = {}  # 全局配置载入后的包设置；数量受MAX_PACKS约束。
        if self.manifest_file.exists():
            try:
                if self.manifest_file.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError('立绘包清单过大')
                data = json.loads(self.manifest_file.read_text(encoding='utf-8'))
                packs = data['packs']
                if not isinstance(packs, dict) or 'default' not in packs or len(packs) > self.MAX_PACKS:
                    raise ValueError('立绘包清单格式错误')
                for key, entry in packs.items():
                    if not isinstance(entry, dict) or not valid_expression_name(entry.get('name')):
                        raise ValueError('立绘包名称无效')
                    if key != 'default':
                        if UUID(key).hex != key:
                            raise ValueError('立绘包编号无效')
                        self._managed_directory(key, entry)
                        if not isinstance(entry.get('files', []), list) or any(
                                not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name
                                or not name.lower().endswith('.png') for name in entry.get('files', [])):
                            raise ValueError('立绘包文件清单无效')
                if data.get('active') not in packs:
                    raise ValueError('选中的立绘包不存在')
                self.manifest = data
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                self._warning = f'立绘包清单无法读取，已保留现有资源并回到默认角色：{error}'
                LOG.warning(self._warning)
        self.active = original
        try:
            self.active = self._load(self.manifest['active'])
        except (OSError, ValueError) as error:
            self.manifest['active'] = 'default'
            self._warning = f'选中立绘包不可用，已回到默认角色：{error}'
            LOG.warning(self._warning)
        self.refresh()

    @property
    def packs(self):
        return {key: entry['name'] for key, entry in self.manifest['packs'].items()}

    @property
    def active_id(self):
        return self.manifest['active']

    @property
    def directory(self):
        return self.active.directory

    @property
    def state(self):
        return self.active.state

    @property
    def state_file(self):
        return self.active.state_file

    @property
    def warning(self):
        return self._warning or self.active.warning or self.global_resources.warning

    @property
    def expressions(self):
        return self.active.expressions

    @property
    def active_expressions(self):
        return self.active.active_expressions

    @property
    def records(self):
        portraits = {key: item for key, item in self.active.records.items() if item.kind == 'portrait'}
        bubbles = {f'global:{key}': replace(item, key=f'global:{key}')
                   for key, item in self.global_resources.records.items() if item.kind != 'portrait'}
        return portraits | bubbles

    def _managed_directory(self, key, entry):
        expected = self.pack_root.resolve() / key
        directory = Path(entry['directory'])
        if (directory.resolve() != expected or directory.is_symlink() or directory.is_junction()
                or self.pack_root.is_symlink() or self.pack_root.is_junction()):
            raise ValueError('立绘包目录不在本项目受管目录内')
        return directory

    def _load(self, key):
        if key == 'default':
            return self.original
        if key in self._loaded_libraries:
            return self._loaded_libraries[key]
        directory = self._managed_directory(key, self.manifest['packs'][key])
        if not directory.is_dir():
            raise ValueError('立绘包目录已丢失')
        library = ResourceLibrary(directory, directory / '.resources.json', catalog=self.base,
                                  expressions=self._base_expressions, include_builtin=False)
        library.catalog()  # 无图时拒绝切包，保留当前角色。
        return library

    def _commit_manifest(self, data):
        # 先固化独立气泡配置，再允许默认角色更换目录；重启后也不会串包。
        if not self.global_resources.state_file.exists():
            self.global_resources.directory.mkdir(parents=True, exist_ok=True)
            self.global_resources.save()
        save_resource_json(self.manifest_file, data)
        self.manifest = data

    def select_pack(self, key):
        if key not in self.manifest['packs']:
            raise ValueError('立绘包不存在')
        candidate = self._load(key)
        candidate.catalog()
        data = deepcopy(self.manifest)
        data['active'] = key
        self._commit_manifest(data)
        self.active = candidate
        self.refresh()

    def import_pack(self, source, name=None):
        source = Path(source).resolve()
        if not source.is_dir():
            raise ValueError('请选择直接包含PNG立绘的文件夹')
        if len(self.packs) >= self.MAX_PACKS:
            raise ValueError(f'最多管理{self.MAX_PACKS}个立绘包')
        files = []
        total = 0
        for path in source.iterdir():
            if path.suffix.lower() != '.png':
                continue
            if path.is_symlink() or path.is_junction() or path.resolve().parent != source:
                raise ValueError('立绘包不能包含链接到其他目录的图片')
            if len(files) >= ResourceLibrary.MAX_FILES:
                raise ValueError('每个包最多256张PNG')
            check_png(path, decode=True)
            total += path.stat().st_size
            if total > 512 * 1024 * 1024:
                raise ValueError('单个立绘包最多512MB')
            files.append(path)
        if not files:
            raise ValueError('这个文件夹没有有效PNG，请选择直接包含立绘图片的文件夹')
        name = name or source.name
        if not valid_expression_name(name):
            raise ValueError('包名称须为1到64个字符，不含文件名特殊字符')
        used = {label.casefold() for label in self.packs.values()}
        original_name, number = name, 2
        while name.casefold() in used:
            name = f'{original_name[:55]}（{number}）'
            number += 1
        key = uuid4().hex
        if self.pack_root.is_symlink() or self.pack_root.is_junction():
            raise ValueError('受管立绘目录不能是符号链接或目录联接')
        directory = self.pack_root.resolve() / key
        directory.mkdir(parents=True, exist_ok=False)
        created = []
        try:
            for source_file in files:
                target = directory / source_file.name
                if not QFile.copy(str(source_file), str(target)):
                    raise OSError(f'无法复制{source_file.name}')
                created.append(target)
            library = ResourceLibrary(directory, directory / '.resources.json', catalog=self.base,
                                      expressions=self._base_expressions, include_builtin=False)
            state = deepcopy(library.state)
            state['files'] = {path.name: {'kind': 'portrait', 'owned': True} for path in created}
            library._commit(state)
            created.append(library.state_file)
            library.refresh()
            library.catalog()
            data = deepcopy(self.manifest)
            data['packs'][key] = {'name': name, 'directory': str(directory), 'files': [path.name for path in files]}
            data['active'] = key
            self._commit_manifest(data)
        except Exception:
            # 仅清理本次新建目录中的已知副本，不递归处理源文件夹。
            for path in created:
                path.unlink(missing_ok=True)
            directory.rmdir()
            raise
        self.active = library
        self.refresh()
        return key

    def rename_pack(self, key, name):
        if not valid_expression_name(name):
            raise ValueError('请输入1到64个字符的有效包名称')
        if any(other != key and label.casefold() == name.casefold() for other, label in self.packs.items()):
            raise ValueError('同名立绘包已存在')
        data = deepcopy(self.manifest)
        data['packs'][key]['name'] = name
        self._commit_manifest(data)

    def remove_pack(self, key):
        if key == 'default':
            raise ValueError('默认角色包用于安全回退，不能移除；可修改或导入新包')
        entry = self.manifest['packs'][key]
        directory = self._managed_directory(key, entry)
        owned = {name for name in entry.get('files', []) if isinstance(name, str) and Path(name).name == name
                 and '/' not in name and '\\' not in name and name.lower().endswith('.png')}
        store = self.active if self.active_id == key else ResourceLibrary(
            directory, directory / '.resources.json', catalog=self.base, include_builtin=False)
        if store.directory == directory.resolve():
            owned.update(name for name, info in store.state['files'].items()
                         if isinstance(info, dict) and info.get('owned') is True)
        data = deepcopy(self.manifest)
        del data['packs'][key]
        if data['active'] == key:
            data['active'] = 'default'
        self._commit_manifest(data)
        self._loaded_libraries.pop(key, None)
        if self.active_id == 'default':
            self.active = self.original
        # 不递归删除目录：只删除已导入的图片副本和本包配置，其他文件保留。
        for name in (*owned, '.resources.json'):
            path = directory / name
            if path.resolve().parent == directory.resolve() and not path.is_symlink() and path.is_file():
                try:
                    path.unlink()
                except OSError as error:
                    LOG.warning('包已移除，副本未能删除：%s', error)
        if directory.exists():
            try:
                directory.rmdir()
            except OSError:
                LOG.warning('包已移除，目录内其余文件保留：%s', directory)
        self.refresh()

    def refresh(self):
        self.global_resources.refresh()
        for library in {self.original, self.active}:
            if library.directory == self.global_resources.directory:
                for item in self.global_resources.records.values():
                    if item.kind != 'portrait' and not item.builtin:
                        library.state['files'][item.path.name] = {'kind': item.kind, 'owned': item.owned}
            library.refresh()

    def catalog(self):
        return self.active.catalog()

    def expression_key(self, expression):
        return self.active.expression_key(expression)

    def skin_key(self, color):
        return 'global:' + self.global_resources.skin_key(color)

    def _owner(self, key):
        return (self.global_resources, key.removeprefix('global:')) if key.startswith('global:') else (self.active, key)

    def import_png(self, source, kind='portrait'):
        library = self.active if kind == 'portrait' else self.global_resources
        key = library.import_png(source, kind, copy_within=True)
        self.refresh()
        return key if kind == 'portrait' else 'global:' + key

    def set_mapping(self, expression, key):
        self.active.set_mapping(expression, key)

    def set_default(self, key):
        library, raw = self._owner(key)
        library.set_default(raw)

    def remove(self, key):
        library, raw = self._owner(key)
        library.remove(raw)
        self.refresh()

    def rename_image(self, key, name):
        library, raw = self._owner(key)
        renamed = library.rename_image(raw, name)
        self.refresh()
        return 'global:' + renamed if key.startswith('global:') else renamed

    def replace_image(self, key, source):
        library, raw = self._owner(key)
        library.replace_image(raw, source)
        self.refresh()

    def change_directory(self, path, global_bubbles=False):
        library = self.global_resources if global_bubbles else self.active
        if not global_bubbles and not library.include_builtin:
            candidate = ResourceLibrary(path, self.manifest_file.parent / (uuid4().hex + '.json'),
                                        catalog=self.base, expressions=self._base_expressions, include_builtin=False)
            candidate.catalog()
        if not self.global_resources.state_file.exists():
            self.global_resources.directory.mkdir(parents=True, exist_ok=True)
            self.global_resources.save()
        library.change_directory(path)
        self.refresh()

    def reset(self, global_bubbles=False):
        (self.global_resources if global_bubbles else self.active).reset()

    def save(self):
        self.active.save()
        self.global_resources.save()
        self._commit_manifest(deepcopy(self.manifest))
