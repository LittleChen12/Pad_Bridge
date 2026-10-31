# SPDX-License-Identifier: GPL-3.0-or-later
"""Let the installer detect every live controller, worker and CLI process."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes

APP_MUTEX = r'Local\LittleChen12.PadBridge.Running'


@contextmanager
def running_application():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, APP_MUTEX)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)
