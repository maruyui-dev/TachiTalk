"""本地PNG资源库：受控复制、神态映射与原子保存；不保存任何API密钥。"""
from copy import copy, deepcopy
from dataclasses import dataclass
import json
import logging
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QSaveFile
from PySide6.QtGui import QImageReader
from app.ui.pet.expressions import ExpressionCatalog
from app.paths import BUBBLE_DIR
from app.core.expressions import valid_expression_name

LOG = logging.getLogger('tachitalk.resources')
KINDS = {'portrait': '人物立绘', 'pink': '粉色气泡', 'blue': '蓝色气泡'}


def save_resource_json(path, state):
    path = Path(path)
    data = json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8')
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('资源配置超过2MB，请减少资源数量')
    path.parent.mkdir(parents=True, exist_ok=True)
    target = QSaveFile(str(path))
    if not target.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(f'无法保存资源配置：{target.errorString()}')
    if target.write(data) != len(data) or not target.commit():
        target.cancelWriting()
        raise OSError(f'资源配置写入失败：{target.errorString()}')


@dataclass(frozen=True)
class Resource:
    key: str
    path: Path
    kind: str
    builtin: bool = False
    owned: bool = False


def check_png(path, decode=False):
    """先查格式与像素上限，再解码，避免伪装文件或超大图片占满内存。"""
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != '.png' or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('请选择不超过64MB的PNG图片')
    reader = QImageReader(str(path))
    size = reader.size()
    if bytes(reader.format()).lower() != b'png' or not reader.canRead():
        raise ValueError(f'{path.name} 不是有效的PNG图片')
    if (size.width() <= 0 or size.height() <= 0 or max(size.width(), size.height()) > 8192
            or size.width() * size.height() > 12_000_000):
        raise ValueError(f'{path.name} 尺寸过大：单边最多8192像素，总像素最多1200万')
    if decode and reader.read().isNull():
        raise ValueError(f'{path.name} 图片损坏：{reader.errorString()}')


