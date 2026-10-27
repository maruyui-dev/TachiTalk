"""Owned training projects, editable annotations and immutable source audio copies."""
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from uuid import uuid4
from copy import deepcopy

from app.core.resources import save_resource_json


def apply_voice(project, data_root, library, reference, prompt, language):
    """Add a reference without removing recordings, then select the model pair."""
    from app.core.audio_library import inspect_audio
    from app.core.expressions import valid_expression_name
    inspect_audio(reference)
    if not prompt.strip() or language not in LANGUAGES:
        raise ValueError('请选择参考音频语言并填写对应原文')
    pair = project.model_pair()
    previous = deepcopy(library.state)
    try:
        added = library.add(reference)
        name = project.state['name'][:48]
        if not valid_expression_name(name):
            name = '训练声音'
        occupied = {ref.name.casefold() for ref in library.records.values() if ref.key != added.key}
        base, suffix = name, 2
        while name.casefold() in occupied:
            name = f'{base}（{suffix}）'
            suffix += 1
        library.update(added.key, name=name, scene='训练角色参考音频', prompt=prompt,
                       language=language, enabled=True, default=True)
        save_resource_json(Path(data_root) / 'settings/active_voice_model.json', dict(version=VERSION,
            project=str(project.directory), **{k: str(v) for k, v in pair.items()}))
    except Exception:
        library._commit(previous)
        raise
    return added.key

VERSION = 'v2ProPlus'
LANGUAGES = ('ja', 'zh', 'en', 'ko', 'yue')
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac'}
ASR_MODEL = 'models/asr/large-v3-turbo.pt'
UVR_MODEL = 'models/uvr/HP2_all_vocals.pth'
TRAINING_FILES = (
    ASR_MODEL, UVR_MODEL,
    'GPT_SoVITS/s1_train.py', 'GPT_SoVITS/s2_train.py',
    'GPT_SoVITS/configs/s2v2ProPlus.json', 'GPT_SoVITS/configs/s1longer-v2.json',
    'GPT_SoVITS/prepare_datasets/1-get-text.py',
    'GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py',
    'GPT_SoVITS/prepare_datasets/2-get-sv.py',
    'GPT_SoVITS/prepare_datasets/3-get-semantic.py',
    'GPT_SoVITS/pretrained_models/s1v3.ckpt',
    'GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth',
    'GPT_SoVITS/pretrained_models/v2Pro/s2Dv2ProPlus.pth',
    'training_progress.py', 'tools/slicer2.py', 'tools/uvr5/vr.py',
    'tools/uvr5/lib/lib_v5/nets_61968KB.py', 'tools/uvr5/lib/lib_v5/nets_new.py',
    'tools/uvr5/lib/lib_v5/layers_123821KB.py', 'tools/uvr5/lib/lib_v5/layers_new.py',
    'tools/uvr5/lib/lib_v5/spec_utils.py', 'tools/uvr5/lib/lib_v5/model_param_init.py',
    'tools/uvr5/lib/lib_v5/modelparams/4band_v2.json', 'tools/uvr5/lib/utils.py',
)


def training_location(service, app_root=None):
    if app_root is not None:
        local = Path(app_root) / 'services/gpt_sovits/training'
        if local.is_dir():
            return local
    return Path(service) / 'training'


def training_status(service, app_root=None):
    root = training_location(service, app_root)
    missing = [name for name in TRAINING_FILES if not (root / name).is_file()]
    return dict(installed=not missing, missing=missing, version=VERSION)


@dataclass
class TrainingOptions:
    sovits_epochs: int = 8
    gpt_epochs: int = 15
    batch_size: int = 2
    save_every: int = 1
    gpu: str = '0'
    half: bool = True
    version: str = VERSION

    def validate(self):
        if self.version != VERSION:
            raise ValueError('仅支持 v2ProPlus')
        if not all(isinstance(n, int) and 1 <= n <= 1000 for n in
                   (self.sovits_epochs, self.gpt_epochs, self.save_every)):
            raise ValueError('训练轮数/保存间隔必须为1～1000')
        if not 1 <= self.batch_size <= 64 or self.gpu not in ('cpu', '0', '1', '2', '3', '4', '5', '6', '7'):
            raise ValueError('请选择有效批次大小和设备')


