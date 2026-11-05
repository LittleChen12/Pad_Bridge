# SPDX-License-Identifier: GPL-3.0-or-later
"""One explicitly owned IDD output; never change physical display modes."""
import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass
import os
from pathlib import Path
import time

from . import desktop, storage, display_config, device_control

AUTO = 'auto'
INSTALL_DIR = Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'PadBridge' / 'VirtualDisplayDriver'
OWNER = INSTALL_DIR / 'padbridge-driver.json'
LEASE = storage.RUNTIME / 'virtual-display.json'


class DisplayDevice(ct.Structure):
    _fields_ = [('cb', wt.DWORD), ('name', wt.WCHAR*32), ('description', wt.WCHAR*128),
                ('flags', wt.DWORD), ('device_id', wt.WCHAR*128), ('key', wt.WCHAR*128)]


class DevMode(ct.Structure):
    _fields_ = [('device', wt.WCHAR*32), ('spec', wt.WORD), ('driver', wt.WORD),
                ('size', wt.WORD), ('extra', wt.WORD), ('fields', wt.DWORD),
                ('position', wt.POINT), ('orientation', wt.DWORD), ('fixed', wt.DWORD),
                ('color', wt.SHORT), ('duplex', wt.SHORT), ('yres', wt.SHORT),
                ('tt', wt.SHORT), ('collate', wt.SHORT), ('form', wt.WCHAR*32),
                ('logpixels', wt.WORD), ('bits', wt.DWORD), ('width', wt.DWORD),
                ('height', wt.DWORD), ('flags', wt.DWORD), ('frequency', wt.DWORD),
                ('icm', wt.DWORD), ('intent', wt.DWORD), ('media', wt.DWORD),
                ('dither', wt.DWORD), ('reserved1', wt.DWORD), ('reserved2', wt.DWORD),
                ('panwidth', wt.DWORD), ('panheight', wt.DWORD)]


@dataclass(frozen=True)
class Adapter:
    name: str
    description: str
    device_id: str
    key: str
    attached: bool
    primary: bool

    @property
    def is_vdd(self):
        return self.description == 'Virtual Display Driver' and 'MTTVDD' in self.device_id.upper()


def api():
    user = ct.WinDLL('user32', use_last_error=True)
    user.EnumDisplayDevicesW.argtypes = [wt.LPCWSTR, wt.DWORD, ct.POINTER(DisplayDevice), wt.DWORD]
    user.EnumDisplaySettingsExW.argtypes = [wt.LPCWSTR, wt.DWORD, ct.POINTER(DevMode), wt.DWORD]
    user.ChangeDisplaySettingsExW.argtypes = [wt.LPCWSTR, ct.POINTER(DevMode), wt.HWND, wt.DWORD, ct.c_void_p]
    user.ChangeDisplaySettingsExW.restype = wt.LONG
    return user


def adapters():
    desktop.dpi_aware()
    user = api()
    result = []
    for index in range(64):
        device = DisplayDevice(cb=ct.sizeof(DisplayDevice))
        if not user.EnumDisplayDevicesW(None, index, ct.byref(device), 0):
            break
        result.append(Adapter(device.name, device.description, device.device_id, device.key,
                              bool(device.flags & 1), bool(device.flags & 4)))
    return result


def owned_adapter():
    owner = storage.read_json(OWNER)
    if owner.get('hardware_id') != r'Root\MttVDD':
        return None
    matches = [a for a in adapters() if a.is_vdd]
    return matches[0] if len(matches) == 1 else None


def available():
    # A parked PnP device has no GDI adapter, but is still installed and usable.
    return device_control.ready() and device_control.owned_device() is not None


def modes(name, refresh=60):
    user = api()
    found = {}
    for index in range(1024):
        mode = DevMode(size=ct.sizeof(DevMode))
        if not user.EnumDisplaySettingsExW(name, index, ct.byref(mode), 0):
            break
        if mode.bits == 32 and mode.frequency > 1:
            size = (mode.width, mode.height)
            previous = found.get(size)
            # Lowest supported rate at or above the stream target; otherwise
            # the highest available. 24/30/60 FPS keep the usual 60 Hz mode.
            score = lambda m: (m.frequency < refresh, abs(m.frequency - refresh))
            if previous is None or score(mode) < score(previous):
                found[size] = mode
    return found


def choose_size(available_sizes, wanted):
    if wanted in available_sizes:
        return wanted
    # Preserve tablet aspect ratio first, then choose the closest pixel count.
    w, h = wanted
    return min(available_sizes, key=lambda s: (abs(s[0]/s[1]-w/h), abs(s[0]*s[1]-w*h)))


def initial_position(screens, size, position):
    """Place beside the desktop, aligned with the primary, without overlap."""
    if position not in ('left', 'right'):
        raise ValueError('副屏位置必须为左侧或右侧。')
    main = next(m for m in screens if m.primary)
    width, height = size
    neighbors = [m for m in screens if m.y < main.y+height and m.y+m.h > main.y]
    x = min(m.x for m in neighbors)-width if position == 'left' else max(m.x+m.w for m in neighbors)
    return x, main.y