class ResourceLibrary:
    MAX_FILES = 256

    def __init__(self, directory, state_file, catalog=None, expressions=None, include_builtin=True):
        self.base = catalog or ExpressionCatalog()
        self.include_builtin = include_builtin
        self._base_expressions = tuple(dict.fromkeys((self.base.default, *(expressions or self.base.names))))
        self.state_file = Path(state_file)
        self.state = {'directory': str(Path(directory).resolve()), 'files': {}, 'excluded': [], 'mapping': {}, 'skins': {}}
        self.warning = ''
        self._validated = {}
        if self.state_file.exists():
            try:
                if self.state_file.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError('配置文件超过2MB')
                saved = json.loads(self.state_file.read_text(encoding='utf-8'))
                if not isinstance(saved, dict) or not isinstance(saved.get('directory'), str):
                    raise ValueError('配置格式不正确')
                directory_value = saved['directory']
                if (not directory_value.strip() or any(ord(char) < 32 for char in directory_value)
                        or not Path(directory_value).is_absolute()):
                    raise ValueError('资源目录必须是有效的绝对路径')
                Path(directory_value).resolve()
                for key in ('files', 'mapping', 'skins'):
                    if not isinstance(saved.get(key, {}), dict):
                        raise ValueError(f'{key}格式不正确')
                if not isinstance(saved.get('excluded', []), list):
                    raise ValueError('excluded格式不正确')
                if any(not isinstance(name, str) for name in saved.get('excluded', [])):
                    raise ValueError('excluded只能包含文件名')
                self.state.update({key: saved[key] for key in self.state if key in saved})
            except (OSError, ValueError, TypeError) as error:
                self.warning = f'资源配置无法读取，已使用内置资源：{error}'
                LOG.warning(self.warning)
        self.refresh()

    @property
    def directory(self):
        return Path(self.state['directory']).resolve()

    @property
    def expressions(self):
        # 图片文件名就是新增的神态名；固定映射行仍保留，便于给TTS情绪补图。
        names = [item.path.stem for item in self.records.values()
                 if item.kind == 'portrait' and valid_expression_name(item.path.stem)]
        for name, ref in self.state['mapping'].items():
            item = self.records.get(ref) if isinstance(ref, str) else None
            if valid_expression_name(name) and item and item.kind == 'portrait':
                names.append(name)
        return tuple(dict.fromkeys((*self._base_expressions, *sorted(names))))[:self.MAX_FILES + len(self._base_expressions)]

    @property
    def active_expressions(self):
        # 没有实际图片/映射的TTS情绪只保留在设置页，不向LLM宣传成可用神态。
        return tuple(name for name in self.expressions if name == self.base.default or self._direct_key(name) is not None)

    def refresh(self):
        self.records = {f'builtin:portrait:{name}': Resource(f'builtin:portrait:{name}', path, 'portrait', True)
                        for name, path in self.base.paths.items()} if self.include_builtin else {}
        for color in ('pink', 'blue'):
            path = BUBBLE_DIR / f'bubble_{color}.png'
            self.records[f'builtin:{color}'] = Resource(f'builtin:{color}', path, color, True)
        directory = self.directory
        if not directory.is_dir():
            if self.state_file.exists():
                self.warning = f'资源目录不可用：{directory}；暂用内置资源'
                LOG.warning(self.warning)
            return
        count = 0
        builtin_paths = {item.path.resolve() for item in self.records.values() if item.builtin}
        for path in directory.iterdir():
            if path.suffix.lower() != '.png' or path.name in self.state['excluded']:
                continue
            if path.resolve() in builtin_paths:
                continue  # 内置资源现在与项目资源共目录，不重复注册同一张图片。
            if count >= self.MAX_FILES:
                LOG.warning('资源目录最多加载%s张PNG，其他文件未加载', self.MAX_FILES)
                break
            if path.is_symlink() or path.resolve().parent != directory:
                continue
            try:
                signature = (path.stat().st_mtime_ns, path.stat().st_size)
                if self._validated.get(path) != signature:
                    check_png(path, decode=True)
                    self._validated[path] = signature
            except (OSError, ValueError) as error:
                LOG.warning('忽略资源：%s', error)
                continue
            info = self.state['files'].get(path.name, {})
            if not isinstance(info, dict):
                info = {}
            kind = info.get('kind', 'portrait')
            kind = kind if isinstance(kind, str) and kind in KINDS else 'portrait'
            key = f'file:{path.name}'
            self.records[key] = Resource(key, path, kind, owned=info.get('owned') is True)
            count += 1
        active_paths = {item.path for item in self.records.values() if not item.builtin}
        self._validated = {path: signature for path, signature in self._validated.items() if path in active_paths}
        for ref in (*self.state['mapping'].values(), *self.state['skins'].values()):
            if not isinstance(ref, str) or ref not in self.records:
                self.warning = '部分映射的图片不存在或无效，已回退内置立绘／皮肤；请重新导入或选择映射'
                LOG.warning(self.warning)
                break

    def _commit(self, state):
        # 清理已删除文件留下的元数据；反复导入/移除不会累积历史列表。
        root = Path(state['directory']).resolve()
        def present(name):
            return (isinstance(name, str) and name not in ('.', '..') and '/' not in name and '\\' not in name
                    and (root / name).is_file())
        state['files'] = {name: info for name, info in state['files'].items() if present(name)}
        state['excluded'] = [name for name in state['excluded'] if present(name)]
        save_resource_json(self.state_file, state)
        self.state = state

    def save(self):
        self._commit(deepcopy(self.state))

    def import_png(self, source, kind='portrait', copy_within=False):
        if kind not in KINDS:
            raise ValueError('未知资源类型')
        source = Path(source).resolve()
        check_png(source, decode=True)
        builtin = next((item for item in self.records.values()
                        if item.builtin and item.path.resolve() == source), None)
        if builtin is not None and builtin.kind == kind and not copy_within:
            return builtin.key
        if sum(not item.builtin for item in self.records.values()) >= self.MAX_FILES:
            raise ValueError(f'最多管理{self.MAX_FILES}张PNG，请先移除不用的资源')
        self.directory.mkdir(parents=True, exist_ok=True)
        owned = source.parent != self.directory or copy_within or builtin is not None
        target = source
        if owned:
            target = self.directory / source.name
            number = 2
            while target.exists():
                target = self.directory / f'{source.stem}_{number}.png'
                number += 1
            # QFile.copy不会覆盖同名文件；即使有外部程序并发写入，也保留已有文件。
            if not QFile.copy(str(source), str(target)):
                raise OSError(f'无法复制{source.name}，请检查目录权限或重名文件')
        state = deepcopy(self.state)
        previous = self.state['files'].get(target.name, {})
        state['files'][target.name] = {'kind': kind, 'owned': owned or
                                      (isinstance(previous, dict) and previous.get('owned') is True)}
        state['excluded'] = [name for name in state['excluded'] if name != target.name]
        key = f'file:{target.name}'
        if kind == 'portrait' and source.stem in self.expressions:
            state['mapping'][source.stem] = key
        try:
            self._commit(state)
        except (OSError, ValueError):
            if owned:
                target.unlink()
            raise
        self.refresh()
        return key

    def _direct_key(self, expression):
        key = self.state['mapping'].get(expression)
        item = self.records.get(key) if isinstance(key, str) else None
        if item and item.kind == 'portrait':
            return key
        builtin = f'builtin:portrait:{expression}'
        if builtin in self.records:
            return builtin
        for item in self.records.values():
            if item.kind == 'portrait' and item.path.stem == expression:
                return item.key
        return None

    def expression_key(self, expression):
        key = self._direct_key(expression)
        if key is not None:
            return key
        if expression != self.base.default:
            return self.expression_key(self.base.default)
        # 自定义角色缺少“生气.png”时使用该角色第一张图，绝不串入别人的立绘。
        for item in self.records.values():
            if item.kind == 'portrait':
                return item.key
        raise ValueError('这个立绘包没有可用PNG，请重新导入图片或切换立绘包')

    def skin_key(self, color):
        key = self.state['skins'].get(color)
        item = self.records.get(key) if isinstance(key, str) else None
        return key if item and item.kind == color else f'builtin:{color}'

    def catalog(self):
        # 窗口也保留缺图情绪的默认回退；LLM使用active_expressions只选真实资源。
        catalog = copy(self.base)
        catalog.paths = {name: self.records[self.expression_key(name)].path for name in self.expressions}
        catalog.names = self.expressions
        return catalog

    def set_mapping(self, expression, key):
        if expression not in self.expressions or (key is not None and
                (key not in self.records or self.records[key].kind != 'portrait')):
            raise ValueError('请选择存在的人物立绘')
        state = deepcopy(self.state)
        if key is None:
            state['mapping'].pop(expression, None)
        else:
            check_png(self.records[key].path, decode=True)
            state['mapping'][expression] = key
        self._commit(state)

    def set_default(self, key):
        item = self.records[key]
        if item.kind == 'portrait':
            self.set_mapping(self.base.default, key)
        else:
            check_png(item.path, decode=True)
            state = deepcopy(self.state)
            state['skins'][item.kind] = key
            self._commit(state)

    def remove(self, key):
        item = self.records[key]
        if item.builtin:
            raise ValueError('内置资源不可移除，请导入新图片替换映射')
        if (not self.include_builtin and item.kind == 'portrait'
                and sum(record.kind == 'portrait' for record in self.records.values()) <= 1):
            raise ValueError('不能移除立绘包最后一张图片；可先导入替换图片，或移除整个立绘包')
        if item.path.is_symlink() or item.path.resolve().parent != self.directory:
            raise ValueError('资源路径不在当前目录内，拒绝删除')
        state = deepcopy(self.state)
        state['files'].pop(item.path.name, None)
        state['excluded'] = list(set(state['excluded']) | {item.path.name})
        for section in ('mapping', 'skins'):
            state[section] = {name: ref for name, ref in state[section].items() if ref != key}
        self._commit(state)
        if item.owned:
            try:
                item.path.unlink(missing_ok=True)
            except OSError as error:
                LOG.warning('已移出资源库，但未能删除副本%s：%s', item.path.name, error)
        self.refresh()

    def _editable(self, key):
        item = self.records[key]
        if item.builtin or not item.owned:
            raise ValueError('只能修改已导入的副本，请先导入PNG')
        if item.path.is_symlink() or item.path.resolve().parent != self.directory:
            raise ValueError('图片不在当前资源目录，拒绝修改')
        return item

    def rename_image(self, key, name):
        item = self._editable(key)
        name = name[:-4] if name.lower().endswith('.png') else name
        if not valid_expression_name(name):
            raise ValueError('神态名须为1到64个字符，不含路径和文件名特殊字符')
        target = item.path.with_name(name + '.png')
        if target == item.path:
            return key
        if target.exists() or not QFile.rename(str(item.path), str(target)):
            raise ValueError('同名图片已存在或图片无法重命名')
        new_key = f'file:{target.name}'
        state = deepcopy(self.state)
        state['files'][target.name] = state['files'].pop(item.path.name)
        for section in ('mapping', 'skins'):
            state[section] = {label: new_key if ref == key else ref for label, ref in state[section].items()
                              if not (section == 'mapping' and label == item.path.stem
                                      and label != self.base.default and ref == key)}
        try:
            self._commit(state)
        except (OSError, ValueError):
            if not QFile.rename(str(target), str(item.path)):
                LOG.error('保存失败且重命名回滚失败，请检查资源目录：%s', self.directory)
            raise
        self.refresh()
        return new_key

    def replace_image(self, key, source):
        item = self._editable(key)
        source = Path(source).resolve()
        check_png(source, decode=True)
        if source == item.path.resolve():
            return
        target = QSaveFile(str(item.path))
        if not target.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError('图片无法写入，请检查目录权限')
        try:
            with source.open('rb') as stream:
                while block := stream.read(256 * 1024):
                    if target.write(block) != len(block):
                        raise OSError('替换图片写入失败')
            if not target.commit():
                raise OSError('替换图片保存失败，原图片保留')
        except Exception:
            target.cancelWriting()
            raise
        self._validated.pop(item.path, None)
        self.refresh()

    def change_directory(self, directory):
        if not str(directory).strip():
            raise ValueError('请选择资源文件夹，目录不能为空')
        path = Path(directory).expanduser().resolve()
        if not path.is_dir():
            raise ValueError('资源目录不存在，请先选择已有文件夹')
        if path == self.directory:
            self.refresh()
            return
        state = deepcopy(self.state)
        state.update(directory=str(path), files={}, excluded=[])
        for section in ('mapping', 'skins'):
            state[section] = {name: ref for name, ref in state[section].items()
                              if isinstance(ref, str) and ref.startswith('builtin:')}
        self._commit(state)
        self.refresh()

    def reset(self):
        state = deepcopy(self.state)
        state.update(mapping={}, skins={})
        self._commit(state)
