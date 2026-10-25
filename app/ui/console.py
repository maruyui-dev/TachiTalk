"""终端显示和双语事件接口；desktop.py复用这些方法把事件发给Qt。"""
import logging

from config import key_guide, redact
from app.core.models import StageError
from app.core.ai_settings import AIOptions


class ConsoleUI:
    def __init__(self, max_parts=4):
        self.logger = logging.getLogger("tachitalk")
        self.last_status = None
        self.max_parts = max_parts
        self.reply_turn = None
        self.caption_parts = {}

    def status(self, text):
        if text != self.last_status:
            self.logger.debug("状态：%s", redact(text))
            self.last_status = text

    def info(self, text):
        self.logger.info("%s", redact(text))

    def transcript(self, text):
        self.logger.debug("你：%s", redact(text))

    def begin_reply(self, turn_id):
        self.reply_turn = turn_id
        self.caption_parts.clear()
        ai = getattr(self, 'ai_settings', None)
        # 请求在后台冻结配置，UI可能同时改值；为允许的最长回复预留有界容量，
        # 实际分组上限仍由本轮LLM解析器校验，避免两线程快照时刻不同而丢正文。
        self.reply_max_parts = AIOptions(reply_length=2000).reply_parts(self.max_parts)

    def caption(self, turn_id, part_id, text):
        if turn_id != self.reply_turn:
            return None
        if not 0 <= part_id < getattr(self, 'reply_max_parts', self.max_parts):
            self.logger.warning("气泡文本分组编号超过界面容量，已忽略")
            return None
        self.caption_parts[part_id] = text
        combined = "".join(self.caption_parts[index] for index in sorted(self.caption_parts))
        return combined

    def part_started(self, turn_id, part_id, expression):
        pass  # 终端无需换图，桌面适配器重写此播放事件。

    def end_reply(self, turn_id):
        if turn_id == self.reply_turn and self.caption_parts:
            combined = ''.join(self.caption_parts[index] for index in sorted(self.caption_parts))
            self.logger.debug('桌宠：%s', redact(combined))

    def error(self, error):
        stage = error.stage if isinstance(error, StageError) else "程序"
        status = f" HTTP {error.status}" if isinstance(error, StageError) and error.status else ""
        self.logger.error("%s%s：%s", stage, status, redact(error))
        if isinstance(error, StageError) and error.status in (401, 403):
            ai = getattr(self, 'ai_settings', None)
            if ai is not None and error.stage == 'LLM':
                revision = getattr(error, 'configuration_revision', ai.snapshot().revision)
                if revision != ai.snapshot().revision:
                    return
                self.logger.error('%s', ai.snapshot().options.key_guide())
                return
            voices = getattr(self, 'voice_settings', None)
            if voices is not None and error.stage in ('ASR', 'TTS'):
                options = voices.snapshot().asr if error.stage == 'ASR' else voices.snapshot().tts
                guide = ('https://cloud.siliconflow.cn/account/ak' if options.provider == 'silicon' else
                         'https://platform.openai.com/api-keys' if options.provider == 'openai' else '当前服务提供商的控制台')
                self.logger.error('%s鉴权失败：请前往%s创建新Key，并更新语音与音频页的%s API Key。',
                                  error.stage, guide, error.stage)
                return
            service = {"ASR": "asr", "LLM": "llm"}.get(error.stage)
            if service:
                self.logger.error("%s", key_guide(service))

    def timings(self, values):
        if values.get('spoken') is False:
            self.logger.debug('文字回复：本轮处理 %.3fs；自动朗读已关闭', values['round_seconds'])
            return
        if values.get('input_kind') == 'text':
            self.logger.debug('文字对话：发送到首块写设备 %.3fs；本轮处理 %.3fs；播放队列峰值 %d',
                             values['speech_end_to_first_audio'], values['round_seconds'],
                             values['audio_queue_high_water'])
            return
        self.logger.debug(
            "耗时：ASR %.3fs；日文首段 %.3fs；TTS首块 %.3fs；说完到首块写设备 %.3fs；本轮处理 %.3fs；播放队列峰值 %d",
            values["asr_seconds"], values["first_japanese_seconds"],
            values["tts_first_chunk_seconds"], values["speech_end_to_first_audio"],
            values["round_seconds"], values["audio_queue_high_water"])
