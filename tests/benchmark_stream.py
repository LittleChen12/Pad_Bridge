# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in live extension benchmark. Draws only on the ready, non-primary output.

Does not start/stop a stream or save screen pixels. Run with the same Python
environment as smoke_capture.py; results belong in the ignored validation/ folder.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
from odx11 import state


def measure(output, duration):
    rows, errors, windows = [], [], []
    ready_at = time.monotonic()
    started = [None]
    target = [None]
    worker = [None]

    def finish(error=None):
        if error:
            errors.append(error)
        for window in windows:
            window.destroy()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'samples':rows, 'errors':errors}, indent=2))
        Gtk.main_quit()
        return False

    def draw(widget, cr):
        elapsed = time.monotonic() - started[0]
        offset = (elapsed * 160) % 90 if int(elapsed // 30) % 2 else 0
        cr.set_source_rgb(.95, .96, .98)
        cr.paint()
        for i in range(14):
            y = i * 90 - offset
            cr.set_source_rgb(.2, .35, .65)
            cr.rectangle(30, y, 1140, 3)
            cr.fill()
            cr.set_font_size(24)
            cr.move_to(45, y + 45)
            cr.show_text(f'PadBridge desktop scrolling sample / row {i:02d}')
        return False

    def ready():
        facts = state.read()
        w, h, x, y = facts.get('monitor', [0,0,0,0])
        desktop = Gdk.Display.get_default()
        monitor = desktop.get_monitor_at_point(x+1, y+1)
        rect = monitor.get_geometry()
        if (facts.get('state') != state.STREAMING or monitor.is_primary() or
                (rect.x,rect.y,rect.width,rect.height) != (x,y,w,h)):
            if time.monotonic()-ready_at > 20:
                return finish('No ready extension matching the stream; no test window was shown.')
            return True
        worker[0], target[0] = facts['pid'], facts['monitor']
        window = Gtk.Window(title='PadBridge performance check')
        window.set_default_size(min(1200,w-100), min(950,h-100))
        window.set_accept_focus(False)
        window.set_decorated(False)
        # A benchmark canvas is not a normal desktop window: the window manager
        # must not move it to the primary display during placement or teardown.
        window.realize()
        window.get_window().set_override_redirect(True)
        window.move(x+50, y+50)
        area = Gtk.DrawingArea()
        area.connect('draw', draw)
        window.add(area)
        windows.append(window)
        started[0] = time.monotonic()
        window.show_all()
        window.move(x+50, y+50)
        GLib.timeout_add(17, lambda: (area.queue_draw(), True)[1])
        GLib.timeout_add_seconds(1, sample)
        return False

    def sample():
        elapsed = time.monotonic()-started[0]
        facts = state.read()
        if (facts.get('state') != state.STREAMING or facts.get('monitor') != target[0]
                or facts.get('pid') != worker[0]):
            return finish('Stream or layout changed; stopped the test canvas.')
        x, y = windows[0].get_position()
        w, h, sx, sy = target[0]
        if not (sx <= x < sx+w and sy <= y < sy+h):
            return finish('Test canvas moved outside the extension.')
        try:
            proc = Path(f'/proc/{worker[0]}/stat').read_text().rsplit(')',1)[1].split()
            ticks = int(proc[11])+int(proc[12])
        except (OSError, ValueError, IndexError):
            return finish('Worker resource counters unavailable.')
        try:
            gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=pstate,power.draw,utilization.gpu,utilization.encoder,clocks.gr,clocks.mem',
                                          '--format=csv,noheader,nounits'], text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
        except (OSError, subprocess.SubprocessError):
            gpu = None
        rows.append({'elapsed': round(elapsed,2), 'phase':'scroll' if int(elapsed//30)%2 else 'static',
                     'facts':facts, 'cpu_seconds': ticks/os.sysconf('SC_CLK_TCK'), 'gpu':gpu,
                     'canvas_position':[x,y]})
        return finish() if elapsed >= duration else True

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: finish('Interrupted'))
    GLib.timeout_add(100, ready)
    Gtk.main()
    print(json.dumps({'samples':len(rows), 'output':str(output), 'errors':errors}))
    return 1 if errors else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=int, default=185)
    args = parser.parse_args()
    raise SystemExit(measure(args.output, max(1,args.duration)))
