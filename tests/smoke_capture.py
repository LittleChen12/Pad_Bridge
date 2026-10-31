"""Live X11 → NVENC regression: valid keyframes and segment-correct timestamps.

Run explicitly in the launcher's environment; does not save or transmit pixels.
"""
import json
import time
import os
import sys
import threading
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GLib
from padbridge_app.encoding import NativePipeline, select_encoder
from odx11 import config, annexb
from odx11.display import Geometry

NativePipeline.encoder = (sys.argv[sys.argv.index('--encoder')+1] if '--encoder' in sys.argv
                          else select_encoder())
if '--wifi' in sys.argv:
    NativePipeline.transport = 'wifi'
    NativePipeline.bitrate_kbps = 10000
cfg = config.parse({'video': {'preset': 'custom', 'convert': 'cpu',
                            'change_tail_ms': 0, 'idle_pause_s': 0}})
frames, errors, delays = [], [], []
ready = []
main_thread = threading.get_ident()
loop = GLib.MainLoop()


def validate_frame(data, keyframe, capture_ms):
    nals = annexb.split_nals(data)
    assert data.startswith(annexb.START)
    if keyframe:
        types = {annexb.nal_type(nal) for nal in nals}
        assert {7, 8, 5}.issubset(types)
    frames.append(keyframe)
    assert capture_ms is not None
    delay = time.time() * 1000 - capture_ms
    assert -10 < delay < 1000, f'Invalid capture timestamp: delay {delay} ms'
    delays.append(delay)


def receive(data, keyframe, capture_ms):
    try:
        validate_frame(data, keyframe, capture_ms)
        if '--slow-send' in sys.argv:
            time.sleep(.08)
    except Exception as exc:
        errors.append(str(exc))
        GLib.idle_add(lambda: (loop.quit(), False)[1])


def error(message):
    errors.append(message)
    loop.quit()


p = NativePipeline(Geometry(0, 0, 160, 120), cfg.video, os.environ.get('DISPLAY', ':0'), receive, error, fps=30)
p.on_ready = lambda: ready.append((threading.get_ident(), len(frames)))
try:
    p.start()
    GLib.timeout_add(500, lambda: (p.force_idr(), False)[1])
    GLib.timeout_add_seconds(2, lambda: (loop.quit(), False)[1])
    loop.run()
finally:
    p.stop()
assert not errors, errors
assert len(frames) >= 15 and sum(frames) >= 2, (len(frames), sum(frames))
if '--slow-send' in sys.argv:
    assert p.statistics()['backpressure_drops'] > 0
assert len(ready) == 1 and ready[0][0] == main_thread and ready[0][1] > 0, ready
print(json.dumps({'encoder': NativePipeline.encoder, 'frames': len(frames), 'keyframes': sum(frames),
                  'backpressure_drops': p.statistics()['backpressure_drops'],
                  'capture_to_callback_ms': [round(min(delays), 1), round(max(delays), 1)]}))
