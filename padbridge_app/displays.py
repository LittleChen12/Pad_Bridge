# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only mirroring and explicitly owned virtual X11 outputs."""
import json
import logging
from pathlib import Path
import re
import subprocess
import time
from odx11 import display
from .paths import MARKER, RUNTIME
from .video import mirror_size
from .display_layout import initial_layout, restore_positions
log = logging.getLogger('padbridge.display')


def record_ownership(data):
    temporary = MARKER.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(data), encoding='utf-8')
        temporary.replace(MARKER)
    finally:
        temporary.unlink(missing_ok=True)


def owned_connector():
    try:
        name = json.loads(MARKER.read_text())['connector']
        return name if re.fullmatch(r'card\d+-HDMI-A-\d+', name) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def choose_connector(root=Path('/sys/class/drm')):
    owned = owned_connector()
    for path in sorted(root.glob('card*-HDMI-A-*')):
        card = path.name.split('-', 1)[0]
        if (root / card / 'device/driver').resolve().name not in ('i915', 'xe', 'amdgpu'):
            continue
        status = (path / 'status').read_text().strip()
        if status == 'disconnected' or (path.name == owned and not (path / 'edid').read_bytes()):
            return path
    raise RuntimeError('没有找到可用的 Intel/AMD 空闲显示接口。')


def output_for_id(properties, connector_id):
    """Resolve PRIME names (e.g. HDMI-1-1) from xrandr's actual CONNECTOR_ID."""
    current = None
    matches = []
    for line in properties.splitlines():
        if line and not line[0].isspace():
            match = re.match(r'(\S+) (?:connected|disconnected)\b', line)
            current = match.group(1) if match else None
        match = re.match(r'\s+CONNECTOR_ID:\s*(\d+)\s*$', line)
        if match and current and int(match.group(1)) == connector_id:
            matches.append(current)
    if len(matches) != 1:
        raise RuntimeError(f'无法唯一定位显示接口（DRM ID {connector_id}）：{matches}')
    return matches[0]


def resolve_output(connector):
    properties = subprocess.check_output(['xrandr', '--prop'], text=True, timeout=10)
    return output_for_id(properties, int((connector / 'connector_id').read_text()))


def panel_mode(panel_w, panel_h, divisor, override=None):
    """CVT needs 8-pixel horizontal cells; NV12 needs even, not 16-aligned heights.

    Keeping the exact 1668 lines matters for native 2224×1668 iPad Air panels.
    H.264 encoders pad macroblocks internally and signal cropping in the SPS.
    """
    if override:
        w, h = max(override), min(override)
    else:
        w = max(8, round(max(panel_w, panel_h) / divisor / 8) * 8)
        h = max(2, round(min(panel_w, panel_h) / divisor / 2) * 2)
    return w, h, 'normal' if panel_w >= panel_h else 'left'


