# SPDX-License-Identifier: GPL-3.0-or-later
"""Initial X11 placement and conservative recovery of our origin translation."""
import re
import subprocess


def initial_layout(outputs, primary, width, side):
    """Return virtual (x,y), other positions. X11 cannot use negative origins.

    Geometry values are (x,y,w,h). A left extension translates the desktop as
    one unit; existing output modes and relative arrangements stay unchanged.
    """
    if side not in ('left', 'right'):
        raise ValueError('副屏位置必须为左侧或右侧。')
    x = (min((g[0] for g in outputs.values()), default=primary[0]) - width
         if side == 'left' else max((g[0]+g[2] for g in outputs.values()), default=primary[0]+primary[2]))
    # xrandr normalizes the whole framebuffer even when every coordinate is
    # positive. Account for that explicitly, including a hotplug-restored layout
    # or a narrower portrait screen, so our ownership record matches reality.
    dx = -min([x, *(g[0] for g in outputs.values())])
    dy = -min([primary[1], *(g[1] for g in outputs.values())])
    moved = {name: [g[0]+dx, g[1]+dy, *g[2:]] for name, g in outputs.items()}
    return (x+dx, primary[1]+dy), moved


def read_layout():
    result = subprocess.check_output(['xrandr', '--query'], text=True, timeout=10)
    pattern = r'^(\S+) connected (?:primary )?(\d+)x(\d+)\+(-?\d+)\+(-?\d+)\b'
    return {name: [int(x), int(y), int(w), int(h)]
            for name, w, h, x, y in re.findall(pattern, result, re.MULTILINE)}


def restore_positions(record, owned):
    """Undo only an exact translation still owned by us, never a manual layout."""
    before, applied = record.get('layout_before'), record.get('layout_applied')
    if not isinstance(before, dict) or not isinstance(applied, dict) or before == applied:
        return
    current = {name: g for name, g in read_layout().items() if name != owned}
    if current != applied or set(before) != set(applied):
        return
    args = []
    for name, g in before.items():
        if (not isinstance(g, list) or len(g) != 4 or
                any(type(v) is not int or v < 0 for v in g) or g[2:] != applied[name][2:]):
            return
        args.extend(['--output', name, '--pos', f'{g[0]}x{g[1]}'])
    if args:
        subprocess.run(['xrandr', *args], check=True, capture_output=True, timeout=10)
