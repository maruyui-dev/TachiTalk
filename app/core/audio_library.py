"""参考音频库：原子保存、不可变轮次快照及独立角色音频包。"""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
from itertools import islice
from pathlib import Path
from threading import Lock
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
import wave

from app.core.expressions import valid_expression_name
from app.core.resources import save_resource_json


def inspect_audio(path):
    """只接受本地GPT-SoVITS可直接使用的3～10秒PCM16 WAV，不转码。"""
    path = Path(path)
    if path.suffix.lower() != '.wav' or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('请选择不超过8MB的WAV参考音频')
    try:
        with wave.open(str(path), 'rb') as stream:
            rate, channels, frames = stream.getframerate(), stream.getnchannels(), stream.getnframes()
            if (stream.getsampwidth() != 2 or channels not in (1, 2) or not 16000 <= rate <= 96000
                    or not 3 <= frames / rate <= 10 or stream.getcomptype() != 'NONE'):
                raise ValueError('参考音频须为3～10秒、16～96kHz、16位PCM单/双声道WAV')
            pcm = stream.readframes(frames)
            if len(pcm) != frames * channels * 2:
                raise ValueError('WAV音频已截断')
        return rate, channels, frames / rate
    except (wave.Error, EOFError) as error:
        raise ValueError('无法读取有效WAV音频') from error


@dataclass(frozen=True, slots=True)
class AudioReference:
    key: str
    name: str
    path: str
    prompt: str = ''
    scene: str = ''
    language: str = 'ja'
    enabled: bool = False


@dataclass(frozen=True, slots=True)
class AudioSnapshot:
    references: tuple[AudioReference, ...]
    default: AudioReference

    @property
    def names(self):
        return tuple(ref.name for ref in self.references)

    def resolve(self, name):
        return next((ref for ref in self.references if ref.name == name), self.default)


