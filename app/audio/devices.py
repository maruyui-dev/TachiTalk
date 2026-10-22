"""输入设备枚举和PCM软件音量；由现有采集线程调用。"""
from array import array
from math import log10, sqrt
import sys

from app.core.audio_input import InputDevice


def enumerate_inputs(audio):
    devices = []
    for index in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(index)
        if int(info.get('maxInputChannels', 0)) > 0:
            host = audio.get_host_api_info_by_index(int(info['hostApi']))['name']
            devices.append(InputDevice(index, str(info['name']), str(host)))
    return tuple(devices)


def apply_input_volume(frame, volume):
    """100%保留原始PCM，0%静音；返回增益后的PCM和对数电平0..100。"""
    samples = array('h', frame)
    if sys.byteorder != 'little':
        samples.byteswap()
    if volume != 100:
        for i, sample in enumerate(samples):
            samples[i] = round(sample * volume / 100)
    rms = sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))
    level = 0 if not rms else max(0, min(100, round((20 * log10(rms / 32768) + 60) / 60 * 100)))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes(), level
