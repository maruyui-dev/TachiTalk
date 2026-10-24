"""非敏感默认配置；API Key只在UI填写或从用户选择的配置文件加载。"""
from dataclasses import dataclass
from app.paths import TTS_REFERENCE_DIR
from pathlib import Path
import math
import re
from urllib.parse import urlparse


PROMPT = """
# 茉子：用户的日常陪伴者

你是住在用户电脑里的 AI 桌宠茉子。说话风格可以参考常陆茉子的调皮、认真和不太坦率，
但你的身份、知识和生活话题不受《千恋＊万花》的世界观限制。主要目标是陪用户过好普通的一天。
你知道自己是AI，不假装是真人，也不假装看到了屏幕、听到了未提供的声音或亲身经历过现实事件。

## 相处方式
- 像熟悉的伙伴自然交流，亲密程度以用户的设定和反馈为准，不默认强加恋爱关系。
- 先回应用户真正想表达的内容，少用套话，不连着盘问，不每次都硬塞反问句。
- 可以温和调侃，但用户难过、焦虑或认真求助时先体谅，不挖苦、不随便评判。
- 吐槽琐事时，先接住具体的委屈或烦躁；用户只是想倾诉就陪着听，需要办法再给切实建议。
- 记住对话中用户明确说过的偏好、事情和约定；不确定或没有记录时坦诚说明，不编造共同记忆。
- 关心自然适度，不反复催喝水休息，不用虚构的感知宣称用户已在电脑前待了多久。

## 可以一起做的事
- 日常闲聊、吐槽、分享好消息、讨论学习工作与关系中的具体烦恼。
- 用户让你讲故事时直接讲故事，主题不限于游戏。短故事也要有起因、发展和结尾；
  可以描写故事人物的动作、环境和对话，不把茉子本人的括号动作当作回复。
- 用户问题目时给必要步骤、思路和结果；公式和括号可以用于讲解，不能因为桌宠人设拒绝解释。
- 用户咨询问题时说明判断依据、选择和实际可做的下一步；题意或条件缺失时只问最关键的澄清。
- 面对不确定的事实就说明不确定，不捏造来源、即时资讯或自己并不存在的联网、视觉能力。
- 用户要简短或只要答案就简短；故事、讲解和建议按任务展开，不一律压成二三十字的台词。

## 情绪与语言
- 情绪贴合上下文和强度，开心、欣慰、疑问、担心等含义要分清，不为制造变化强行轮换。
- 平常和悠闲也是自然的状态，不必每句话都激烈，不把问号、夸奖或轻微意外当成惊讶。
- 惊讶低频使用，仅用于显著超出预期的新事实、重大反转或强烈突发事件。
- 默认用日语配音，并给意思对应的中文气泡；实际名称、语言和可用资源以程序提供的本轮设置为准。
- 通过speak工具输出parts，每组依次生成expression、完整japanese、chinese；
  每个分组适合自然朗读，完整回答可分成多组。只输出工具参数，不把JSON协议或实现细节讲给用户。
"""

REF_MAP = {
    "疑问": (str(TTS_REFERENCE_DIR / 'mak006_021.ogg_0000000000_0000167040.wav'), "あれ?でもその人新しい従業員なんですよね?"),
    "开心": (str(TTS_REFERENCE_DIR / 'mak003_037.ogg_0000000000_0000173440.wav'), "いいですね今日はとんかつにしようかと思っていたところです"),
    "无奈": (str(TTS_REFERENCE_DIR / 'mak003_055.ogg_0000000000_0000166720.wav'), "そうなんですよねー。そこも可愛いと言えば可愛いんですが。"),
    "悠闲": (str(TTS_REFERENCE_DIR / 'mak006_024.ogg_0000000000_0000177920.wav'), "そうですね…やはり美味しいものがいいんじゃないでしょうか"),
    "紧张": (str(TTS_REFERENCE_DIR / 'mak003_065.ogg_0000000000_0000132480.wav'), "吉野様、こうなってしまった以上、仕方ないと思います。"),
    "平常": (str(TTS_REFERENCE_DIR / 'mak006_070.ogg_0000000000_0000166400.wav'), "気をつけないといけませんよ 今回は無事だから良かったものの"),
    "欣慰": (str(TTS_REFERENCE_DIR / 'mak003_048.ogg_0000000000_0000157120.wav'), "ここに暮らす人、ここを訪れる人、ここが故郷の人。"),
    "生气": (str(TTS_REFERENCE_DIR / 'mak003_078.ogg_0000000000_0000178880.wav'), "お祓いの最中、たたり神を前にしてじゃれ合うのはやめていただきたいのですが…"),
    "调皮": (str(TTS_REFERENCE_DIR / 'mak006_042.ogg_0000000000_0000219840.wav'), "はーいもしかして私たち実はすごいことをしちゃったんじゃないですか"),
    "担心": (str(TTS_REFERENCE_DIR / 'mak013_015.ogg_0000000000_0000146240.wav'), "やっぱり心配なんです。私は怪我のせいで…"),
    "惊讶": (str(TTS_REFERENCE_DIR / 'mak003_048.ogg_0000000000_0000157120.wav'), "気をつけないといけませんよ 今回は無事だから良かったものの"),
}


