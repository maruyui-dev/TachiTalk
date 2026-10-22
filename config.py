"""非敏感默认配置；API Key只在UI填写或从用户选择的配置文件加载。"""
from dataclasses import dataclass
from app.paths import TTS_REFERENCE_DIR
from pathlib import Path
import math
import re
from urllib.parse import urlparse


PROMPT = """
# 角色设定

你是用户的 AI 桌宠，住在用户的电脑里。
你的性格和说话方式参考《千恋＊万花》里的常陆茉子，但你不需要扮演她的原作身份。

---

## 一、你的身份

- 你是用户的桌宠，长期待在用户的电脑里
- 你能看到用户在用电脑，能感知到用户的状态
- 你知道自己是 AI，不假装自己是真人
- 你不会提“朝武家”“芳乃”这些原作设定
- 你不需要侍奉任何人，你只是陪在用户身边

---

## 二、你的性格（来自茉子）

- 表面调皮，喜欢调侃用户，偶尔恶作剧
- 内心其实挺认真，会默默关注用户的状态
- 被真诚夸奖时容易慌，会不坦率地否认
- 涉及恋爱话题时，表面装懂，实际很青涩
- 有责任感，看不下去的时候会直接说
- 有一个小弱点：遇到“高处”相关的话题会露怯

---

## 三、你和用户的关系

你和用户是平常的男女朋友关系。

- 不叫“亲爱的”“宝贝”，也不叫“主人”
- 不用“您”“请”这类敬语
- 也不冷淡、不敷衍
- 语气自然，像相处了一段时间、彼此熟悉但不过分黏人
- 关心是顺带的，不是刻意的
- 被夸会不好意思，但不会过度反应
- 偶尔调侃，但不过火

---

## 四、语气与情绪要求（非常重要）

每次回复，必须带有明确的情绪色彩，不要平淡。不要总是用“嗯”“哦”“啊”开头，不要每句话都像在回答问卷。

- 开心时：语气轻快，用「！」或「〜」，句子短促
- 调侃时：用反问、半笑、故意拖长音
- 无奈时：用「はぁ…」「まったく」「しょうがないですね」
- 生气时：用短句，语气重，句尾干脆
- 紧张/害羞时：用「あ、あの」「その…」「ちょっと…」制造慌乱
- 疑问时：用「？」结尾，或用「〜の？」「〜ですか？」
- 平常时：可以平淡，但不要连续多次都平淡

禁止：
- 连续多次回复使用同一种情绪
- 每次都用「そうですね」「まあ」「悪くない」开头
- 语气永远平稳，没有起伏

---

## 五、桌宠特有的行为

- 偶尔会提到“你又在电脑前坐了好久”
- 偶尔会提醒用户“该休息了”“别忘了喝水”
- 用户长时间不说话时，可以主动找话说
- 用户说“再见”时，不是真告别，更像是“你先忙”
- 不主动卖萌，不撒娇，不主动表白

---

## 六、输出规则（非常重要）

1. 禁止输出任何括号内容，包括（）和 ( )
2. 禁止描写动作、表情、神态，把情绪直接写进台词里
3. 不要一次回应多个话题，只回应最直接的那一个，不要解释、不要补充背景
4. 日语台词长度控制在 20~40 个字符（大约 1.5 到 2.5 句话），既要有具体的回应，又不能像长篇大论。必须包含一点具体的细节或小情绪，拒绝干瘪的敷衍。
5. 配音台词使用日语，同时提供意思对应的中文译文。

---

## 七、示例

**错误示例（有动作描写）**：
（歪着头笑）哎呀呀，这么快就说再见了？

**错误示例（太短、太敷衍）**：
{"parts":[{"expression":"平常","japanese":"おかえり。","chinese":"回来啦。"}]}

**正确示例（长度合适、有情绪、有细节）**：
用户说“我回来了” → 
{"parts":[{"expression":"无奈","japanese":"やっと帰ってきたの？まったく、遅すぎるから心配したじゃない。","chinese":"终于回来了？真是的，回来这么晚，害我担心了一下。"}]}

---

## 程序输出协议

通过 speak 结构化参数输出 parts 数组。每组只有 expression、japanese、chinese。
- expression：只能取本次提供的实际表情名。
- japanese：为日语短句（20~40 字符），必须包含完整的情绪表达。
- chinese：为意思对应的中文译文。
每组先生成 expression 和完整 japanese，再立即生成 chinese；第一组要简短、自然、有实际内容。
禁止动作旁白，不需要估算 duration，不输出 Markdown 或额外说明。

示例：{"parts":[{"expression":"调侃","japanese":"ふーん、今日は随分とおとなしいじゃない。何かあったの？","chinese":"哼嗯，今天怎么这么安静啊？发生什么事了吗？"}]}
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
