"""固定文本的本地TTS对照；不加载LLM/ASR、不打开麦克风。用项目venv运行。"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

from app.audio.play import AudioPlayer
from app.core.voice_settings import TTSOptions
from app.paths import TTS_SERVICE_DIR
from app.services.local_tts import LocalTTSService
from app.services.owned_process import spawn_hidden
from app.services.tts import WaveStreamDecoder
from config import REF_MAP, Settings
from scripts.start_tts import service_environment


TEXT = '今日はよく頑張ったね。少し休んでから一緒にお茶を飲もう。'


class Console:
    def info(self, text):
        print(text, flush=True)

    status = info


async def request(session, url, payload, settings, directory, name, playback):
    marks = {}
    pcm = bytearray()
    decoder = WaveStreamDecoder(settings.frame_ms, settings.max_tts_seconds)
    queue = asyncio.Queue(maxsize=settings.playback_queue_size)
    player = AudioPlayer(settings) if playback else None
    started = perf_counter()

    async def produce():
        async with session.post(url, json=payload, allow_redirects=False) as response:
            response.raise_for_status()
            marks['headers_seconds'] = perf_counter() - started
            async for block in response.content.iter_chunked(4096):
                for chunk in decoder.feed(block):
                    marks.setdefault('first_pcm_seconds', perf_counter() - started)
                    pcm.extend(chunk.pcm)
                    if player:
                        await queue.put(chunk)
            for chunk in decoder.finish():
                pcm.extend(chunk.pcm)
                if player:
                    await queue.put(chunk)
        marks['response_complete_seconds'] = perf_counter() - started
        if player:
            await queue.put(None)

    def first_audio(at):
        marks['first_device_submit_seconds'] = at - started
        # PortAudio估计的DAC延迟，不是麦克风测得的声学出声时间。
        marks['device_latency_seconds'] = player.stream.latency
        marks['estimated_first_dac_seconds'] = at - started + player.stream.latency

    try:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(produce())
            if player:
                tasks.create_task(player.play(queue, first_audio))
        marks['playback_finished_seconds'] = perf_counter() - started if player else None
        marks['underflows'] = player.underflows if player else None
    finally:
        if player:
            await player.close()
    fmt = decoder.format
    if not any(pcm):
        raise RuntimeError('TTS returned only silence')
    with wave.open(str(directory / (name + '.wav')), 'wb') as output:
        output.setparams((fmt.channels, fmt.sample_width, fmt.sample_rate, 0, 'NONE', ''))
        output.writeframes(pcm)
    marks.update(name=name, mode=payload['streaming_mode'], playback=playback,
                 pcm_sha256=hashlib.sha256(pcm).hexdigest(),
                 audio_seconds=len(pcm) / fmt.bytes_per_second)
    print(json.dumps(marks, ensure_ascii=False), flush=True)
    return marks


async def main(args):
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    if args.runs < 1 or args.play_runs < 1:
        raise ValueError('runs/play-runs must be positive')
    service = LocalTTSService(Console(), state_dir=directory / 'service')
    url = f'http://127.0.0.1:{args.port}/tts'
    options = TTSOptions(url=url)
    reference, prompt = REF_MAP[args.expression]
    payload = dict(text=args.text, text_lang='ja', prompt_lang='ja', ref_audio_path=reference,
                   prompt_text=prompt, media_type='wav', text_split_method='cut5', batch_size=1,
                   split_bucket=False, top_k=15, top_p=1.0, temperature=1.0, seed=12345,
                   repetition_penalty=1.35, speed_factor=1.0, fragment_interval=0.3,
                   sample_steps=32, super_sampling=False)
    report = {'text': args.text, 'reference': reference, 'prompt': prompt, 'payload': payload, 'runs': []}
    try:
        if args.launch:
            if service.port_in_use(args.port):
                raise RuntimeError('测试端口已占用；请选择空闲端口，不会关闭已有服务')
            started = perf_counter()
            if args.entry:
                service.state_dir.mkdir(parents=True, exist_ok=True)
                service.log = (service.state_dir / 'service.log').open('ab', buffering=0)
                command = [str(TTS_SERVICE_DIR / 'runtime/python.exe'), '-u', '-B', str(args.entry.resolve()),
                           '--service-root', str(TTS_SERVICE_DIR), '--state-dir', str(service.state_dir),
                           '--port', str(args.port)]
                service.process, service.job = spawn_hidden(command, cwd=TTS_SERVICE_DIR,
                    env=service_environment(), stdout=service.log, stderr=service.log)
                service.endpoint = f'http://127.0.0.1:{args.port}/openapi.json'
            await service.ensure(options)
            report['service_ready_seconds'] = perf_counter() - started
            for name in ('runtime_status', 'warmup_status'):
                path = service.state_dir / (name + '.json')
                if path.exists():
                    report[name] = json.loads(path.read_text(encoding='utf-8'))
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
            for mode in args.modes:
                payload.update(streaming_mode=mode, parallel_infer=mode == 1)
                if args.cold_play:
                    result = await request(session, url, payload, settings, directory, f'mode{mode}_cold_play', True)
                    report['runs'].append(result)
                for index in range(args.runs):
                    name = f'mode{mode}_{index}'
                    result = await request(session, url, payload, settings, directory, name, False)
                    report['runs'].append(result)
                if args.play:
                    for index in range(args.play_runs):
                        result = await request(session, url, payload, settings, directory, f'mode{mode}_play{index}', True)
                        report['runs'].append(result)
            if args.check_recovery:
                # Close a live HTTP stream early, then require another real synthesis.
                async with session.post(url, json=payload) as response:
                    response.raise_for_status()
                    await response.content.read(4096)
                result = await request(session, url, payload, settings, directory, 'after_cancel', False)
                report['runs'].append(result)
                async with session.post(url, json=dict(payload, text_lang='invalid')) as response:
                    if response.status != 400:
                        raise RuntimeError('invalid language did not fail as expected')
                    await response.read()
                result = await request(session, url, payload, settings, directory, 'after_error', False)
                report['runs'].append(result)
                reference, prompt = REF_MAP['疑问']
                result = await request(session, url, dict(payload, ref_audio_path=reference, prompt_text=prompt),
                                       settings, directory, 'changed_reference', False)
                report['runs'].append(result)
                report['recovery_checks'] = 'passed: HTTP cancel, rejected request, changed reference'
        (directory / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        await service.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=19880)
    parser.add_argument('--launch', action='store_true', help='启动并在结束时关闭独立测试服务')
    parser.add_argument('--entry', type=Path, help='可选的本地性能分析启动器')
    parser.add_argument('--modes', type=int, nargs='+', choices=(1, 2, 3), default=[1])
    parser.add_argument('--runs', type=int, default=4, help='第0次为本进程第一次请求，其后为热态')
    parser.add_argument('--play', action='store_true', help='另外实际播放一轮；默认只合成')
    parser.add_argument('--play-runs', type=int, default=1)
    parser.add_argument('--cold-play', action='store_true', help='下载测试前先测一次实际播放；需launch保证是新进程首请求')
    parser.add_argument('--check-recovery', action='store_true', help='验证取消、400错误、换参考后仍可正常合成')
    parser.add_argument('--text', default=TEXT)
    parser.add_argument('--expression', choices=tuple(REF_MAP), default='平常')
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
