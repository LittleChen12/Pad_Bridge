# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only monitor enumeration, Windows Graphics Capture and GDI fallback."""
import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import asdict, dataclass
import logging
import time

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Monitor:
    name: str
    x: int
    y: int
    w: int
    h: int
    primary: bool = False

    def to_dict(self):
        return asdict(self)


def dpi_aware():
    # Must precede monitor enumeration and creation of native windows.
    user = ct.WinDLL('user32', use_last_error=True)
    user.SetProcessDpiAwarenessContext.argtypes = [ct.c_void_p]
    user.SetProcessDpiAwarenessContext(ct.c_void_p(-4))


def monitors():
    dpi_aware()
    user = ct.WinDLL('user32', use_last_error=True)

    class Info(ct.Structure):
        _fields_ = [('size', wt.DWORD), ('monitor', wt.RECT), ('work', wt.RECT),
                    ('flags', wt.DWORD), ('device', wt.WCHAR * 32)]

    callback_type = ct.WINFUNCTYPE(wt.BOOL, wt.HANDLE, wt.HDC, ct.POINTER(wt.RECT), wt.LPARAM)
    user.GetMonitorInfoW.argtypes = [wt.HANDLE, ct.POINTER(Info)]
    user.EnumDisplayMonitors.argtypes = [wt.HDC, ct.POINTER(wt.RECT), callback_type, wt.LPARAM]
    found, errors = [], []

    @callback_type
    def visit(handle, dc, rect, data):
        info = Info(size=ct.sizeof(Info))
        if not user.GetMonitorInfoW(handle, ct.byref(info)):
            errors.append(ct.WinError(ct.get_last_error()))
            return False
        r = info.monitor
        found.append(Monitor(info.device, r.left, r.top, r.right-r.left, r.bottom-r.top,
                             bool(info.flags & 1)))
        return True

    if not user.EnumDisplayMonitors(None, None, visit, 0):
        raise errors[0] if errors else ct.WinError(ct.get_last_error())
    return sorted(found, key=lambda m: (not m.primary, m.name))


def choose_monitor(mode='mirror', name='', available=None):
    if mode not in ('mirror', 'extend'):
        raise ValueError('显示模式必须为扩展或镜像。')
    available = monitors() if available is None else available
    if mode == 'mirror':
        choices = [m for m in available if m.primary]
    else:
        choices = [m for m in available if not m.primary and (not name or m.name == name)]
    if len(choices) != 1:
        if mode == 'extend':
            raise RuntimeError('未找到唯一匹配的已启用副屏。请在 Windows 显示设置中启用目标副屏，'
                               '或使用 --monitor auto 让 PadBridge 自动创建 iPad 副屏。')
        raise RuntimeError('未找到唯一的 Windows 主屏幕。请检查显示设置。')
    return choices[0]


def refresh_rate(name):
    from .virtual_display import DevMode, api
    mode = DevMode(size=ct.sizeof(DevMode))
    if api().EnumDisplaySettingsExW(name, 0xFFFFFFFF, ct.byref(mode), 0):
        return mode.frequency if mode.frequency > 1 else None
    return None


class BitmapInfo(ct.Structure):
    _fields_ = [('size', wt.DWORD), ('width', wt.LONG), ('height', wt.LONG),
                ('planes', wt.WORD), ('bit_count', wt.WORD), ('compression', wt.DWORD),
                ('size_image', wt.DWORD), ('xppm', wt.LONG), ('yppm', wt.LONG),
                ('used', wt.DWORD), ('important', wt.DWORD)]


class CursorInfo(ct.Structure):
    _fields_ = [('size', wt.DWORD), ('flags', wt.DWORD), ('cursor', wt.HANDLE), ('point', wt.POINT)]


class IconInfo(ct.Structure):
    _fields_ = [('icon', wt.BOOL), ('hot_x', wt.DWORD), ('hot_y', wt.DWORD),
                ('mask', wt.HBITMAP), ('color', wt.HBITMAP)]


