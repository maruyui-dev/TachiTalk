"""单轮调度：必要数据依赖串接，LLM/TTS/播放流式重叠；麦克风独立运行。"""
import asyncio
from collections import deque
from contextlib import aclosing, nullcontext
from dataclasses import replace
import json
import logging
from itertools import count
from queue import Empty
from time import perf_counter

import aiohttp

from config import Settings, get_api_key, startup_configuration_errors
from app.services.llm import LLMClient
from app.core.models import CaptionPart, SpeechPart, StageError
from app.audio.play import AudioPlayer
from app.audio.record import AudioCapture
from app.core.conversation_input import ConversationInput
from app.core.persona import PersonaStore
from app.core.audio_input import RecordingOptions
from app.core.voice_settings import VoiceSettings
from app.core.ai_settings import AISettings
from app.services.ai_connection import run_ai_commands
from app.services.speech_services import SpeechServices
from app.audio.playback_bus import PlaybackBus
from app.core.voice_runtime import monitor_voice_services, run_voice_commands, serve_conversations


_turn_ids = count(1)  # 后台恢复并重建Pipeline时也不重用旧编号，防止Qt把新译文当旧事件。


def first_error(group):
    for error in group.exceptions:
        if isinstance(error, BaseExceptionGroup):
            yield from first_error(error)
        else:
            yield error


