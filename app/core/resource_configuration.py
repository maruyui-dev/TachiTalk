"""全局配置中的资源路径与映射；只配置已有图片，不导入、覆盖或删除图片。"""
from copy import copy, deepcopy
import json
from pathlib import Path

from app.paths import PROJECT_ROOT
from app.core.expressions import valid_expression_name
from app.core.resources import KINDS


def _path_text(path):
    path = Path(path).resolve()
    return '@project/' + path.relative_to(PROJECT_ROOT).as_posix() if path.is_relative_to(PROJECT_ROOT) else str(path)


def _directory(text):
    if not isinstance(text, str) or not text or len(text) > 4096 or any(ord(c) < 32 for c in text):
        raise ValueError('资源目录格式不正确')
    path = (PROJECT_ROOT / text[9:]).resolve() if text.startswith('@project/') else Path(text)
    if text.startswith('@project/') and not path.is_relative_to(PROJECT_ROOT):
        raise ValueError('项目相对资源目录超出项目范围')
    if not path.is_absolute() or not path.is_dir():
        raise ValueError('配置引用的资源目录不存在，请先准备对应立绘包和气泡图片')
    return path.resolve()


def _owner(library, key):
    if key == 'default':
        return library.original
    if key == library.active_id:
        return library.active
    if key in library._loaded_libraries:
        return library._loaded_libraries[key]
    directory = library._managed_directory(key, library.manifest['packs'][key])
    owner = copy(library.original)
    owner.include_builtin = False
    owner.state_file = directory / '.resources.json'
    owner.state = {'directory': str(directory), 'files': {}, 'excluded': [], 'mapping': {}, 'skins': {}}
    if owner.state_file.exists():
        if owner.state_file.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('立绘包配置过大，无法备份')
        owner.state.update(json.loads(owner.state_file.read_text(encoding='utf-8')))
    return owner


def capture_resources(library):
    def state(owner):
        result = deepcopy(owner.state)
        result['directory'] = _path_text(owner.directory)
        return result
    return {'active': library.active_id,
            'packs': {key: {'name': name, 'state': state(_owner(library, key))}
                      for key, name in library.packs.items()},
            'bubbles': state(library.global_resources)}


def _filename(value):
    return (isinstance(value, str) and len(value) <= 255 and value.lower().endswith('.png')
            and Path(value).name == value and '/' not in value and '\\' not in value)


def _candidate(owner, state):
    if not isinstance(state, dict) or set(state) != {'directory', 'files', 'excluded', 'mapping', 'skins'}:
        raise ValueError('资源配置字段不完整或含有未知字段')
    directory = _directory(state['directory'])
    for name in ('files', 'mapping', 'skins'):
        if not isinstance(state[name], dict) or len(state[name]) > 300:
            raise ValueError('资源映射格式不正确或条目过多')
    if not isinstance(state['excluded'], list) or len(state['excluded']) > 256 or not all(map(_filename, state['excluded'])):
        raise ValueError('资源排除列表格式不正确')
    state = deepcopy(state)
    for filename, info in state['files'].items():
        if (not _filename(filename) or not isinstance(info, dict) or set(info) - {'kind', 'owned'}
                or not isinstance(info.get('kind'), str) or info['kind'] not in KINDS):
            raise ValueError('资源文件信息不正确')
        # 备份文件不能给任意现有文件授予删除权限，只沿用本机已经拥有的副本。
        old = owner.state['files'].get(filename, {}) if directory == owner.directory else {}
        info['owned'] = isinstance(old, dict) and old.get('owned') is True
    if any(not valid_expression_name(name) or not isinstance(ref, str) for name, ref in state['mapping'].items()):
        raise ValueError('神态映射格式不正确')
    if any(color not in ('pink', 'blue') or not isinstance(ref, str) for color, ref in state['skins'].items()):
        raise ValueError('气泡皮肤配置不正确')
    candidate = copy(owner)
    candidate.state = state
    candidate.state['directory'] = str(directory)
    candidate._validated = {}
    candidate.warning = ''
    candidate.refresh()
    for section in ('mapping', 'skins'):
        for name, ref in list(state[section].items()):
            kind = 'portrait' if section == 'mapping' else name
            if ref not in candidate.records:
                # 同一PNG可能从“导入图片”变成“内置图片”；按真实路径恢复稳定的引用。
                path = None
                if ref.startswith('file:') and _filename(ref[5:]):
                    path = directory / ref[5:]
                elif ref.startswith('builtin:portrait:') and valid_expression_name(ref[17:]):
                    path = owner.base.assets_dir / (ref[17:] + '.png')
                if path is not None:
                    ref = next((key for key, item in candidate.records.items()
                                if item.path.resolve() == path.resolve() and item.kind == kind), ref)
                    state[section][name] = ref
            if ref not in candidate.records or candidate.records[ref].kind != kind:
                raise ValueError('配置引用的图片不存在或资源类型不匹配，请先导入对应图片')
    return candidate


def prepare_resources(library, data):
    if (not isinstance(data, dict) or set(data) != {'active', 'packs', 'bubbles'}
            or not isinstance(data['packs'], dict) or len(data['packs']) > library.MAX_PACKS
            or 'default' not in data['packs'] or data['active'] not in data['packs']):
        raise ValueError('角色包配置格式不正确')
    packs, resolved = {}, {}
    manifest = deepcopy(library.manifest)
    for key, entry in data['packs'].items():
        if not isinstance(entry, dict) or set(entry) != {'name', 'state'} or not valid_expression_name(entry['name']):
            raise ValueError('角色包名称或配置不正确')
        target = key
        if target not in library.packs:
            matches = [id for id, name in library.packs.items() if name == entry['name']]
            if len(matches) != 1:
                raise ValueError('配置中的角色包尚未导入，请先导入同名立绘包后再加载')
            target = matches[0]
        if target in packs:
            raise ValueError('配置中的角色包重复或名称有歧义')
        owner = _owner(library, target)
        state = deepcopy(entry['state'])
        if target != key:
            state['directory'] = str(owner.directory)
        packs[target] = _candidate(owner, state)
        packs[target].catalog()
        manifest['packs'][target]['name'] = entry['name']
        resolved[key] = target
    bubbles = _candidate(library.global_resources, data['bubbles'])
    manifest['active'] = resolved[data['active']]
    names = [entry['name'] for entry in manifest['packs'].values()]
    if len(names) != len(set(names)):
        raise ValueError('恢复后的角色包名称重复，请先调整本机包名')
    return packs, bubbles, manifest


def apply_resources(library, prepared):
    packs, bubbles, manifest = prepared
    library.original = packs['default']
    library.global_resources = bubbles
    library._loaded_libraries = {key: owner for key, owner in packs.items() if key != 'default'}
    library.manifest = manifest
    library.active = packs[manifest['active']]
    library.refresh()