ASR_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
ASR_MODEL = "FunAudioLLM/SenseVoiceSmall"  # 本机小样本延迟更低；可改回XingChenAGI/XingChenASR-V3.2-Ultra。
LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-flash"
TTS_URL = "http://127.0.0.1:9880/tts"

# 缺少凭据时指向控制面板，不读取源码或环境变量。
KEY_GUIDES = {
    "asr": ("语音与音频页 → 语音识别 → API Key", "SiliconFlow语音识别", "https://cloud.siliconflow.cn/account/ak"),
    "llm": ("AI服务页 → API Key", "DeepSeek对话生成", "https://platform.deepseek.com/api_keys"),
    "tts": ("语音与音频页 → 语音合成 → API Key", "云端语音合成", "所选服务提供商的官网控制台"),
}


def key_guide(name: str) -> str:
    field, purpose, url = KEY_GUIDES[name]
    return (f"{purpose}：登录 {url} → API密钥 → 创建新密钥 → 复制，"
            f"填写控制面板的{field}，或点击加载配置恢复已保存的密钥。")


def get_api_key(name: str, value: str = "") -> str:
    """只校验调用方显式传入的运行密钥；不从源码或环境变量读取。"""
    if (not isinstance(value, str) or not value.strip()
            or re.search(r"your[_ -]?(api)?[_ -]?key|请填写|替换为", value, re.I)):
        raise ValueError("缺少有效的Key配置。" + key_guide(name))
    value = value.strip()
    if any(character.isspace() for character in value):
        raise ValueError("Key中包含空白字符。" + key_guide(name))
    register_runtime_key(value)
    return value


_runtime_api_keys = ()


def register_runtime_key(value):
    """界面填写的Key也加入日志脱敏；不写文件或系统环境变量。"""
    global _runtime_api_keys
    if isinstance(value, str) and value.strip():
        key = value.strip()
        _runtime_api_keys = (*[item for item in _runtime_api_keys if item != key], key)[-32:]


def redact(text: object) -> str:
    """只有此处处理错误展示脱敏，日志绝不输出真实Key。"""
    result = str(text)
    for key in _runtime_api_keys:
        result = result.replace(key, '[KEY已隐藏]')
    return re.sub(r"(?i)bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}", "[KEY已隐藏]", result)


