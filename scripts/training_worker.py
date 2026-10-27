"""Private Python 3.9 entry: v2ProPlus only; no web server or implicit downloads."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time


def write_json(path, value):
    temporary = Path(str(path) + '.new')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def event(phase, completed=None, total=None, current='', **extra):
    print('TACHITALK_EVENT ' + json.dumps(dict(phase=phase, completed=completed, total=total,
        current=current, progress_at=time.time(), **extra), ensure_ascii=True), flush=True)


def make_configs(service, project, options, training_root=None):
    """Same fields as the upstream WebUI, fixed to v2ProPlus and owned output paths."""
    if options.get('version') != 'v2ProPlus':
        raise ValueError('Only v2ProPlus is supported')
    training = (Path(training_root) if training_root is not None else Path(service) / 'training') / 'GPT_SoVITS'
    project = Path(project)
    pretrain = training / 'pretrained_models'
    s2 = json.loads((training / 'configs/s2v2ProPlus.json').read_text(encoding='utf-8'))
    s1 = json.loads((training / 'configs/s1longer-v2.json').read_text(encoding='utf-8'))
    output = project / 'models'
    output.mkdir(exist_ok=True)
    (project / 'features/logs_s2_v2ProPlus').mkdir(parents=True, exist_ok=True)
    gpu = options.get('gpu', '0')
    half = options.get('half', True) and gpu != 'cpu'
    s2['train'].update(batch_size=options['batch_size'], epochs=options['sovits_epochs'],
        pretrained_s2G=str(pretrain / 'v2Pro/s2Gv2ProPlus.pth'),
        pretrained_s2D=str(pretrain / 'v2Pro/s2Dv2ProPlus.pth'),
        if_save_latest=False, if_save_every_weights=True, save_every_epoch=options['save_every'],
        gpu_numbers='' if gpu == 'cpu' else gpu, fp16_run=half, grad_ckpt=True, num_workers=2)
    s2['model']['version'] = s2['version'] = 'v2ProPlus'
    s2['data']['exp_dir'] = s2['s2_ckpt_dir'] = str(project / 'features')
    s2.update(save_weight_dir=str(output), name='voice')
    s1['train'].update(batch_size=options['batch_size'], epochs=options['gpt_epochs'],
        save_every_n_epoch=options['save_every'], if_save_every_weights=True, if_save_latest=False,
        if_dpo=False, half_weights_save_dir=str(output), exp_name='voice', precision='16-mixed' if half else '32')
    s1['data']['num_workers'] = 2
    s1.update(pretrained_s1=str(pretrain / 's1v3.ckpt'),
        train_semantic_path=str(project / 'features/6-name2semantic.tsv'),
        train_phoneme_path=str(project / 'features/2-name2text.txt'),
        output_dir=str(project / 'checkpoints/gpt'))
    write_json(project / 's2.json', s2)
    write_json(project / 's1.json', s1)
    return s2, s1


def run_script(path, arguments=()):
    # Embedded Python's ._pth ignores PYTHONPATH. Set paths in the actual child.
    bootstrap = ("import os,runpy,sys;sys.path[:0]=os.environ['TACHITALK_TRAIN_PATHS'].split(os.pathsep);"
                 "sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')")
    command = [sys.executable, '-u', '-B', '-c', bootstrap, str(path)] + list(arguments)
    result = subprocess.run(command, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError('Training stage exited with code %s: %s' % (result.returncode, Path(path).name))


def setup(service, project, options, job_dir, training_root=None):
    service, project = Path(service), Path(project)
    training = Path(training_root) if training_root is not None else service / 'training'
    os.environ.update(version='v2ProPlus', hz='25hz', PYTHONIOENCODING='utf-8',
        PYTHONUNBUFFERED='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        CUDA_VISIBLE_DEVICES='' if options['gpu'] == 'cpu' else options['gpu'],
        _CUDA_VISIBLE_DEVICES='' if options['gpu'] == 'cpu' else options['gpu'],
        TACHITALK_TRAIN_STOP=str(job_dir / 'stop.request'),
        TACHITALK_TRAIN_PROGRESS=str(job_dir / 'epoch.json'),
        inp_text=str(project / 'dataset.list'), inp_wav_dir='', exp_name='voice',
        opt_dir=str(project / 'features'), i_part='0', all_parts='1',
        is_half=str(options.get('half', True) and options['gpu'] != 'cpu'),
        bert_pretrained_dir=str(service / 'GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large'),
        cnhubert_base_dir=str(service / 'GPT_SoVITS/pretrained_models/chinese-hubert-base'),
        sv_path=str(service / 'GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt'),
        pretrained_s2G=str(training / 'GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth'),
        s2config_path=str(training / 'GPT_SoVITS/configs/s2v2ProPlus.json'))
    paths = [str(training), str(service), str(service / 'GPT_SoVITS'), str(service / 'GPT_SoVITS/eres2net')]
    os.environ['PYTHONPATH'] = os.pathsep.join(paths)
    os.environ['TACHITALK_TRAIN_PATHS'] = os.pathsep.join(paths)
    sys.path[:0] = paths
    # All third-party temporary outputs stay in this owned project, not the service.
    os.chdir(project)
    for name in ('TEMP', 'TMP', 'HF_HOME', 'TORCH_HOME', 'MPLCONFIGDIR', 'NUMBA_CACHE_DIR'):
        directory = project / 'cache' / name.lower()
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)
    os.environ['PATH'] = str(service / 'runtime') + os.pathsep + os.environ.get('PATH', '')


def prepare(service, project, job, training_root=None):
    training = (Path(training_root) if training_root is not None else service / 'training') / 'GPT_SoVITS/prepare_datasets'
    features = project / 'features'
    features.mkdir(exist_ok=True)
    for name in ('ready.json', '2-name2text-0.txt', '6-name2semantic-0.tsv'):
        (features / name).unlink(missing_ok=True)
    import librosa
    records = json.loads((project / 'project.json').read_text(encoding='utf-8'))['annotations']
    for record in records:
        audio = (project / record['audio']).resolve()
        if project not in audio.parents:
            raise ValueError('Audio path escapes the project')
        seconds = librosa.get_duration(filename=str(audio))
        if not .3 <= seconds <= 54:
            raise ValueError('Audio must be 0.3-54 seconds; run audio slicing first: ' + record['name'])
    steps = [('文本与 BERT', '1-get-text.py'), ('HuBERT 与音频', '2-get-hubert-wav32k.py'),
             ('声纹特征', '2-get-sv.py'), ('语义特征', '3-get-semantic.py')]
    for index, (title, script) in enumerate(steps):
        if (job / 'stop.request').exists():
            return False
        event(title, index, len(steps))
        run_script(training / script)
    text = features / '2-name2text-0.txt'
    semantic = features / '6-name2semantic-0.tsv'
    if not text.is_file() or not semantic.is_file():
        raise ValueError('Feature extraction did not produce the expected dataset')
    text.replace(features / '2-name2text.txt')
    content = semantic.read_text(encoding='utf-8').strip()
    (features / '6-name2semantic.tsv').write_text('item_name\tsemantic_audio\n' + content + '\n', encoding='utf-8')
    records = json.loads((project / 'project.json').read_text(encoding='utf-8'))['annotations']
    for r in records:
        name = Path(r['audio']).name
        for folder, suffix in [('3-bert', '.pt'), ('4-cnhubert', '.pt'), ('5-wav32k', ''), ('7-sv_cn', '.pt')]:
            # Non-Chinese text uses generated zero BERT features during training.
            if folder == '3-bert' and r['language'] != 'zh':
                continue
            if not (features / folder / (name + suffix)).is_file():
                raise ValueError('Missing extracted feature: %s/%s' % (folder, name))
    names = {line.split('\t')[0] for line in content.splitlines()}
    if any(Path(r['audio']).name not in names for r in records):
        raise ValueError('Some audio files failed semantic extraction; see log')
    write_json(features / 'ready.json', dict(annotations=records))
    event('数据集就绪', len(steps), len(steps))
    return True


def infer(service, project, request):
    import numpy as np
    import soundfile as sf
    import torch
    select_device = runpy.run_path(str(Path(__file__).with_name('tts_service_entry.py')))['select_device']
    runtime = select_device(torch, force_cpu=request['options']['gpu'] == 'cpu')
    if runtime['device'] == 'cpu':
        torch.set_num_threads(min(8, os.cpu_count() or 1))
    # Vendor SV/text code uses service-relative model paths; configuration output
    # remains explicitly under this project's preview-infer.yaml.
    os.chdir(service)
    from TTS_infer_pack.TTS import TTS, TTS_Config
    base = service / 'GPT_SoVITS/pretrained_models'
    models = request['models']
    if not all(Path(models[k]).is_file() for k in ('gpt', 'sovits')):
        raise ValueError('The selected model pair is missing')
    gpu = runtime['device'] == 'cuda'
    config = TTS_Config(dict(custom=dict(device='cuda' if gpu else 'cpu', is_half=gpu,
        version='v2ProPlus', t2s_weights_path=models['gpt'], vits_weights_path=models['sovits'],
        bert_base_path=str(base / 'chinese-roberta-wwm-ext-large'),
        cnhuhbert_base_path=str(base / 'chinese-hubert-base'))))
    config.configs_path = str(project / 'preview-infer.yaml')
    engine = TTS(config)
    event('语音合成')
    parts, rate = [], None
    for sample_rate, audio in engine.run(dict(text=request['text'], text_lang=request['language'],
        ref_audio_path=request['reference'], prompt_text=request['prompt'], prompt_lang=request['language'],
        text_split_method='cut5', batch_size=1, parallel_infer=True, streaming_mode=False,
        return_fragment=False, split_bucket=False, speed_factor=1.0, seed=12345)):
        if rate is not None and sample_rate != rate:
            raise ValueError('Inconsistent output sample rate')
        rate = sample_rate
        parts.append(audio)
    if not parts or not any(len(p) for p in parts):
        raise ValueError('The model returned no audio')
    output = project / 'previews'
    output.mkdir(exist_ok=True)
    import uuid
    path = output / (uuid.uuid4().hex + '.wav')
    sf.write(str(path), np.concatenate(parts), rate, subtype='PCM_16')
    return str(path)


def preprocess(service, project, request, job):
    import importlib.util
    import uuid
    import soundfile as sf
    import numpy as np
    import librosa
    operation = request.get('operation', 'slice_asr')
    if operation not in ('slice_asr', 'slice', 'asr', 'separate'):
        raise ValueError('Unknown audio processing operation')
    slicing = operation in ('slice_asr', 'slice')
    recognizing = operation in ('slice_asr', 'asr')
    separating = operation == 'separate' or request.get('separate_vocals', False) or bool(request.get('uvr_model'))
    settings = dict(threshold=-34, min_length=4, min_interval=.3, max_sil_kept=.5, max_length=15)
    settings.update(request.get('slicing', {}))
    if slicing and (not -80 <= settings['threshold'] <= -10 or not .3 <= settings['min_length'] <= settings['max_length'] <= 54
            or not .05 <= settings['min_interval'] <= min(5, settings['min_length']) or not .05 <= settings['max_sil_kept'] <= 5):
        raise ValueError('Invalid slicing parameters')
    state_path = project / 'project.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if not state['annotations']:
        raise ValueError('Import source audio first')
    training = Path(request.get('training', service / 'training'))
    if slicing:
        spec = importlib.util.spec_from_file_location('training_slicer', training / 'tools/slicer2.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    recognizer, device = None, 'cpu'
    if recognizing or separating:
        import torch
        select_device = runpy.run_path(str(Path(__file__).with_name('tts_service_entry.py')))['select_device']
        runtime = select_device(torch, force_cpu=request['options']['gpu'] == 'cpu')
        device = runtime['device']
        if device == 'cpu':
            torch.set_num_threads(min(8, os.cpu_count() or 1))
        if runtime.get('reason'):
            event('运行设备', detail=runtime['reason'])
    if recognizing:
        import whisper
        model_path = Path(request.get('whisper_model') or training / 'models/asr/large-v3-turbo.pt')
        if not model_path.is_file():
            raise ValueError('内置识别模型不完整，请在更新与语音资源中修复完整训练包')
        event('加载内置多语言识别模型', current=model_path.name)
        # Keep Whisper's FP32 normalization weights; transcribe selects FP16
        # compute on CUDA. Converting the whole model breaks its LayerNorm.
        recognizer = whisper.load_model(str(model_path), device='cpu')
        recognizer.to(device)
    uvr_model = Path(request.get('uvr_model') or training / 'models/uvr/HP2_all_vocals.pth')
    if separating and not uvr_model.is_file():
        raise ValueError('内置人声分离模型不完整，请修复完整训练包')
    output = project / 'processed' / uuid.uuid4().hex
    output.mkdir(parents=True)
    rows = []
    sources = state['annotations']
    for index, record in enumerate(sources):
        if (job / 'stop.request').exists():
            return
        source = (project / record['audio']).resolve()
        if project not in source.parents:
            raise ValueError('Audio path escapes the project')
        if separating:
            event('人声分离', index, len(sources), current=record['name'])
            source = separate_vocals(service, source, output, str(uvr_model), device, training)
        audio, rate = librosa.load(str(source), sr=32000, mono=True)
        chunks = [(audio, 0, len(audio))]
        if slicing:
            event('静音切分', index, len(sources), current=record['name'])
            slicer = module.Slicer(sr=rate, threshold=settings['threshold'], min_length=round(settings['min_length']*1000),
                min_interval=round(settings['min_interval']*1000), hop_size=10, max_sil_kept=round(settings['max_sil_kept']*1000))
            # Bound long, uninterrupted speech to the supported training duration.
            limit = round(settings['max_length'] * rate)
            chunks = [(part[start:start+limit], 0, 0) for part, _, _ in slicer.slice(audio)
                      for start in range(0, len(part), limit)]
        for chunk_index, (chunk, start, end) in enumerate(chunks):
            if (job / 'stop.request').exists():
                return
            if len(chunk) < rate * .3 or not np.isfinite(chunk).all() or not np.any(chunk):
                continue
            path = output / (uuid.uuid4().hex + '.wav')
            sf.write(str(path), chunk, rate, subtype='PCM_16')
            text = '' if slicing else record.get('text', '')
            if recognizing:
                event('自动标注', chunk_index, len(chunks), current=record['name'])
                speech = librosa.resample(chunk, orig_sr=rate, target_sr=16000)
                text = recognizer.transcribe(speech, language=request['language'],
                    fp16=device == 'cuda', verbose=None)['text'].strip()
                if not text:
                    raise ValueError('ASR returned an empty annotation: ' + record['name'])
                event('自动标注', chunk_index + 1, len(chunks), current=record['name'])
            rows.append(dict(audio=path.relative_to(project).as_posix(), name=path.name,
                speaker=record['speaker'], language=request['language'], text=text))
        event('音频处理', index + 1, len(sources), current=record['name'])
    if not rows:
        raise ValueError('No usable speech segments were produced')
    # Keep imported originals and previous annotations, even when reprocessing.
    history = project / 'annotation-history'
    history.mkdir(exist_ok=True)
    write_json(history / (uuid.uuid4().hex + '.json'), state)
    state['annotations'] = rows
    (project / 'features/ready.json').unlink(missing_ok=True)
    write_json(state_path, state)
    return dict(operation=operation, input_files=len(sources), output_segments=len(rows),
                recognition_model='large-v3-turbo' if recognizing else None,
                separation_model=uvr_model.name if separating else None, device=device)


def separate_vocals(service, source, output, model_path, device, training_root=None):
    training = (Path(training_root) if training_root is not None else service / 'training') / 'tools/uvr5'
    sys.path.insert(0, str(training))
    from vr import AudioPre
    model = AudioPre(10, str(model_path), device, device == 'cuda')
    vocals, instruments = output / 'vocals', output / 'instruments'
    vocals.mkdir(exist_ok=True)
    instruments.mkdir(exist_ok=True)
    model._path_audio_(str(source), str(instruments), str(vocals), 'wav')
    candidates = list(vocals.glob('*' + source.stem + '*.wav'))
    if len(candidates) != 1:
        raise ValueError('UVR did not produce the expected vocal track')
    return candidates[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    request_path = Path(args.request).resolve()
    job = request_path.parent
    request = json.loads(request_path.read_text(encoding='utf-8'))
    service, project = Path(request['service']).resolve(), Path(request['project']).resolve()
    training = Path(request.get('training', service / 'training')).resolve()
    task, options = request['task'], request['options']
    result = dict(ok=False, task=task, error='', stopped=False)
    try:
        if options.get('version') != 'v2ProPlus':
            raise ValueError('Only v2ProPlus is supported')
        setup(service, project, options, job, training)
        if task == 'detect':
            import torch
            import pytorch_lightning
            import tensorboard
            from module.models import SynthesizerTrn
            if options['gpu'] != 'cpu':
                if not torch.cuda.is_available():
                    raise ValueError('CUDA is unavailable; select CPU or check the driver')
                x = torch.ones((2, 512), device='cuda')
                assert torch.isfinite(torch.fft.rfft(x).abs()).all()
                assert torch.isfinite(x[:, :16] @ x[:, :16].T).all()
                torch.cuda.synchronize()
            result.update(torch=str(torch.__version__), device='CPU' if options['gpu'] == 'cpu' else torch.cuda.get_device_name(0))
        elif task == 'prepare':
            prepare(service, project, job, training)
        elif task == 'preprocess':
            result.update(preprocess(service, project, request, job) or {})
        elif task == 'infer':
            result['audio'] = infer(service, project, request)
        elif task in ('sovits', 'gpt', 'train'):
            records = json.loads((project / 'project.json').read_text(encoding='utf-8'))['annotations']
            ready = json.loads((project / 'features/ready.json').read_text(encoding='utf-8'))
            if ready.get('annotations') != records:
                raise ValueError('Dataset annotations changed; prepare the dataset again')
            make_configs(service, project, options, training)
            for stage in (['sovits', 'gpt'] if task == 'train' else [task]):
                if (job / 'stop.request').exists():
                    break
                event('SoVITS 训练' if stage == 'sovits' else 'GPT 训练')
                script = training / ('GPT_SoVITS/s2_train.py' if stage == 'sovits' else 'GPT_SoVITS/s1_train.py')
                run_script(script, ['--config' if stage == 'sovits' else '--config_file', str(project / ('s2.json' if stage == 'sovits' else 's1.json'))])
        else:
            raise ValueError('Unknown training task: ' + task)
        result.update(ok=True, stopped=(job / 'stop.request').exists())
    except Exception as error:
        import traceback
        traceback.print_exc()
        result['error'] = '%s: %s' % (type(error).__name__, error)
    write_json(job / 'result.json', result)
    event('已停止' if result['stopped'] else '任务完成' if result['ok'] else '任务失败', **result)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
