# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenDisplay pointer gestures -> Win32 SendInput, in physical desktop pixels."""
import ctypes as ct
from ctypes import wintypes as wt
import math
import time
from odx11.input import TouchGesture, ScrollAccumulator, to_root


class MouseInput(ct.Structure):
    _fields_ = [('dx', wt.LONG), ('dy', wt.LONG), ('data', wt.DWORD),
                ('flags', wt.DWORD), ('time', wt.DWORD), ('extra', ct.c_size_t)]


class InputUnion(ct.Union):
    _fields_ = [('mouse', MouseInput)]


class Input(ct.Structure):
    _fields_ = [('type', wt.DWORD), ('value', InputUnion)]


class Injector:
    def __init__(self, geometry):
        self.geometry = geometry
        self.gesture = TouchGesture(8, 0.6)
        self.scroll = ScrollAccumulator(40)
        self.user = ct.WinDLL('user32', use_last_error=True)
        self.user.SendInput.argtypes = [wt.UINT, ct.POINTER(Input), ct.c_int]
        self.user.SendInput.restype = wt.UINT

    def _send(self, flags, dx=0, dy=0, data=0):
        event = Input(type=0, value=InputUnion(mouse=MouseInput(dx, dy, data & 0xffffffff, flags, 0, 0)))
        if self.user.SendInput(1, ct.byref(event), ct.sizeof(Input)) != 1:
            # UIPI prevents input to elevated apps and secure desktops.
            raise OSError('Windows 拒绝输入事件；请在普通权限桌面应用中使用触控。')

    def _actions(self, actions):
        for kind, arg in actions:
            if kind == 'move':
                x, y = self.user.GetSystemMetrics(76), self.user.GetSystemMetrics(77)
                w, h = self.user.GetSystemMetrics(78), self.user.GetSystemMetrics(79)
                self._send(0xC001, round((arg[0]-x)*65535/max(1, w-1)),
                           round((arg[1]-y)*65535/max(1, h-1)))
            elif arg in (1, 3):
                flags = {(1, 'press'): 2, (1, 'release'): 4, (3, 'press'): 8, (3, 'release'): 16}
                self._send(flags[arg, kind])

    def handle(self, message):
        def finite(v):
            return type(v) in (int, float) and math.isfinite(v)
        if message.get('type') == 'touch':
            if not all(finite(message.get(k)) for k in ('x', 'y')):
                return
            phase = message.get('phase')
            if phase in ('began', 'moved', 'ended', 'cancelled'):
                point = to_root(message['x'], message['y'], self.geometry)
                self._actions(self.gesture.feed(phase, point, time.monotonic()))
        elif message.get('type') == 'scroll':
            dx, dy = message.get('dx', 0), message.get('dy', 0)
            if not all(finite(v) and abs(v) <= 10000 for v in (dx, dy)):
                return
            for button in self.scroll.feed(dx, dy):
                self._send(0x0800 if button in (4, 5) else 0x1000,
                           data=120 if button in (4, 7) else -120)

    def release_all(self):
        self._actions(self.gesture.reset())