class TrainingProject:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.path = self.directory / 'project.json'
        self.state = json.loads(self.path.read_text(encoding='utf-8'))
        if self.state.get('version') != VERSION:
            raise ValueError('仅支持 v2ProPlus 训练项目')

    @classmethod
    def create(cls, parent, name, language='ja'):
        if not name.strip() or len(name.strip()) > 80 or language not in LANGUAGES:
            raise ValueError('请填写项目名称并选择支持的语言')
        directory = Path(parent) / uuid4().hex
        directory.mkdir(parents=True)
        save_resource_json(directory / 'project.json', dict(name=name.strip(), version=VERSION,
                    language=language, annotations=[], models={}))
        return cls(directory)

    def save(self):
        save_resource_json(self.path, self.state)

    def owned(self, relative):
        path = (self.directory / relative).resolve()
        if not path.is_relative_to(self.directory) or path == self.directory:
            raise ValueError('训练项目路径越界')
        return path

    def import_audio(self, sources):
        records = []
        for source in map(Path, sources):
            if not source.is_file() or source.suffix.lower() not in AUDIO_EXTENSIONS:
                raise ValueError('请选择支持的音频文件')
            destination = self.owned('audio/' + uuid4().hex + source.suffix.lower())
            destination.parent.mkdir(exist_ok=True)
            shutil.copy2(source, destination)
            records.append(dict(audio=destination.relative_to(self.directory).as_posix(),
                name=source.name, speaker='speaker', language=self.state['language'], text=''))
        self.state['annotations'].extend(records)
        (self.directory / 'features/ready.json').unlink(missing_ok=True)
        self.save()
        return records

    def set_annotations(self, records):
        checked, seen = [], set()
        for item in records:
            audio = self.owned(item['audio'])
            if not audio.is_file() or audio.suffix.lower() not in AUDIO_EXTENSIONS:
                raise ValueError('标注的音频不存在或格式不支持')
            if item['language'] not in LANGUAGES:
                raise ValueError('标注语言不支持')
            if any('|' in str(item[key]) or '\n' in str(item[key]) or '\r' in str(item[key])
                   for key in ('audio', 'speaker', 'language', 'text')):
                raise ValueError('标注内容不能包含竖线或换行')
            if audio.name.casefold() in seen:
                raise ValueError('数据集音频文件名重复')
            seen.add(audio.name.casefold())
            checked.append(dict(item))
        if self.state['annotations'] != checked:
            (self.directory / 'features/ready.json').unlink(missing_ok=True)
        self.state['annotations'] = checked
        self.save()

    def write_filelist(self):
        self.set_annotations(self.state['annotations'])
        if not self.state['annotations'] or any(not r['text'].strip() for r in self.state['annotations']):
            raise ValueError('请先完成并保存全部音频标注')
        output = self.directory / 'dataset.list'
        lines = ['|'.join((str(self.owned(r['audio'])), r['speaker'], r['language'], r['text'].strip()))
                 for r in self.state['annotations']]
        temporary = output.with_suffix('.list.new')
        temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        temporary.replace(output)
        return output

    def model_pair(self):
        result = self.state.get('models', {})
        paths = {kind: self.owned(result[kind]) for kind in ('gpt', 'sovits') if kind in result}
        if set(paths) != {'gpt', 'sovits'} or not all(p.is_file() for p in paths.values()):
            raise ValueError('请先完成 GPT 和 SoVITS 训练并检测模型')
        return paths

    def refresh_models(self):
        for kind, pattern in (('gpt', '*.ckpt'), ('sovits', '*.pth')):
            paths = list((self.directory / 'models').glob(pattern))
            if paths:
                latest = max(paths, key=lambda p: p.stat().st_mtime_ns)
                self.state['models'][kind] = latest.relative_to(self.directory).as_posix()
        self.save()
        return self.state['models']
