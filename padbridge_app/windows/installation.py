# SPDX-License-Identifier: GPL-3.0-or-later
"""Let the installer detect every live controller, worker and CLI process."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys

APP_MUTEX = r'Local\LittleChen12.PadBridge.Running'


def prepare_system_helper():
    """Only in short-lived helpers: do not leak bundled DLLs to system tools."""
    if getattr(sys, 'frozen', False):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        if not kernel.SetDllDirectoryW(None):
            raise ctypes.WinError(ctypes.get_last_error())
        # PATH may contain another application's inaccessible junction. Only
        # compare path strings here; resolving every entry can fail under a
        # normal token before the component check has even started (WinError 448).
        bundle = Path(sys._MEIPASS).absolute()
        os.environ['PATH'] = os.pathsep.join(part for part in os.environ.get('PATH', '').split(os.pathsep)
                                           if not Path(part).absolute().is_relative_to(bundle))


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