class Capture:
    """Owns GDI handles on the streaming thread; never changes a display mode."""
    def __init__(self, monitor):
        self.backend = 'gdi'
        self.monitor = monitor
        self.user = ct.WinDLL('user32', use_last_error=True)
        self.gdi = ct.WinDLL('gdi32', use_last_error=True)
        self.dc = self.mem = self.bitmap = self.old = None
        self.user.GetDC.argtypes, self.user.GetDC.restype = [wt.HWND], wt.HDC
        self.user.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        self.user.GetCursorInfo.argtypes = [ct.POINTER(CursorInfo)]
        self.user.GetIconInfo.argtypes = [wt.HANDLE, ct.POINTER(IconInfo)]
        self.user.DrawIconEx.argtypes = [wt.HDC, ct.c_int, ct.c_int, wt.HANDLE, ct.c_int,
                                        ct.c_int, wt.UINT, wt.HBRUSH, wt.UINT]
        self.gdi.CreateCompatibleDC.argtypes, self.gdi.CreateCompatibleDC.restype = [wt.HDC], wt.HDC
        self.gdi.CreateDIBSection.argtypes = [wt.HDC, ct.POINTER(BitmapInfo), wt.UINT,
                                             ct.POINTER(ct.c_void_p), wt.HANDLE, wt.DWORD]
        self.gdi.CreateDIBSection.restype = wt.HBITMAP
        self.gdi.SelectObject.argtypes, self.gdi.SelectObject.restype = [wt.HDC, wt.HANDLE], wt.HANDLE
        self.gdi.DeleteObject.argtypes = [wt.HANDLE]
        self.gdi.DeleteDC.argtypes = [wt.HDC]
        self.gdi.BitBlt.argtypes = [wt.HDC, ct.c_int, ct.c_int, ct.c_int, ct.c_int,
                                   wt.HDC, ct.c_int, ct.c_int, wt.DWORD]
        try:
            self.dc = self.user.GetDC(None)
            self.mem = self.gdi.CreateCompatibleDC(self.dc)
            info = BitmapInfo(size=ct.sizeof(BitmapInfo), width=monitor.w, height=-monitor.h,
                              planes=1, bit_count=32)
            self.bits = ct.c_void_p()
            self.bitmap = self.gdi.CreateDIBSection(self.dc, ct.byref(info), 0,
                                                   ct.byref(self.bits), None, 0)
            if not all((self.dc, self.mem, self.bitmap, self.bits.value)):
                raise ct.WinError(ct.get_last_error())
            self.old = self.gdi.SelectObject(self.mem, self.bitmap)
            if not self.old or self.old == ct.c_void_p(-1).value:
                raise ct.WinError(ct.get_last_error())
        except BaseException:
            self.close()
            raise

    def grab(self):
        m = self.monitor
        if not self.gdi.BitBlt(self.mem, 0, 0, m.w, m.h, self.dc, m.x, m.y, 0x40CC0020):
            raise RuntimeError('Windows 桌面采集失败；请解锁桌面并检查显示器连接。')
        cursor = CursorInfo(size=ct.sizeof(CursorInfo))
        if self.user.GetCursorInfo(ct.byref(cursor)) and cursor.flags & 1:
            icon = IconInfo()
            if self.user.GetIconInfo(cursor.cursor, ct.byref(icon)):
                try:
                    self.user.DrawIconEx(self.mem, cursor.point.x-m.x-icon.hot_x,
                                         cursor.point.y-m.y-icon.hot_y, cursor.cursor, 0, 0, 0, None, 3)
                finally:
                    for bitmap in (icon.mask, icon.color):
                        if bitmap:
                            self.gdi.DeleteObject(bitmap)
        self.gdi.GdiFlush()
        return ct.string_at(self.bits, m.w * m.h * 4)

    def close(self):
        if self.old and self.mem:
            self.gdi.SelectObject(self.mem, self.old)
        if self.bitmap:
            self.gdi.DeleteObject(self.bitmap)
        if self.mem:
            self.gdi.DeleteDC(self.mem)
        if self.dc:
            self.user.ReleaseDC(None, self.dc)
        self.dc = self.mem = self.bitmap = self.old = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def graphics_output(outputs, name):
    """Match the Win32 device name; never guess from output order or resolution."""
    matches = [(device, index) for device, group in enumerate(outputs)
               for index, output in enumerate(group) if output.devicename == name]
    if len(matches) != 1:
        raise RuntimeError('图形采集接口没有唯一匹配的显示器。')
    return matches[0]


def create_graphics_camera(dxcam, name):
    # DXcam 0.3.0's global factory enumerates only at import. A disconnected
    # virtual monitor is withdrawn and recreated with a new identity; reusing
    # that factory then silently forces the much slower GDI fallback. Build a
    # camera from fresh DXGI objects for each capture session instead. This
    # adapter is version-pinned and never changes another camera's resources.
    devices, outputs = [], []
    for adapter in dxcam.enum_dxgi_adapters():
        device = dxcam.Device(adapter)
        devices.append(device)
        outputs.append([dxcam.Output(pointer) for pointer in device.enum_outputs()])
    device, output = graphics_output(outputs, name)
    return dxcam.DXCamera(device=devices[device], output=outputs[device][output], region=None,
                         output_color='BGRA', backend='winrt', processor_backend='numpy',
                         max_buffer_len=2)


class GraphicsCapture:
    """Windows.Graphics.Capture: latest frame only, with the native cursor."""
    backend = 'windows-graphics-capture'

    def __init__(self, monitor):
        import dxcam
        self.monitor = monitor
        self.camera = None
        try:
            self.camera = create_graphics_camera(dxcam, monitor.name)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if self.camera.grab(copy=False, new_frame_only=False) is not None:
                    break
                time.sleep(0.005)
            else:
                raise RuntimeError('Windows 图形采集没有返回首帧。')
        except BaseException:
            self.close()
            raise

    def grab(self):
        frame = self.camera.grab(copy=False, new_frame_only=False)
        if frame is None or frame.shape != (self.monitor.h, self.monitor.w, 4):
            raise RuntimeError('Windows 图形采集区域已变化，正在重新连接。')
        return frame if frame.flags.c_contiguous else frame.copy()

    def close(self):
        if self.camera:
            self.camera.release()
            self.camera = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def create_capture(monitor):
    try:
        return GraphicsCapture(monitor)
    except Exception as exc:
        log.warning('Windows 图形采集不可用，回退 GDI：%s', exc)
        return Capture(monitor)