class Pipeline:
    def __init__(self, settings, asr, llm, tts, player, ui, profiles=None, voices=None, bus=None):
        self.settings = settings
        self.asr, self.llm, self.tts = asr, llm, tts
        self.player, self.ui = player, ui
        self.history = deque(maxlen=50)
        self.last_metrics = {}
        self.profiles = profiles if profiles is not None else PersonaStore()
        self.voices, self.bus = voices, bus

    async def recognize(self, segment):
        started = perf_counter()
        self.ui.status("识别语音")
        text = await self.asr.transcribe(segment)
        asr_done = perf_counter()
        if not text:
            self.ui.info("ASR没有有效文字，本轮不调用LLM和TTS")
            return '', started, asr_done
        return text, started, asr_done

    async def process(self, segment):
        text, started, asr_done = await self.recognize(segment)
        if text:
            await self._reply(text, started, asr_done, segment.last_speech_at, segment.duration, 'voice')

    async def process_text(self, text, submitted_at=None):
        text = text.strip()
        if not text:
            return
        started = perf_counter()
        await self._reply(text, started, started, submitted_at or started, 0.0, 'text')

    async def _reply(self, text, started, asr_done, submitted_at, segment_seconds, input_kind):
        profile = self.profiles.snapshot()
        voice = self.voices.snapshot() if self.voices is not None else None
        spoken = voice is None or voice.tts.auto_read
        neutral = '平常' if '平常' in self.settings.available_expressions else self.settings.default_expression
        self.ui.transcript(text)
        turn_id = next(_turn_ids)
        self.ui.begin_reply(turn_id)
        if not profile.switch_expression:
            self.ui.part_started(turn_id, 0, neutral)
        self.ui.status("正在等待AI生成回复")
        sentences = asyncio.Queue(maxsize=self.settings.sentence_queue_size)
        audio = asyncio.Queue(maxsize=self.settings.playback_queue_size)
        marks = {"audio_queue_high_water": 0, "sentence_queue_high_water": 0}
        spoken_parts = {}

        async def generate():
            options = {'profile': profile}
            if isinstance(self.llm, LLMClient):
                # 使用本轮已冻结的TTS设置，避免中途切服务影响当前轮协议。
                options['audio_enabled'] = spoken and (voice is None or voice.tts.provider == 'gpt_sovits')
            async with aclosing(self.llm.events(text, **options)) as stream:
                async for event in stream:
                    if isinstance(event, SpeechPart):
                        marks.setdefault("first_japanese_at", perf_counter())
                        spoken_parts[event.part_id] = event.japanese
                        if not spoken:
                            self.ui.part_started(turn_id, event.part_id, event.expression if profile.switch_expression else neutral)
                            continue
                        await sentences.put(event)
                        marks["sentence_queue_high_water"] = max(marks["sentence_queue_high_water"], sentences.qsize())
                        # 队列未满时put可能不挂起；主动让TTS先接手，避免读完缓存的LLM才开始合成。
                        await asyncio.sleep(0)
                    elif isinstance(event, CaptionPart):
                        marks.setdefault("first_chinese_at", perf_counter())
                        self.ui.caption(turn_id, event.part_id, event.chinese)
                    else:
                        raise StageError("LLM", "出现不支持的回复事件")
            if spoken:
                await sentences.put(None)

        async def synthesize():
            voice_expression = None  # 每轮独立，下一轮可以重新选择主情绪。
            audio_reference = None
            first = True
            while True:
                sentence = await sentences.get()
                if sentence is None:
                    marks['tts_finished_at'] = perf_counter()
                    await audio.put(None)
                    return
                if first:
                    voice_expression = sentence.expression
                    audio_reference = sentence.audio_reference
                    first = False
                sentence = replace(sentence, voice_expression=voice_expression, audio_reference=audio_reference)
                if "tts_started_at" not in marks:
                    marks["tts_started_at"] = perf_counter()
                    self.ui.status("正在合成语音，等待首段音频")
                stream = self.tts.stream(sentence, options=voice.tts) if voice is not None else self.tts.stream(sentence)
                async with aclosing(stream) as stream:
                    async for chunk in stream:
                        marks.setdefault("tts_first_chunk_at", perf_counter())
                        await audio.put(chunk)
                        marks["audio_queue_high_water"] = max(marks["audio_queue_high_water"], audio.qsize())

        def first_audio(submitted_at):
            if self.bus is not None:
                self.bus.started()
            marks["first_audio_at"] = submitted_at
            self.ui.status("播放回复；本轮完成后可继续对话")

        def part_started(part_id, expression, submitted_at):
            if self.bus is not None and part_id in spoken_parts:
                self.bus.remember(spoken_parts[part_id])
            self.ui.part_started(turn_id, part_id, expression if profile.switch_expression else neutral)

        try:
            if not spoken:
                await generate()
            else:
                async with (self.bus.lease() if self.bus is not None else nullcontext()):
                    async with asyncio.TaskGroup() as tasks:
                        tasks.create_task(generate(), name="llm-stream")
                        tasks.create_task(synthesize(), name="tts-stream")
                        tasks.create_task(self.player.play(audio, first_audio, part_started), name="playback")
        except ExceptionGroup as group:
            errors = list(first_error(group))
            for error in errors:
                if isinstance(error, StageError):
                    raise error from group
            raise StageError("调度", f"本轮任务失败（{type(errors[0]).__name__}）") from group
        finally:
            self.ui.end_reply(turn_id)

        if spoken and "first_audio_at" not in marks:
            raise StageError("播放", "本轮没有可播放的音频")
        metrics = {
            "asr_seconds": asr_done - started,
            "first_japanese_seconds": marks["first_japanese_at"] - asr_done,
            "first_chinese_seconds": marks["first_chinese_at"] - asr_done if "first_chinese_at" in marks else None,
            "tts_first_chunk_seconds": marks["tts_first_chunk_at"] - marks["tts_started_at"] if spoken else None,
            "japanese_to_tts_seconds": marks['tts_started_at'] - marks['first_japanese_at'] if spoken else None,
            "first_chunk_to_play_seconds": marks['first_audio_at'] - marks['tts_first_chunk_at'] if spoken else None,
            "japanese_to_first_audio_seconds": marks['first_audio_at'] - marks['first_japanese_at'] if spoken else None,
            # Includes bounded-queue backpressure and waiting for later LLM parts;
            # isolated synthesis throughput is measured by benchmark_tts.py.
            "tts_stream_seconds": marks['tts_finished_at'] - marks['tts_started_at'] if spoken else None,
            "speech_end_to_first_audio": marks["first_audio_at"] - submitted_at if spoken else None,
            "round_seconds": perf_counter() - started,
            "audio_queue_high_water": marks["audio_queue_high_water"],
            "sentence_queue_high_water": marks["sentence_queue_high_water"],
            "segment_seconds": segment_seconds,
            "input_kind": input_kind,
            "spoken": spoken,
        }
        self.last_metrics = metrics
        self.history.append(metrics)
        if spoken:
            logging.getLogger('tachitalk').debug(
                'TTS链路：日文就绪到接手 %.3fs；接手到首PCM %.3fs；首PCM到写设备 %.3fs；'
                'TTS流水线（含队列背压及等后续分句） %.3fs',
                metrics['japanese_to_tts_seconds'], metrics['tts_first_chunk_seconds'],
                metrics['first_chunk_to_play_seconds'], metrics['tts_stream_seconds'])
        self.ui.timings(metrics)


async def check_service(session, settings, name, *, api_key=''):
    """只查模型清单/本地接口描述，不在启动时生成收费的回复。"""
    if name == "ASR":
        url = settings.asr_url.rsplit("/audio/", 1)[0] + "/models"
        key, model = get_api_key("asr", api_key), settings.asr_model
    elif name == "LLM":
        url = settings.llm_base_url.rstrip("/") + "/models"
        key, model = get_api_key("llm", api_key), settings.llm_model
    else:
        url = settings.tts_url.rsplit("/tts", 1)[0] + "/openapi.json"
        key, model = None, None
    try:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        async with session.get(url, headers=headers, allow_redirects=False) as response:
            if response.status != 200:
                raise StageError.http(name, response.status)
            body = bytearray()
            async for block in response.content.iter_chunked(8192):
                body.extend(block)
                if len(body) > 1024 * 1024:
                    raise StageError(name, "启动检查响应超过1MiB上限")
            data = json.loads(body)
            if model is not None:
                models = data.get("data", [])
                if model not in [item.get("id") for item in models if isinstance(item, dict)]:
                    raise StageError(name, "配置的模型不在账户模型清单中，请在控制面板重新选择模型", 404)
            elif "post" not in data.get("paths", {}).get("/tts", {}):
                raise StageError("TTS", "服务未提供POST /tts，请启动GPT-SoVITS api_v2.py")
    except StageError:
        raise
    except (aiohttp.ClientError, TimeoutError) as error:
        extra = "；请启动本地GPT-SoVITS服务并检查TTS_URL" if name == "TTS" else "；请检查网络和服务地址"
        raise StageError(name, f"启动检查连接失败或超时（{type(error).__name__}）{extra}") from error
    except (ValueError, AttributeError, TypeError) as error:
        raise StageError(name, "启动检查响应格式不正确") from error


