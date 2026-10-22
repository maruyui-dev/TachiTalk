"""可终止的本地Whisper子进程；stdout仅传JSON结果，模型在进程内复用。"""
import base64
from io import BytesIO
import json
import sys


def main():
    model = signature = None
    for line in sys.stdin.buffer:
        try:
            request = json.loads(line)
            if request.get('operation') == 'check':
                import faster_whisper
                result = {'ready': True}
            else:
                from faster_whisper import WhisperModel
                selected = request['path'] or request['model']
                current = (selected, request['download'])
                if signature != current:
                    model = WhisperModel(selected, device='cpu', compute_type='int8',
                                         local_files_only=not request['download'])
                    signature = current
                audio = BytesIO(base64.b64decode(request['wav'], validate=True))
                segments, _ = model.transcribe(audio, language=request['language'], beam_size=1,
                                               condition_on_previous_text=False, vad_filter=False)
                text = ''
                for segment in segments:
                    text += segment.text
                    if len(text) > 5000:
                        raise ValueError('识别文字超过5000字符上限')
                result = {'text': text.strip()}
        except ImportError:
            result = {'error': '未安装faster-whisper。请在项目虚拟环境执行 uv pip install -r requirements-whisper.txt'}
        except Exception as error:
            result = {'error': f'本地Whisper失败（{type(error).__name__}）：{str(error)[:400]}；请检查模型目录或允许首次下载模型'}
        print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
