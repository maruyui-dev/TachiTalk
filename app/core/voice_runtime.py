"""语音服务预检、试听命令及可打断的对话监督循环。"""
import asyncio
from contextlib import aclosing
from time import perf_counter
import wave

import aiohttp

from app.core.models import AudioChunk, AudioFormat, AudioSegment, SpeechPart, StageError
from app.core.voice_settings import ReferencePreview
from app.services.catalog import fetch_asr_models
from app.services.speech_services import preview_language
from app.services.ai_connection import check_configuration


FATAL = (400, 401, 402, 403, 404, 422)


def useful_error(error):
    if isinstance(error, BaseExceptionGroup):
        return useful_error(error.exceptions[0])
    return error


async def monitor_voice_services(session, settings, inputs, voices, speech, ui, check_llm, ai=None):
    tasks, seen, retries, previous = {}, {}, {}, {}

    async def check(name, snapshot, ai_snapshot):
        if name == 'LLM':
            if ai_snapshot is not None:
                detail = await check_configuration(session, ai_snapshot.options)
                ai.health(ai_snapshot.revision, 'ready', detail)
                return
            return await check_llm(session, settings, 'LLM')
        if name == 'ASR':
            options = snapshot.asr
            options.validate()
            if options.provider == 'whisper':
                await speech.whisper.request({'operation': 'check'}, min(options.timeout, 15))
            elif options.models_url:
                try:
                    names = await fetch_asr_models(session, options)
                    if options.model not in names and options.provider == 'silicon':
                        raise ValueError('所选ASR模型不在当前服务返回的列表中，请重新选择或确认模型ID')
                except StageError as error:
                    if error.status != 404 or options.provider == 'silicon':
                        raise
                    ui.info('ASR服务不提供模型列表；已保留手动填写的模型，将在首次识别时验证接口')
            return
        options = snapshot.tts
        options.validate()
        if options.provider == 'system':
            names = [voice['name'] for voice in await speech.system.voices()]
            if options.voice not in names:
                raise ValueError('所选系统音色尚未安装，请获取系统音色后重新选择')
            await speech.system.request({'operation': 'check', 'voice': options.voice}, min(options.timeout, 15))
        elif options.provider == 'gpt_sovits':
            service = getattr(voices, 'local_service', None)
            if service is not None:
                await service.ensure(options)
            url = options.url.rsplit('/tts', 1)[0] + '/openapi.json'
            headers = {'Authorization': f'Bearer {options.api_key}'} if options.api_key else {}
            async with session.get(url, headers=headers, allow_redirects=False,
                                   timeout=aiohttp.ClientTimeout(total=min(options.timeout, 15))) as response:
                if response.status != 200:
                    raise StageError.http('TTS', response.status)
        # 云TTS不通过生成收费音频来预检；参数在此验证，鉴权在首次合成时明确报告。

    try:
        while True:
            snapshot = voices.snapshot()
            ai_snapshot = ai.snapshot() if ai is not None else None
            signatures = {'LLM': ai_snapshot.revision if ai_snapshot is not None else 0,
                          'ASR': snapshot.asr_revision, 'TTS': snapshot.tts_revision}
            service = getattr(voices, 'local_service', None)
            suspended = getattr(voices, 'training_active', False)
            if service is not None and hasattr(service, 'configuration_signature'):
                signatures['TTS'] = (snapshot.tts_revision, service.configuration_signature(), suspended)
            desired = {'LLM'}
            if inputs.recording_state()[0]:
                desired.add('ASR')
            if snapshot.tts.auto_read and not suspended:
                desired.add('TTS')
            for name, signature in signatures.items():
                if seen.get(name) != signature:
                    seen[name] = signature
                    inputs.invalidate_service(name)
                    retries.pop(name, None)
                    previous.pop(name, None)
                    if name in tasks:
                        old = tasks.pop(name)
                        old.cancel()
                        await asyncio.gather(old, return_exceptions=True)
            for name, task in tuple(tasks.items()):
                if name not in desired:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    del tasks[name]
            for name in desired:
                if (name not in tasks and not inputs.service_ready(name) and not inputs.service_blocked(name)
                        and perf_counter() >= retries.get(name, 0)):
                    if name == 'LLM' and ai_snapshot is not None:
                        ai.health(ai_snapshot.revision, 'checking', '正在检查模型列表与鉴权，不生成回复')
                    tasks[name] = asyncio.create_task(check(name, snapshot, ai_snapshot), name=f'voice-check-{name}')
            for name, task in tuple(tasks.items()):
                if not task.done():
                    continue
                del tasks[name]
                if name == 'LLM' and ai is not None and ai.snapshot().revision != seen[name]:
                    await asyncio.gather(task, return_exceptions=True)
                    continue
                try:
                    task.result()
                except asyncio.CancelledError:
                    continue
                except Exception as error:
                    if name == 'LLM' and ai is not None:
                        ai.health(seen[name], 'error', str(error))
                    if str(error) != previous.get(name):
                        ui.error(error if isinstance(error, StageError) else StageError(name, str(error)))
                        previous[name] = str(error)
                    if isinstance(error, ValueError) or isinstance(error, StageError) and error.status in FATAL:
                        inputs.block_service(name)
                    else:
                        retries[name] = perf_counter() + settings.retry_delay
                else:
                    inputs.set_service_ready(name)
                    ui.info(f'{name}当前服务配置已就绪')
            await asyncio.sleep(.1)
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


