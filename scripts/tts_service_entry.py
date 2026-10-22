"""由随包Python运行（兼容Python 3.9）；配置写入用户目录，模型保持只读。"""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys


def probe_cuda(torch):
    """覆盖声纹FFT/复数abs、矩阵乘与卷积；CUDA可见不代表这些算子能运行。"""
    with torch.inference_mode():
        audio = torch.ones((2, 512), device='cuda', dtype=torch.float16)
        spectrum = torch.fft.rfft(audio).abs()
        matrix = audio[:, :16] @ audio[:, :16].T
        convolution = torch.nn.functional.conv1d(audio.unsqueeze(1),
            torch.ones((8, 1, 3), device='cuda', dtype=torch.float16))
        if not all(torch.isfinite(value).all().item() for value in (spectrum, matrix, convolution)):
            raise RuntimeError('CUDA运算自检产生非有限数值')
        torch.cuda.synchronize()


def select_device(torch, force_cpu=False):
    result = {'device': 'cpu', 'is_half': False, 'gpu': '', 'reason': '',
              'torch': str(torch.__version__), 'cuda': str(torch.version.cuda)}
    if force_cpu:
        result['reason'] = '已选择CPU兼容模式'
        return result
    try:
        if not torch.cuda.is_available():
            result['reason'] = 'CUDA不可用，使用CPU兼容模式；请检查NVIDIA显卡及驱动'
            return result
        result['gpu'] = torch.cuda.get_device_name(0)
        probe_cuda(torch)
    except Exception as error:
        # 只对GPU兼容检测回退，模型损坏等后续错误仍会明确失败。
        detail = str(error).strip().splitlines()
        result['reason'] = f'CUDA运算自检失败（{type(error).__name__}）：' + (detail[-1][:300] if detail else '')
        try:
            torch.cuda.empty_cache()
        except RuntimeError:
            pass
        return result
    result.update(device='cuda', is_half=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--service-root', required=True)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--device', choices=('auto', 'cpu'), default='auto')
    args = parser.parse_args()
    root, state = Path(args.service_root).resolve(), Path(args.state_dir).resolve()
    state.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    sys.path.insert(0, str(root))
    import torch
    import yaml
    with (root / 'GPT_SoVITS/configs/tts_infer.yaml').open(encoding='utf-8') as source:
        configs = yaml.safe_load(source)
    custom = configs['custom']
    for field in ('bert_base_path', 'cnhuhbert_base_path', 't2s_weights_path', 'vits_weights_path'):
        custom[field] = str((root / custom[field]).resolve())
    runtime = select_device(torch, force_cpu=args.device == 'cpu')
    custom.update(device=runtime['device'], is_half=runtime['is_half'])
    if runtime['device'] == 'cpu':
        torch.set_num_threads(min(8, os.cpu_count() or 1))
    (state / 'runtime_status.json').write_text(json.dumps(runtime, ensure_ascii=False), encoding='utf-8')
    print('TachiTalk runtime:', json.dumps(runtime, ensure_ascii=False), flush=True)
    destination = state / 'tts_infer.yaml'
    with destination.open('w', encoding='utf-8') as output:
        yaml.safe_dump({'custom': custom}, output, allow_unicode=False)
    print('TachiTalk TTS device:', custom['device'], flush=True)
    os.environ['TACHITALK_TTS_WARMUP_REPORT'] = str(state / 'warmup_status.json')
    sys.argv = [str(root / 'api_v2.py'), '-a', '127.0.0.1', '-p', str(args.port), '-c', str(destination)]
    runpy.run_path(str(root / 'api_v2.py'), run_name='__main__')


if __name__ == '__main__':
    main()