async def check_services(session, settings, names=("ASR", "LLM", "TTS"), *, api_keys=None):
    results = await asyncio.gather(*(check_service(session, settings, name, api_key=(api_keys or {}).get(name, "")) for name in names),
                                   return_exceptions=True)
    return dict(zip(names, results))


async def show_capture_notices(capture, ui):
    while True:
        try:
            while True:
                kind, text = capture.notices.get_nowait()
                if kind == "error":
                    ui.error(StageError("录音", text))
                elif kind == "speech":
                    ui.status(text)
                else:
                    ui.info(text)
        except Empty:
            await asyncio.sleep(.1)


async def wait_for_manual_restart(ui):
    ui.status("等待配置修复；程序保持运行，请Ctrl+C手动结束、修复配置后重启")
    await asyncio.Event().wait()


async def run_application(settings: Settings, ui, inputs=None, profiles=None, voices=None, ai=None, expressions=None, audio=None, history=None):
    inputs = inputs if inputs is not None else ConversationInput(
        audio_options=RecordingOptions(device=settings.input_device, sample_rate=settings.sample_rate))
    profiles = profiles if profiles is not None else PersonaStore()
    voices = voices if voices is not None else VoiceSettings(settings)
    ai = ai if ai is not None else AISettings(settings)
    selected = voices.snapshot()
    inputs.set_voice_preferences(auto_read=selected.tts.auto_read, auto_send=selected.asr.auto_send, interrupt=selected.tts.interrupt)
    inputs.bind_loop()
    capture = player = notice_task = None
    timeout = aiohttp.ClientTimeout(total=settings.request_timeout, connect=settings.connect_timeout,
                                    sock_read=settings.read_timeout)
    try:
        # 设备检查和电平测试不依赖线上API Key；后台预检失败也保留采集线程。
        capture = AudioCapture(settings, inputs.gate, controls=inputs)
        capture.start()
        notice_task = asyncio.create_task(show_capture_notices(capture, ui), name='capture-notices')
        # 文字模式不需要ASR Key；ASR单独在录音启用时给出配置和鉴权错误。
        # 服务地址、Key和模型由各运行配置预检，填写不完整时保留面板与后台命令。
        errors = startup_configuration_errors(settings, services=(), check_references=False, check_service_fields=False)
        if errors:
            for message in errors:
                ui.error(StageError('配置', message))
            await wait_for_manual_restart(ui)
        player = AudioPlayer(settings)
        player.voices = voices
        async with aiohttp.ClientSession(timeout=timeout, read_bufsize=16384,
                                        connector=aiohttp.TCPConnector(limit=6, limit_per_host=2)) as session:
            speech = SpeechServices(session, settings, voices)
            bus = PlaybackBus(player, voices, inputs)
            pipeline = Pipeline(settings, speech, None, speech, player, ui, profiles, voices, bus)
            service_task = asyncio.create_task(monitor_voice_services(session, settings, inputs, voices, speech, ui, check_service, ai), name='service-checks')
            commands_task = asyncio.create_task(run_voice_commands(settings, voices, speech, bus, ui), name='voice-settings-commands')
            ai_task = asyncio.create_task(run_ai_commands(session, settings, ai, ui, inputs, expressions, audio), name='ai-settings-commands')
            for task in (service_task, commands_task, ai_task):
                task.add_done_callback(lambda _: inputs.wake())
            try:
                await serve_conversations(pipeline, inputs, voices, bus, ui, (service_task, commands_task, ai_task),
                                          lambda: LLMClient(session, settings, profiles, ai=ai, expressions=expressions, audio=audio,
                                              audio_active=lambda: voices.snapshot().tts.auto_read
                                              and voices.snapshot().tts.provider == 'gpt_sovits', history=history))
            finally:
                service_task.cancel()
                commands_task.cancel()
                ai_task.cancel()
                await asyncio.gather(service_task, commands_task, ai_task, return_exceptions=True)
                await speech.close()
    finally:
        inputs.unbind_loop()
        if notice_task is not None:
            notice_task.cancel()
            await asyncio.gather(notice_task, return_exceptions=True)
        if capture is not None:
            try:
                await asyncio.to_thread(capture.close)
            except Exception as error:
                ui.error(error)
            ui.info(f'采集统计：语音队列峰值{capture.queue_high_water}；丢弃片段{capture.dropped_segments}；设备输入溢出{capture.overflow_count}')
        if player is not None:
            try:
                await player.close()
            except Exception as error:
                ui.error(error)
