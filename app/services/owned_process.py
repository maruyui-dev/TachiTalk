"""只管理自己创建的进程；Windows Job关闭时同步终止其子进程。

依据：learn.microsoft.com/windows/win32/procthread/job-objects。
"""
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
from threading import Lock

_spawn_lock = Lock()


class WindowsJob:
    def __init__(self):
        self.handle = None
        if os.name != 'nt':
            return
        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                        ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', ctypes.c_uint64 * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api = api
        self.handle = api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def attach(self, process):
        if self.handle and not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def spawn_hidden(command, **kwargs):
    """冻结程序启动独立Python前恢复系统DLL搜索路径，防止两套Qt/运行库冲突。"""
    job = WindowsJob()
    with _spawn_lock:
        api = ctypes.windll.kernel32 if os.name == 'nt' and getattr(sys, 'frozen', False) else None
        if api:
            api.SetDllDirectoryW(None)
        try:
            process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                       **kwargs)
            try:
                job.attach(process)
            except Exception:
                process.terminate()
                process.wait(timeout=5)
                raise
            return process, job
        except Exception:
            job.close()
            raise
        finally:
            if api:
                api.SetDllDirectoryW(str(sys._MEIPASS))