def apply_mode(adapter, mode):
    if not adapter.is_vdd or adapter.primary:
        raise RuntimeError('拒绝修改非 PadBridge 虚拟副屏。')
    name, active, shared, _ = display_config.current()
    if active and not shared and any(m.name == name and m.primary for m in desktop.monitors()):
        raise RuntimeError('虚拟屏已被设为主屏，已保留用户布局。')
    display_config.apply(mode.width, mode.height, mode.position.x, mode.position.y,
                         refresh=mode.frequency or 60)


def detach(adapter):
    mode = DevMode(size=ct.sizeof(DevMode), fields=0x20 | 0x80000 | 0x100000)
    apply_mode(adapter, mode)


def recover():
    """Withdraw only the device recorded by our connection, keeping user layouts."""
    lease = storage.read_json(LEASE)
    if not lease:
        return
    device = device_control.owned_device()
    if not device:
        return
    adapter = owned_adapter()
    matches = (lease.get('instance_id') == device.instance_id if 'instance_id' in lease else
               adapter and adapter.device_id == lease.get('device_id') and adapter.key == lease.get('key'))
    if not matches:
        return
    current = display_config.current(optional=True)
    if current:
        name, active, shared, path = current
        if lease.get('monitor_path', path) != path:
            return
        if active and not shared and any(m.name == name and m.primary for m in desktop.monitors()):
            LEASE.unlink(missing_ok=True)
            return
        if active and adapter:
            detach(adapter)
    device_control.set_enabled(False)
    LEASE.unlink(missing_ok=True)


def park_idle():
    """Migrate an old, inactive output without taking a user-enabled screen away."""
    if not available():
        return
    current = display_config.current(optional=True)
    if current is None or not current[1]:
        device_control.set_enabled(False)


class VirtualDisplay:
    def __init__(self, position='right'):
        if position not in ('left', 'right'):
            raise ValueError('副屏位置必须为左侧或右侧。')
        self.position = position
        self.placed_at = None
        self.adapter = None
        self.monitor_name = None
        self.size = None
        self.requested_refresh = 60
        self.borrowed = False

    def attach(self, wanted, refresh=60):
        # The stream checks geometry once a second. Stable sessions need only
        # the active-monitor list, not PnP/CCD enumeration on the video thread.
        if self.adapter is not None and (self.borrowed or (self.size == wanted and self.requested_refresh == refresh)):
            for monitor in desktop.monitors():
                if monitor.name == self.monitor_name and not monitor.primary:
                    return monitor
        device = device_control.owned_device()
        if not device:
            raise RuntimeError('扩展屏幕需要虚拟显示组件，请先点击“安装扩展组件”。')
        current = display_config.current(optional=True)
        if self.adapter is None:
            # Borrow only a screen that was active BEFORE enabling our device.
            self.borrowed = bool(current and current[1] and not current[2])
            if not self.borrowed:
                storage.write_json(LEASE, {'instance_id': device.instance_id})
                device_control.set_enabled(True)
        deadline = time.monotonic()+8
        while current is None and time.monotonic() < deadline:
            time.sleep(0.05)
            current = display_config.current(optional=True)
        if current is None:
            raise RuntimeError('Windows 尚未创建虚拟屏，请重新连接。')
        adapter = owned_adapter()
        if not adapter:
            raise RuntimeError('虚拟显示适配器尚未就绪，请重新连接。')
        if adapter.primary:
            raise RuntimeError('虚拟屏当前是主屏，请先在“排列屏幕”中恢复电脑主屏。')
        name, active, shared, path = current
        if not self.borrowed and (not active or shared or self.size != wanted or self.requested_refresh != refresh):
            choices = modes(adapter.name, refresh)
            if not choices:
                raise RuntimeError('虚拟显示驱动没有提供可用模式，请更新扩展组件。')
            chosen = choose_size(choices, wanted)
            mode = choices[chosen]
            screens = desktop.monitors()
            old = next((m for m in screens if m.name == name and not m.primary), None)
            # Windows may restore the driver's last coordinates on enable.
            # A new session must use the selected side. Within this session,
            # keep manual moves; an untouched left screen stays edge-aligned
            # when its native size changes (for example, tablet rotation).
            manual = self.adapter is not None and old is not None and (old.x, old.y) != self.placed_at
            others = [m for m in screens if m.primary or m.name != name]
            point = (old.x, old.y) if manual else initial_position(others, chosen, self.position)
            mode.position.x, mode.position.y = point
            mode.fields = 0x20 | 0x40000 | 0x80000 | 0x100000 | 0x400000
            storage.write_json(LEASE, {'instance_id': device.instance_id, 'device_id': adapter.device_id,
                                       'key': adapter.key, 'monitor_path': path})
            apply_mode(adapter, mode)
            self.placed_at = None if manual else point
            self.size = wanted
            self.requested_refresh = refresh
            name = display_config.current()[0]
        self.adapter = adapter
        self.monitor_name = name
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            for monitor in desktop.monitors():
                if monitor.name == name and not monitor.primary:
                    return monitor
            time.sleep(0.05)
        raise RuntimeError('Windows 没有启用虚拟副屏，请打开“排列屏幕”检查。')

    def close(self):
        if not self.borrowed:
            recover()
        self.adapter = None
        self.placed_at = None
        self.monitor_name = None
        self.size = None
        self.requested_refresh = 60
        self.borrowed = False
