# SPDX-License-Identifier: GPL-3.0-or-later
"""CCD topology updates confined to one verified virtual GDI source."""
import ctypes as ct
from ctypes import wintypes as wt

U32 = ct.c_uint32
INVALID = 0xffffffff


class Luid(ct.Structure):
    _fields_ = [('low', U32), ('high', ct.c_int32)]


class Rational(ct.Structure):
    _fields_ = [('numerator', U32), ('denominator', U32)]


class Source(ct.Structure):
    _fields_ = [('adapter', Luid), ('id', U32), ('mode', U32), ('status', U32)]


class Target(ct.Structure):
    _fields_ = [('adapter', Luid), ('id', U32), ('mode', U32), ('technology', U32),
                ('rotation', U32), ('scaling', U32), ('refresh', Rational),
                ('scanline', U32), ('available', wt.BOOL), ('status', U32)]


class Path(ct.Structure):
    _fields_ = [('source', Source), ('target', Target), ('flags', U32)]


class SourceMode(ct.Structure):
    _fields_ = [('width', U32), ('height', U32), ('format', U32), ('position', wt.POINT)]


class ModeData(ct.Union):
    # uint64 array retains the alignment of DISPLAYCONFIG_VIDEO_SIGNAL_INFO.
    _fields_ = [('raw', ct.c_uint64*6), ('source', SourceMode)]


class Mode(ct.Structure):
    _fields_ = [('type', U32), ('id', U32), ('adapter', Luid), ('data', ModeData)]


class SourceName(ct.Structure):
    _fields_ = [('type', U32), ('size', U32), ('adapter', Luid), ('id', U32), ('name', wt.WCHAR*32)]


class TargetName(ct.Structure):
    _fields_ = [('type', U32), ('size', U32), ('adapter', Luid), ('id', U32),
                ('flags', U32), ('technology', U32), ('manufacturer', wt.WORD), ('product', wt.WORD),
                ('connector', U32), ('friendly', wt.WCHAR*64), ('path', wt.WCHAR*128)]


def api():
    user = ct.WinDLL('user32')
    user.GetDisplayConfigBufferSizes.argtypes = [U32, ct.POINTER(U32), ct.POINTER(U32)]
    user.QueryDisplayConfig.argtypes = [U32, ct.POINTER(U32), ct.POINTER(Path),
                                       ct.POINTER(U32), ct.POINTER(Mode), ct.c_void_p]
    user.DisplayConfigGetDeviceInfo.argtypes = [ct.c_void_p]
    user.SetDisplayConfig.argtypes = [U32, ct.POINTER(Path), U32, ct.POINTER(Mode), U32]
    return user


def query():
    user = api()
    for _ in range(5):
        np, nm = U32(), U32()
        code = user.GetDisplayConfigBufferSizes(1, ct.byref(np), ct.byref(nm))
        if code:
            raise ct.WinError(code)
        paths, modes = (Path*np.value)(), (Mode*nm.value)()
        code = user.QueryDisplayConfig(1, ct.byref(np), paths, ct.byref(nm), modes, None)
        if code == 122:
            continue
        if code:
            raise ct.WinError(code)
        return list(paths)[:np.value], list(modes)[:nm.value]
    raise RuntimeError('显示布局持续变化，请稍后重试。')


def source_name(path):
    info = SourceName(type=1, size=ct.sizeof(SourceName), adapter=path.source.adapter, id=path.source.id)
    code = api().DisplayConfigGetDeviceInfo(ct.byref(info))
    if code:
        raise ct.WinError(code)
    return info.name


def target_name(path):
    info = TargetName(type=2, size=ct.sizeof(TargetName), adapter=path.target.adapter, id=path.target.id)
    code = api().DisplayConfigGetDeviceInfo(ct.byref(info))
    if code:
        raise ct.WinError(code)
    return info.path


def source_key(path):
    return path.source.adapter.low, path.source.adapter.high, path.source.id


def target_key(path):
    return path.target.adapter.low, path.target.adapter.high, path.target.id


def virtual_path(paths, optional=False):
    candidates = [p for p in paths if p.target.available and '#MTT1337#' in target_name(p).upper()]
    keys = {target_key(p) for p in candidates}
    if not keys and optional:
        return None
    if len(keys) != 1:
        raise RuntimeError('无法唯一定位 PadBridge 虚拟显示目标。')
    return next((p for p in candidates if p.flags & 1), candidates[0])


def current(optional=False):
    paths, _ = query()
    path = virtual_path(paths, optional=optional)
    if path is None:
        return None
    shared = any(p.flags & 1 and target_key(p) != target_key(path) and
                 source_key(p) == source_key(path) for p in paths)
    return source_name(path), bool(path.flags & 1), shared, target_name(path)


def plan(paths, modes, selected, width, height, x, y, refresh=60):
    """Keep every other active path and its exact mode records."""
    result = [p for p in paths if p.flags & 1 and target_key(p) != target_key(selected)]
    modes = list(modes)
    if width and height:
        target = Path.from_buffer_copy(selected)
        used = {source_key(p) for p in result}
        if source_key(target) in used:
            # IDDs may be routed through the physical GPU. On first install
            # Windows can clone the tablet onto its primary source. Allocate an
            # unused source on that same adapter instead of altering the primary.
            unused = [p for p in paths if source_key(p)[:2] == source_key(target)[:2]
                      and source_key(p) not in used]
            if not unused:
                raise RuntimeError('Windows 没有可分配给虚拟副屏的独立显示源。')
            target.source = Source.from_buffer_copy(unused[0].source)
        mode = Mode(type=1, id=target.source.id, adapter=target.source.adapter)
        mode.data.source = SourceMode(width, height, 4, wt.POINT(x, y))
        target.source.mode = len(modes)
        modes.append(mode)
        target.target.mode = INVALID
        target.target.rotation = 1
        target.target.refresh = Rational(refresh, 1)
        target.target.scanline = 1
        target.flags = 1
        result.append(target)
    if not result:
        raise RuntimeError('拒绝关闭最后一块屏幕。')
    return result, modes


def apply(width, height, x=0, y=0, refresh=60):
    paths, modes = query()
    paths, modes = plan(paths, modes, virtual_path(paths), width, height, x, y, refresh)
    pp, mm = (Path*len(paths))(*paths), (Mode*len(modes))(*modes)
    # Existing physical source and target modes remain fully specified. Windows
    # selects only the missing target timing for the virtual output.
    code = api().SetDisplayConfig(len(pp), pp, len(mm), mm, 0x20 | 0x80 | 0x200)
    if code:
        raise RuntimeError(f'Windows 未能应用虚拟副屏布局（{code}）。')
