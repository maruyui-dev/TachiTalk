"""批量设置服务配置和录音参数；控件回填后仅向后台提交一次完整设置。"""
from dataclasses import asdict
from config import Settings
from PySide6.QtCore import QSignalBlocker
from app.core.ai_settings import provider_defaults
from app.core.voice_settings import default_voice_profiles


def profile_objects(panel):
    ai, voice = panel.ai_controls, panel.voice_controls
    settings = Settings()
    asr, tts = default_voice_profiles(settings)
    groups = {'ai': provider_defaults(settings) | ai._cache,
              'asr': asr | voice._asr_cache, 'tts': tts | voice._tts_cache}
    for stage, options in (('ai', ai.read_options()), ('asr', voice.read_asr_options()), ('tts', voice.read_tts_options())):
        groups[stage][options.provider] = options
    return groups


def capture_profiles(panel):
    return {stage: {name: asdict(options) for name, options in group.items()}
            for stage, group in profile_objects(panel).items()}


def apply_profiles(panel, profiles):
    panel.ai_controls._cache = dict(profiles['ai'])
    panel.voice_controls._asr_cache = dict(profiles['asr'])
    panel.voice_controls._tts_cache = dict(profiles['tts'])


def commit_ai(panel, values):
    control = panel.ai_controls
    control._provider = control.PROVIDERS[values['aiProviderCombo']]
    control._models.pop(control._provider, None)
    with QSignalBlocker(control.w('llmModelCombo')):
        control.w('llmModelCombo').clear()
        control.w('llmModelCombo').setCurrentText(values['llmModelCombo'])
    control.custom_key_visible()
    options = control.read_options()
    control._cache[options.provider] = options
    control.save()


def commit_audio(panel, values):
    audio, voice = panel.audio_controls, panel.voice_controls
    voice.model_timer.stop()
    voice._requested.clear()
    voice._seen.clear()
    voice._asr_provider = voice.ASR_PROVIDERS[values['asrProviderCombo']]
    voice._tts_provider = voice.TTS_PROVIDERS[values['ttsProviderCombo']]
    with QSignalBlocker(voice.w('asrModelCombo')):
        voice.w('asrModelCombo').clear()
        if values['asrModelCombo']:
            voice.w('asrModelCombo').addItem(values['asrModelCombo'])
    for cache, options in ((voice._asr_cache, voice.read_asr_options()), (voice._tts_cache, voice.read_tts_options())):
        cache[options.provider] = options
    if voice.voices is not None:
        voice.voices.discard_commands('models', 'voices')
        if voice.voices.result('preview').running:
            voice.voices.request('preview', None)
        voice.save_asr()
        voice.save_tts()
        voice.save_output()
        voice.request_models()
    voice.show_groups()
    audio.test_timer.stop()
    audio._device_disabled = values['microphoneCombo'] == -1
    if audio.inputs is not None:
        audio.inputs.set_testing(False)
        index = values['microphoneCombo']
        device_name = next((item.name for item in audio.inputs.audio_status().devices if item.index == index), '')
        audio.inputs.configure_audio(device=None if index == -1 else index, device_name=device_name,
                                     mode=audio.MODES[values['recordingModeCombo']],
                                     sample_rate=int(values['sampleRateCombo'].split()[0]),
                                     volume=values['inputVolumeSlider'], trim_silence=values['trimSilenceCheck'])
        if index == -1:
            audio.inputs.set_recording(False)
        audio._result = ''
        audio.refresh()
    audio.change_shortcut()
    audio.volume_label.setText(f"{values['inputVolumeSlider']}%")
    voice.w('outputVolumeSliderValue').setText(f"{values['outputVolumeSlider']}%")
