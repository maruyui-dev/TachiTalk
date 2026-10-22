"""本机自动配置：Windows当前用户DPAPI加密，QSaveFile原子替换。

Win32依据：learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
不设置LOCAL_MACHINE，不弹认证窗口，不提供明文回退。
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile
from app.core.configuration_file import MAX_BYTES, _reject_constant, _unique_object

MAGIC = b'TachiTalk.session.v1\n'


class DataBlob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, *, decrypt=False):
    if os.name != 'nt':
        raise OSError('当前平台不支持Windows本机自动配置加密')
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.POINTER(DataBlob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source = ctypes.create_string_buffer(data)
    entropy = ctypes.create_string_buffer(MAGIC)
    source_blob = DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    entropy_blob = DataBlob(len(MAGIC), ctypes.cast(entropy, ctypes.POINTER(ctypes.c_ubyte)))
    output = DataBlob()
    if not function(ctypes.byref(source_blob), None, ctypes.byref(entropy_blob), None, None,
                    1, ctypes.byref(output)):  # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError('无法解密本机自动配置' if decrypt else '无法加密本机自动配置')
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


class SessionFile:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return None
        with self.path.open('rb') as source:
            raw = source.read(MAX_BYTES + 65537)
        if len(raw) > MAX_BYTES + 65536 or not raw.startswith(MAGIC):
            raise ValueError('自动配置文件格式或大小不正确')
        plain = crypt(raw[len(MAGIC):], decrypt=True)
        if len(plain) > MAX_BYTES:
            raise ValueError('自动配置超过8MB上限')
        try:
            return json.loads(plain.decode('utf-8'), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
        except (UnicodeError, ValueError, RecursionError) as error:
            raise ValueError('自动配置内容损坏') from error

    def write(self, document):
        plain = json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(plain) > MAX_BYTES:
            raise ValueError('自动配置超过8MB上限')
        protected = MAGIC + crypt(plain)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        target = QSaveFile(str(self.path))
        if not target.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError('无法写入自动配置目录')
        if target.write(protected) != len(protected) or not target.commit():
            target.cancelWriting()
            raise OSError('自动配置保存失败，原文件未替换')