async def run_voice_commands(settings, voices, speech, bus, ui):
    seen, tasks = {}, {}

    async def perform(name, command):
        try:
            if name == 'models':
                value = await fetch_asr_models(speech.session, command.payload)
            elif name == 'speakers':
                value = await bus.player.output_devices()
            elif name == 'voices':
                value = await speech.system.voices()
                if not value:
                    raise ValueError('未找到已安装的系统音色，请在Windows语言和语音设置中安装语音包')
            elif not command.payload:
                value = '试听已结束'
            else:
                reference_preview = command.payload if isinstance(command.payload, ReferencePreview) else None
                if reference_preview is not None:
                    text, options = reference_preview.text, voices.snapshot().tts
                    if reference_preview.raw:
                        text = reference_preview.reference.prompt
                    if not reference_preview.raw and options.provider != 'gpt_sovits':
                        raise ValueError('参考音频试读需要在语音与音频页选择GPT-SoVITS')
                else:
                    text, options = command.payload
                if reference_preview is None or not reference_preview.raw:
                    options.validate()
                queue = asyncio.Queue(maxsize=settings.playback_queue_size)
                part = SpeechPart(0, text, settings.default_expression,
                                  audio_reference=reference_preview.reference if reference_preview else None)

                async def synthesize():
                    if reference_preview is not None and reference_preview.raw:
                        from app.core.audio_library import inspect_audio
                        await asyncio.to_thread(inspect_audio, reference_preview.reference.path)
                        with wave.open(reference_preview.reference.path, 'rb') as source:
                            format_ = AudioFormat(source.getframerate(), source.getnchannels(), 2)
                            while block := source.readframes(max(1, source.getframerate() * settings.frame_ms // 1000)):
                                await queue.put(AudioChunk(block, format_, part_id=0))
                        await queue.put(None)
                        return
                    async with aclosing(speech.stream(part, options=options, language=preview_language(text))) as stream:
                        async for chunk in stream:
                            await queue.put(chunk)
                    await queue.put(None)

                async with bus.lease():
                    async with asyncio.TaskGroup() as group:
                        group.create_task(synthesize())
                        group.create_task(bus.player.play(queue, lambda _: bus.started(), lambda *_: bus.remember(text)))
                value = '试听完成'
        except asyncio.CancelledError:
            voices.complete(name, command.id, value='已结束')
            raise
        except Exception as error:
            error = useful_error(error)
            voices.complete(name, command.id, error=str(error))
            ui.error(error if isinstance(error, StageError) else StageError('语音设置', str(error)))
        else:
            voices.complete(name, command.id, value=value)

    try:
        while True:
            for name, command in voices.commands().items():
                if seen.get(name) == command.id:
                    continue
                seen[name] = command.id
                old = tasks.pop(name, None)
                if old is not None:
                    old.cancel()
                    await asyncio.gather(old, return_exceptions=True)
                tasks[name] = asyncio.create_task(perform(name, command), name=f'voice-command-{name}')
            await asyncio.sleep(.05)
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


async def serve_conversations(pipeline, inputs, voices, bus, ui, background_tasks, llm_factory):
    current = None

    def block_failed_service(error):
        if not isinstance(error, StageError) or error.status not in FATAL:
            return
        ai = getattr(pipeline.llm, 'ai', None)
        revision = getattr(error, 'configuration_revision', None)
        if error.stage == 'LLM' and ai is not None and revision is not None and revision != ai.snapshot().revision:
            ui.info('旧AI配置的请求已结束，当前配置按新的检查结果继续运行')
            return
        inputs.block_service(error.stage)

    async def reply(request, text=None, started=None, asr_done=None):
        try:
            if isinstance(request.payload, AudioSegment):
                await pipeline._reply(text, started, asr_done, request.payload.last_speech_at,
                                      request.payload.duration, 'voice')
            else:
                await pipeline.process_text(request.payload, request.submitted_at)
        except asyncio.CancelledError:
            ui.info('旧回复或试听已结束，已清理待播音频')
        except Exception as error:
            ui.error(error if isinstance(error, StageError) else StageError('对话', str(error)))
            block_failed_service(error)

    try:
        while True:
            inputs.clear_wake()
            for task in background_tasks:
                if task.done():
                    task.result()
            if current is not None and current.done():
                current.result()
                current = None
            request = inputs.take_next()
            if request is not None:
                transferred = False
                try:
                    if isinstance(request.payload, AudioSegment):
                        text, started, asr_done = await pipeline.recognize(request.payload)
                        if not text:
                            continue
                        if bus.is_echo(text, request.payload.last_speech_at):
                            ui.info('识别内容与刚播放的桌宠台词一致，本次按回声忽略')
                            continue
                        if not voices.snapshot().asr.auto_send:
                            voices.set_draft(text)
                            inputs.set_review_pending(True)
                            ui.info('识别文字已放入ASR确认框，编辑后点击发送')
                            continue
                    if current is not None and not current.done():
                        if voices.snapshot().tts.interrupt:
                            current.cancel()
                        await asyncio.gather(current, return_exceptions=True)
                    if pipeline.llm is None:
                        pipeline.llm = llm_factory()
                    current = asyncio.create_task(
                        reply(request, text, started, asr_done) if isinstance(request.payload, AudioSegment)
                        else reply(request), name='conversation-reply')
                    # 即使协程尚未开始便被取消，也必须释放输入所有权。
                    current.add_done_callback(lambda _: inputs.finish_turn())
                    transferred = True
                except Exception as error:
                    ui.error(error if isinstance(error, StageError) else StageError('对话', str(error)))
                    block_failed_service(error)
                finally:
                    if not transferred:
                        inputs.finish_turn()
                continue
            ui.status(inputs.snapshot().message)
            wake = asyncio.create_task(inputs.wait_changed())
            try:
                await asyncio.wait([wake] + ([current] if current is not None else []), return_when=asyncio.FIRST_COMPLETED)
            finally:
                wake.cancel()
                await asyncio.gather(wake, return_exceptions=True)
    finally:
        if current is not None:
            current.cancel()
            await asyncio.gather(current, return_exceptions=True)