class AudioLibrary:
    MAX_FILES = 128
    MAX_PACKS = 32

    def __init__(self, state_file, seeds=None):
        self.state_file = Path(state_file)
        self.directory = self.state_file.parent / 'audio_files'
        self._lock = Lock()
        self.warning = ''
        self.read_only = False
        refs = [AudioReference(uuid5(NAMESPACE_URL, f'tachitalk:audio:{name}:{Path(path).resolve().as_posix()}').hex,
                              name, str(Path(path).resolve()), prompt, name, enabled=True)
                for name, (path, prompt) in (seeds or {}).items()]
        default = next((ref.key for ref in refs if ref.name == '平常'), refs[0].key if refs else '')
        self.state = {'active': 'default', 'packs': {
            'default': {'name': '茉子', 'default': default, 'references': [asdict(ref) for ref in refs]}}}
        if self.state_file.exists():
            # 损坏的用户配置不能被后续一次保存静默覆盖。
            try:
                if self.state_file.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError('音频库配置超过2MB上限')
                data = json.loads(self.state_file.read_text(encoding='utf-8'))
                self.validate(data)
                self.state = data
            except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
                self.read_only = True
                self.warning = f'音频库配置损坏，已只读使用初始参考；请修复或备份后移走 {self.state_file}：{error}'

    @staticmethod
    def validate(data):
        try:
            AudioLibrary._validate_state(data)
        except (KeyError, TypeError, AttributeError, UnicodeError) as error:
            raise ValueError('音频库清单格式错误') from error

    @staticmethod
    def _validate_state(data):
        packs = data['packs']
        if (not isinstance(packs, dict) or not 1 <= len(packs) <= AudioLibrary.MAX_PACKS
                or 'default' not in packs or data['active'] not in packs):
            raise ValueError('音频包清单无效')
        for pack_id, pack in packs.items():
            if pack_id != 'default' and UUID(pack_id).hex != pack_id:
                raise ValueError('音频包编号无效')
            if not valid_expression_name(pack['name']) or len(pack['references']) > AudioLibrary.MAX_FILES:
                raise ValueError('音频包名称或数量无效')
            names, keys = set(), set()
            for record in pack['references']:
                ref = AudioReference(**record)
                if (not valid_expression_name(ref.name) or ref.name.casefold() in names
                        or not isinstance(ref.key, str) or UUID(ref.key).hex != ref.key or ref.key in keys
                        or type(ref.enabled) is not bool
                        or ref.language not in ('ja', 'zh', 'en', 'ko', 'yue') or not isinstance(ref.prompt, str) or len(ref.prompt) > 1000
                        or not isinstance(ref.scene, str) or len(ref.scene) > 200
                        or not isinstance(ref.path, str) or not Path(ref.path).is_absolute()):
                    raise ValueError('音频名称、路径或原文无效；昵称不得重复')
                names.add(ref.name.casefold())
                keys.add(ref.key)
            if pack['default'] and pack['default'] not in keys:
                raise ValueError('默认音频不存在')

    @property
    def active_id(self):
        return self.state['active']

    @property
    def packs(self):
        return {key: pack['name'] for key, pack in self.state['packs'].items()}

    @property
    def records(self):
        return {ref['key']: AudioReference(**ref) for ref in self.state['packs'][self.active_id]['references']}

    @property
    def default_key(self):
        return self.state['packs'][self.active_id]['default']

    def snapshot(self):
        with self._lock:
            pack = self.state['packs'][self.active_id]
            refs = tuple(AudioReference(**ref) for ref in pack['references']
                         if ref['enabled'] and ref['prompt'].strip() and Path(ref['path']).is_file())
            if not refs:
                raise ValueError('当前音频包没有可用参考音频，请填写原文并启用至少一条音频')
            default = next((ref for ref in refs if ref.key == pack['default']), refs[0])
            return AudioSnapshot(refs, default)

    def _commit(self, data):
        if self.read_only:
            raise ValueError(self.warning)
        self.validate(data)
        for pack in data['packs'].values():
            valid = [ref['key'] for ref in pack['references']
                     if ref['enabled'] and ref['prompt'].strip() and Path(ref['path']).is_file()]
            if pack['default'] not in valid:
                pack['default'] = valid[0] if valid else ''
        save_resource_json(self.state_file, data)
        with self._lock:
            self.state = data

    def _edit(self):
        data = deepcopy(self.state)
        return data, data['packs'][data['active']]

    def _copy(self, source):
        inspect_audio(source)
        # 每次替换使用新路径；旧轮快照指向的文件始终可读，不移动原文件。
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / (uuid4().hex + '.wav')
        with Path(source).open('rb') as stream, target.open('xb') as output:
            output.write(stream.read(8 * 1024 * 1024 + 1))
        inspect_audio(target)
        return str(target.resolve())

    def add(self, source):
        data, pack = self._edit()
        if len(pack['references']) >= self.MAX_FILES:
            raise ValueError('每个音频包最多128条参考音频')
        name = Path(source).stem[:54]
        names = {ref['name'].casefold() for ref in pack['references']}
        base, number = name, 2
        while name.casefold() in names:
            name, number = f'{base}（{number}）', number + 1
        if not valid_expression_name(name):
            raise ValueError('音频文件名不能作为昵称，请先重命名文件')
        ref = AudioReference(uuid4().hex, name, self._copy(source))
        pack['references'].append(asdict(ref))
        self._commit(data)
        return ref

    def update(self, key, *, name, scene, prompt, enabled, default=False, language=None):
        data, pack = self._edit()
        ref = self.records[key]
        ref = replace(ref, name=name.strip(), scene=scene.strip(), prompt=prompt.strip(), enabled=enabled,
                      language=ref.language if language is None else language)
        if enabled:
            if not ref.prompt:
                raise ValueError('启用前请填写与参考音频一致的原文')
            inspect_audio(ref.path)
        if default and not enabled:
            raise ValueError('默认音频必须启用')
        pack['references'] = [asdict(ref) if item['key'] == key else item for item in pack['references']]
        if default:
            pack['default'] = key
        elif key == pack['default'] and not enabled:
            pack['default'] = ''
        self._commit(data)

    def replace(self, key, source):
        data, pack = self._edit()
        path = self._copy(source)
        for ref in pack['references']:
            if ref['key'] == key:
                # 新录音的原文必须重新核对，防止旧文本配错音频。
                ref.update(path=path, prompt='', enabled=False)
        if pack['default'] == key:
            pack['default'] = ''
        self._commit(data)

    def remove(self, key):
        data, pack = self._edit()
        pack['references'] = [ref for ref in pack['references'] if ref['key'] != key]
        if pack['default'] == key:
            pack['default'] = ''
        self._commit(data)

    def create_pack(self, name):
        data = deepcopy(self.state)
        if len(data['packs']) >= self.MAX_PACKS:
            raise ValueError('最多32个音频包')
        if name.casefold() in (pack['name'].casefold() for pack in data['packs'].values()):
            raise ValueError('音频包名称已存在')
        key = uuid4().hex
        data['packs'][key] = {'name': name, 'default': '', 'references': []}
        data['active'] = key
        self._commit(data)
        return key

    def import_pack(self, source):
        source = Path(source).resolve()
        files = sorted(islice(source.glob('*.wav'), self.MAX_FILES + 1))
        if not files or len(files) > self.MAX_FILES:
            raise ValueError('音频包须包含1～128条WAV音频及同名TXT日语原文')
        manifest = source / 'audio_pack.json'
        metadata = {}
        if manifest.exists():
            if manifest.stat().st_size > 256 * 1024:
                raise ValueError('音频包清单过大')
            metadata = json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(metadata, dict):
                raise ValueError('音频包清单无效')
        data = deepcopy(self.state)
        if len(data['packs']) >= self.MAX_PACKS:
            raise ValueError('最多32个音频包')
        name = source.name[:54]
        used = {pack['name'].casefold() for pack in data['packs'].values()}
        base, number = name, 2
        while name.casefold() in used:
            name, number = f'{base}（{number}）', number + 1
        refs, default = [], ''
        for path in files:
            inspect_audio(path)
            entry = metadata.get(path.name, {})
            if not isinstance(entry, dict):
                raise ValueError('音频包条目无效')
            transcript = path.with_suffix('.txt')
            if transcript.exists() and transcript.stat().st_size > 8192:
                raise ValueError('音频原文文件过大')
            prompt = transcript.read_text(encoding='utf-8-sig').strip() if transcript.exists() else ''
            ref = AudioReference(uuid4().hex, entry.get('name', path.stem), self._copy(path),
                                 prompt, entry.get('scene', ''), enabled=bool(prompt) and entry.get('enabled', True))
            refs.append(asdict(ref))
            if entry.get('default') and ref.enabled:
                default = ref.key
        key = uuid4().hex
        data['packs'][key] = {'name': name, 'default': default, 'references': refs}
        data['active'] = key
        self._commit(data)
        return key

    def export_pack(self, destination):
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=False)
        metadata = {}
        for ref in self.records.values():
            inspect_audio(ref.path)
            filename = ref.key + '.wav'
            with Path(ref.path).open('rb') as source, (directory / filename).open('xb') as target:
                target.write(source.read(8 * 1024 * 1024 + 1))
            (directory / (ref.key + '.txt')).write_text(ref.prompt, encoding='utf-8')
            metadata[filename] = {'name': ref.name, 'scene': ref.scene, 'enabled': ref.enabled,
                                  'default': ref.key == self.default_key}
        (directory / 'audio_pack.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')

    def select_pack(self, key):
        data = deepcopy(self.state)
        if key not in data['packs']:
            raise ValueError('音频包不存在')
        data['active'] = key
        self._commit(data)

    def rename_pack(self, name):
        data, pack = self._edit()
        if any(key != self.active_id and item['name'].casefold() == name.casefold()
               for key, item in data['packs'].items()):
            raise ValueError('音频包名称已存在')
        pack['name'] = name
        self._commit(data)

    def remove_pack(self):
        if self.active_id == 'default':
            raise ValueError('初始音频包不可移除，可编辑其中的音频')
        data = deepcopy(self.state)
        del data['packs'][self.active_id]
        data['active'] = 'default'
        self._commit(data)