class HybridDisplay(display.VirtualDisplay):
    def __init__(self, cfg, connector, resolution=None, position='right'):
        if position not in ('left', 'right'):
            raise ValueError('副屏位置必须为左侧或右侧。')
        super().__init__(cfg)
        self.port = connector
        self.connector = connector.name.split('-', 1)[1]
        self.output = resolve_output(connector)
        self.resolution = resolution
        self.position = position
        self.layout_record = {}
        self._automatic_geometry = None

    def _force(self, value):
        # Only this instance's connector is ever changed; no sweeping HDMI cleanup.
        if value == 'on':
            if (self.port / 'edid').read_bytes():
                raise RuntimeError('这个接口刚接入了真实显示器，已取消创建副屏。')
            RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
            record_ownership({'connector': self.port.name, 'output': self.output})
        (self.port / 'status').write_text(value)

    def _apply_mode(self, args, size, first):
        self._xrandr(*args)
        if first and self.cfg.settle_timeout_s:
            # GNOME can finish a pending hotplug configuration after our modeset.
            # Verify the requested size before starting capture, with one recovery
            # confined to startup so later desktop changes are still respected.
            deadline = time.monotonic() + self.cfg.settle_timeout_s

            def size_changed():
                geom = self.geometry()
                return geom is None or (geom.w, geom.h) != size

            quiet = min(0.5, self.cfg.settle_timeout_s)
            if (self._wait_until(size_changed, quiet) and self._connected()
                    and not (self.port / 'edid').read_bytes()):
                log.info('热插拔配置覆盖了副屏模式，重新设置 %dx%d', *size)
                self._xrandr(*args)
                self._wait_until(size_changed, max(0, min(quiet, deadline - time.monotonic())))
        return self.geometry()

    def attach(self, panel_w, panel_h, device_cfg, limits=None):
        mw, mh, rotation = panel_mode(panel_w, panel_h, self.cfg.divisor,
                                     self.resolution or device_cfg.mode)
        if limits:
            mw, mh = display.fit_mode(mw, mh, rotation, limits.max_w, limits.max_h)
        ow, oh = (mw, mh) if rotation == 'normal' else (mh, mw)
        old_mode = self.mode_name
        name = self._ensure_mode(mw, mh)
        first = not self.attached
        if not self.forced:
            self._force('on')
            self.forced = True
        if first:
            # PRIME drivers may leave the cached connector state disconnected
            # until Xorg probes it, even after sysfs accepted the force request.
            if not self._connected():
                self._randr.get_screen_resources(self.root)
            if not self._wait_until(self._connected, self.cfg.connect_timeout_s):
                raise RuntimeError(f'{self.output} 没有响应虚拟显示请求。')
            self._wait_until(lambda: self.geometry() is not None, self.cfg.settle_timeout_s)
        main = self.main_geometry()
        g = self.geometry()
        enabled = {info.name: list(self._crtc_geometry(info.name)) for _, info, _ in self._outputs()
                   if info.name != self.output and info.crtc}
        automatic = (g is not None and g == self._automatic_geometry and
                     enabled == self.layout_record.get('layout_applied'))
        # GNOME may auto-enable a hotplugged output at 0,0; explicitly extend it.
        positions = []
        if first or g is None or (automatic and self.position == 'left'):
            before, primary = enabled, main
            if automatic:
                # A rotation changes the width of a left screen. Rebase from our
                # original arrangement; do not accumulate origin translations.
                before = self.layout_record['layout_before']
                primary = next(before[name] for name, current in enabled.items()
                               if current == list(main))
            (x, y), moved = initial_layout(before, primary, ow, self.position)
            self.layout_record = {'connector': self.port.name, 'output': self.output,
                                  'layout_before': before, 'layout_applied': moved}
            record_ownership(self.layout_record)
            for output, position in moved.items():
                if position != enabled[output]:
                    positions += ['--output', output, '--pos', f'{position[0]}x{position[1]}']
        else:
            x, y = g.x, g.y
        args = ('--output', self.output, '--mode', name, '--rotate', rotation,
                '--pos', f'{x}x{y}', *positions)
        g = self._apply_mode(args, (ow, oh), first)
        if g is None or (g.w, g.h) != (ow, oh):
            raise RuntimeError(f'副屏尺寸设置失败：需要 {ow}×{oh}，实际 {g}')
        if old_mode and old_mode != name:
            self._xrandr('--delmode', self.output, old_mode, check=False)
            self._xrandr('--rmmode', old_mode, check=False)
        self.attached = True
        self._automatic_geometry = g if first or automatic else None
        log.info('副屏已建立：%s %dx%d+%d+%d', self.output, g.w, g.h, g.x, g.y)
        return g

    def teardown(self):
        super().teardown()
        try:
            restore_positions(self.layout_record, self.output)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            log.warning('无法恢复桌面原点：%s', exc)
        if self.port.exists() and (self.port / 'status').read_text().strip() == 'disconnected':
            MARKER.unlink(missing_ok=True)


class MirrorDisplay(display.VirtualDisplay):
    """Read-only RandR adapter: capture the primary output, never set a mode."""
    def __init__(self, cfg, resolution=None):
        super().__init__(cfg)
        self.limits = None
        self.resolution = resolution

    def stream_size(self, geom, fps):
        return mirror_size(geom.w, geom.h, self.limits, self.resolution, fps)

    def attach(self, panel_w, panel_h, device_cfg, limits=None):
        self.limits = limits
        if self.output is None:
            primary = self._randr.get_output_primary(self.root).output
            enabled = [(oid, info.name) for oid, info, _ in self._outputs() if info.crtc]
            name = self.cfg.main_output
            if name is None:
                name = next((name for oid, name in enabled if oid == primary), None)
            if name is None and len(enabled) == 1:
                name = enabled[0][1]
            if name is None or name not in [name for _, name in enabled]:
                raise RuntimeError('未找到已启用的主屏幕，请先在系统中指定主屏。')
            self.output = name
        geom = self.geometry()
        if geom is None:
            raise RuntimeError('要镜像的主屏幕已停用。')
        self.attached = True
        log.info('镜像主屏：%s %dx%d+%d+%d（保留原显示设置）',
                 self.output, geom.w, geom.h, geom.x, geom.y)
        return geom

    def teardown(self):
        # The physical display belongs to the user; disconnect only ends capture.
        self.attached = False


def release():
    """Crash recovery, confined to the port recorded by our own display instance."""
    name = owned_connector()
    if not name:
        return
    port = Path('/sys/class/drm') / name
    if (port / 'edid').read_bytes():
        MARKER.unlink(missing_ok=True)
        return
    output = resolve_output(port)
    record = json.loads(MARKER.read_text())
    (port / 'status').write_text('detect')
    subprocess.run(['xrandr', '--output', output, '--off'], capture_output=True, timeout=10)
    restore_positions(record, output)
    MARKER.unlink(missing_ok=True)