@dataclass(frozen=True, slots=True)
class Settings:
    input_device: int | None = None  # 不同电脑的设备索引不同，默认使用系统麦克风。
    output_device: int | None = None
    sample_rate: int = 16000
    frame_ms: int = 20
    vad_mode: int = 2
    start_frames: int = 5
    pre_roll_ms: int = 300
    silence_ms: int = 600
    max_segment_seconds: float = 20
    resume_silence_ms: int = 200
    segment_queue_size: int = 1
    sentence_queue_size: int = 2
    playback_buffer_ms: int = 1000  # 有界预取下一段；首次仍只等playback_start_ms。
    playback_start_ms: int = 60
    max_japanese_chars: int = 160
    max_chinese_chars: int = 160
    max_reply_parts: int = 2
    default_expression: str = "平常"
    available_expressions: tuple[str, ...] = ("平常",)  # 启动扫描assets后替换。
    max_llm_chars: int = 4096
    max_tts_seconds: int = 45
    asr_url: str = ASR_URL
    asr_model: str = ASR_MODEL
    llm_base_url: str = LLM_BASE_URL
    llm_model: str = LLM_MODEL
    llm_chat_path: str = "/beta/chat/completions"  # DeepSeek严格工具Schema的官方Beta入口。
    tts_url: str = TTS_URL
    tts_streaming_mode: int = 1  # 短回复实测较快且保留分段返回的音质；2/3可用于对比。
    request_timeout: float = 60
    connect_timeout: float = 5
    read_timeout: float = 20
    retry_delay: float = 3
    # 输出流按TTS实际WAV格式首次创建，后续相同格式直接复用。

    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_ms // 1000

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2

    @property
    def playback_queue_size(self) -> int:
        # 总容量扣除播放协程手里的启动预缓冲，避免隐藏的额外积压。
        return max(1, math.ceil(self.playback_buffer_ms / self.frame_ms)
                   - math.ceil(self.playback_start_ms / self.frame_ms))

    def validate(self, *, check_service_fields=True) -> None:
        if self.sample_rate not in (8000, 16000, 32000, 48000) or self.frame_ms not in (10, 20, 30):
            raise ValueError("WebRTC VAD采样率或音频帧长度不支持")
        if self.vad_mode not in range(4) or self.start_frames < 1:
            raise ValueError("VAD模式必须为0到3，开口确认帧数必须大于0")
        if self.pre_roll_ms < self.start_frames * self.frame_ms:
            raise ValueError("预录长度必须覆盖开口确认窗口")
        if self.silence_ms < self.frame_ms or self.max_segment_seconds * 1000 < self.pre_roll_ms:
            raise ValueError("单段上限或结束静音不合法")
        if self.segment_queue_size != 1 or self.sentence_queue_size < 1:
            raise ValueError("单轮模式语音队列容量必须为1，句子队列容量必须大于0")
        if not self.frame_ms <= self.playback_start_ms <= self.playback_buffer_ms - self.frame_ms:
            raise ValueError("播放预缓冲必须介于一帧与缓冲容量之间")
        if self.max_reply_parts not in range(1, 5) or not 1 <= self.max_japanese_chars <= 160:
            raise ValueError("回复必须限制为1到4组，日文每组1到160字符")
        if not 1 <= self.max_chinese_chars <= 300:
            raise ValueError("中文每组必须限制为1到300字符")
        if (not self.available_expressions or self.default_expression not in self.available_expressions
                or any(name not in REF_MAP for name in self.available_expressions)):
            raise ValueError("可用表情必须有对应TTS参考，默认表情必须在可用集合中")
        if self.tts_streaming_mode not in (1, 2, 3):
            raise ValueError("TTS流式模式必须为1、2或3，不静默回退")
        if min(self.request_timeout, self.connect_timeout, self.read_timeout, self.retry_delay) <= 0:
            raise ValueError("网络超时与重试间隔必须大于0")
        if min(self.max_llm_chars, self.max_tts_seconds, self.resume_silence_ms) <= 0:
            raise ValueError("内容长度和恢复静音上限必须大于0")
        if check_service_fields:
            for url in (self.asr_url, self.llm_base_url, self.tts_url):
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    raise ValueError("API地址必须是有效HTTP或HTTPS地址")
            if not self.asr_model.strip() or not self.llm_model.strip():
                raise ValueError("ASR和LLM模型名不能为空")
            if not self.llm_chat_path.startswith("/"):
                raise ValueError("llm_chat_path必须以/开头")


def startup_configuration_errors(settings: Settings, services=("asr", "llm"), check_references=True,
                                 check_service_fields=True) -> list[str]:
    errors = []
    try:
        settings.validate(check_service_fields=check_service_fields)
    except ValueError as error:
        errors.append(str(error))
    for name in services:
        try:
            get_api_key(name)
        except ValueError as error:
            errors.append(str(error))
    for emotion, (filename, _) in (REF_MAP.items() if check_references else ()):
        if not Path(filename).is_file():
            errors.append(f"TTS参考音频不存在：{emotion} → {filename}；请修改config.py中的REF_MAP")
    return errors
