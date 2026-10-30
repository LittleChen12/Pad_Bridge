# SPDX-License-Identifier: GPL-3.0-or-later
"""Handle the narrow XShm capture/resize race without killing the worker.

GStreamer's ximagesrc can read the old region while RandR shrinks the root.
Xlib's default BadMatch handler exits the process before the bus or RandR
handler gets a chance to rebuild capture. Only that request is intercepted;
other X errors retain their existing handler. No X calls occur in the callback.
"""
import ctypes


class XErrorEvent(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('display', ctypes.c_void_p),
                ('resourceid', ctypes.c_ulong), ('serial', ctypes.c_ulong),
                ('error_code', ctypes.c_ubyte), ('request_code', ctypes.c_ubyte),
                ('minor_code', ctypes.c_ubyte)]


HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))
_guard = None
_xlib = None


def init_threads():
    """Run before GStreamer starts threads or opens an Xlib connection."""
    global _xlib
    if _xlib is None:
        _xlib = ctypes.CDLL('libX11.so.6')
        _xlib.XInitThreads.restype = ctypes.c_int
        if not _xlib.XInitThreads():
            raise RuntimeError('无法初始化 X11 多线程截图。')
    return _xlib


class CaptureGuard:
    def __init__(self, display_name):
        self.generation = 0
        lib = init_threads()
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XQueryExtension.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                       ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                       ctypes.POINTER(ctypes.c_int)]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        lib.XSetErrorHandler.restype = ctypes.c_void_p
        connection = lib.XOpenDisplay(display_name.encode())
        if not connection:
            raise RuntimeError('无法连接到 X11 显示服务。')
        try:
            opcode, event, error = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
            found = lib.XQueryExtension(connection, b'MIT-SHM', ctypes.byref(opcode),
                                       ctypes.byref(event), ctypes.byref(error))
            self.shm_opcode = opcode.value if found else None
        finally:
            lib.XCloseDisplay(connection)
        self.callback = HANDLER(self._handle)
        self.previous = None
        previous = lib.XSetErrorHandler(ctypes.cast(self.callback, ctypes.c_void_p))
        if previous:
            self.previous = HANDLER(previous)

    def _handle(self, connection, pointer):
        event = pointer.contents
        # BadMatch=8; MIT-SHM GetImage=4. Do not hide unrelated X errors.
        if (event.error_code == 8 and event.request_code == self.shm_opcode
                and event.minor_code == 4):
            self.generation += 1
            return 0
        if self.previous:
            return self.previous(connection, pointer)
        return 0


def install(display_name):
    global _guard
    if _guard is None:
        _guard = CaptureGuard(display_name)
    return _guard
