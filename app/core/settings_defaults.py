"""按页面独立维护恢复默认值；本页所有服务的API Key在重置时清空。"""

PAGE_DEFAULTS = {
    'characterPage': {
        'expressionCombo': '平常', 'scaleSlider': 180, 'rangeCombo': 0, 'rangeSlider': 50,
        'fixedCheck': True, 'topCheck': True, 'maxBubblesSpin': 4, 'bubbleGapSpin': 4,
        'recordingEnabledCheck': True, 'messageEdit': '', 'choosePinkButton': True,
        'chooseBlueButton': False,
    },
    'dialoguePage': {
        'characterNameEdit': '茉子', 'userNameEdit': '', 'replyLanguageCombo': 0,
        'personaEdit': '', 'streamReplyCheck': True, 'expressionLinkCheck': True, 'contextTurnsCombo': 0,
    },
    'audioPage': {
        'microphoneCombo': None, 'recordingModeCombo': 0, 'recordingShortcut': 'Ctrl+Space',
        'sampleRateCombo': '16000 Hz', 'inputVolumeSlider': 77,
        'asrProviderCombo': 0, 'asrUrlEdit': 'https://api.siliconflow.cn/v1/audio/transcriptions',
        'asrModelsUrlEdit': 'https://api.siliconflow.cn/v1/models',
        'asrModelCombo': 'FunAudioLLM/SenseVoiceSmall', 'asrLanguageCombo': 0,
        'asrRequireKeyCheck': True, 'asrAutoSendCheck': True, 'trimSilenceCheck': True,
        'asrTimeoutSpin': 60, 'whisperPathEdit': '', 'whisperDownloadCheck': False,
        'ttsProviderCombo': 0, 'ttsUrlEdit': 'http://127.0.0.1:9880/tts',
        'ttsModelEdit': '', 'ttsVoiceEdit': '', 'ttsRequireKeyCheck': False,
        'autoReadCheck': True, 'interruptSpeechCheck': False, 'ttsTimeoutSpin': 60,
        'systemVoiceCombo': '', 'speakerCombo': None, 'outputVolumeSlider': 80,
        'speechTestEdit': '你好，今天也一起学习吧！',
    },
    'aiPage': {
        'aiProviderCombo': 0, 'baseUrlEdit': 'https://api.deepseek.com',
        'llmModelCombo': 'deepseek-flash', 'temperatureSpin': .7, 'maxTokensSpin': 2048,
        'timeoutSpin': 60, 'retrySpin': 2, 'replyLengthSpin': 0, 'apiStreamingCheck': True, 'aiRequireKeyCheck': True,
    },
    'resourcesPage': {'resourceSearchEdit': '', 'resourceScopeCombo': 0, 'importResourceKind': 'portrait'},
    'trainingPage': {
        'trainingProjectNameEdit': '茉子_新声音', 'trainingVersionCombo': 0,
        'trainingLanguageCombo': 0, 'trainingAudioDirectoryEdit': '',
        'trainingRecommendedCheck': True, 'trainingSoVITSEpochsSpin': 8,
        'trainingGPTEpochsSpin': 15, 'trainingBatchCombo': 0, 'trainingDeviceCombo': 0,
        'trainingPreviewTextEdit': 'こんにちは、よろしくね。',
    },
}

# 静态下拉项保存序号；模型、采样率和神态保存文字，设备/资源类型保存itemData。
TEXT_COMBOS = {'expressionCombo', 'sampleRateCombo', 'asrModelCombo', 'llmModelCombo'}
DATA_COMBOS = {'microphoneCombo', 'speakerCombo', 'systemVoiceCombo', 'importResourceKind'}
KEY_FIELDS = {'audioPage': ('asrApiKeyEdit', 'ttsApiKeyEdit'), 'aiPage': ('apiKeyEdit',)}

DESKTOP_DEFAULTS = {'visible': True, 'anchor': [2, 2],
                    'preview': {'pink': '今天也一起学习吧！', 'blue': '好的，我们开始。'}}
RESOURCE_DEFAULTS = {'active_pack': 'default', 'default_pack_name': '茉子'}
