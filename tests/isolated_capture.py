# SPDX-License-Identifier: GPL-3.0-or-later
"""Real capture/resize regression in an invisible nested X server.

Only a blank Xephyr display is resized. No physical monitor settings change,
no screen contents are saved, and no packets are sent to an iPad.
Run in the PadBridge launcher environment.
"""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time


def child(unprotected=False):
    from types import SimpleNamespace
    import padbridge_app.encoding as backend
    from odx11 import config, pipeline
    from odx11.display import Geometry
    from gi.repository import GLib
    backend.NativePipeline.encoder = backend.select_encoder()
    if unprotected:
        backend.x11_capture.install = lambda _: SimpleNamespace(generation=0)
    cfg = config.parse({'video': {'preset':'custom', 'fps':30, 'convert':'cpu',
                                  'change_tail_ms':0, 'idle_pause_s':0}})
    frames, errors, sizes = [0,0], [], []
    current, stage = [None], [0]
    loop = GLib.MainLoop()
    failures = []

    def receive(data, keyframe, timestamp):
        frames[stage[0]] += 1

    def recover(message):
        errors.append(message)
        current[0].stop()
        if stage[0] == 1:
            failures.append('second capture failed')
            loop.quit()
            return
        stage[0] = 1
        build(Geometry(0, 0, 640, 480), (320, 240))

    def build(geometry, output):
        p = backend.NativePipeline(geometry, cfg.video, os.environ['DISPLAY'],
                                   receive, recover, fps=30, output_size=output)
        current[0] = p
        p.start()

    def shrink():
        try:
            from Xlib import display
            caps = current[0].sink.get_static_pad('sink').get_current_caps().get_structure(0)
            sizes.append([caps.get_value('width'), caps.get_value('height')])
            host = display.Display(os.environ['PADBRIDGE_TEST_HOST'])
            host.create_resource_object('window', int(os.environ['PADBRIDGE_TEST_PARENT'])).configure(width=640, height=480)
            host.sync()
            host.close()
        except Exception as exc:
            failures.append(str(exc))
            loop.quit()
        return False

    build(Geometry(800, 0, 480, 640), (240, 320))
    GLib.timeout_add(800, shrink)
    GLib.timeout_add(2300, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
        caps = current[0].sink.get_static_pad('sink').get_current_caps().get_structure(0)
        sizes.append([caps.get_value('width'), caps.get_value('height')])
    finally:
        current[0].stop()
    assert not failures, failures
    assert min(frames) >= 5, (frames, errors)
    assert errors, 'resize race was not exercised'
    assert sizes == [[240,320],[320,240]], sizes
    print(json.dumps({'frames_before_after':frames,'recovered_errors':len(errors),'video_sizes':sizes}), flush=True)


def parent():
    from Xlib import X, display
    host = display.Display()
    parent_window = host.screen().root.create_window(-4000, -4000, 1280, 960, 0,
                         X.CopyFromParent, X.InputOutput, X.CopyFromParent,
                         override_redirect=True)
    # A mapped, offscreen parent delivers resize events without covering work.
    parent_window.map()
    host.sync()
    results = {}
    try:
        for unprotected in (True, False):
            parent_window.configure(width=1280, height=960)
            host.sync()
            read_fd, write_fd = os.pipe()
            with tempfile.TemporaryFile() as log:
                server = subprocess.Popen(['Xephyr','-parent',str(parent_window.id),'-screen','1280x960',
                       '-resizeable','-noreset','-nolisten','tcp','-ac','-displayfd',str(write_fd)],
                       pass_fds=(write_fd,), stdout=log, stderr=log)
                os.close(write_fd)
                try:
                    if not select.select([read_fd],[],[],8)[0]:
                        raise RuntimeError('Nested X server did not start')
                    name = ':' + os.read(read_fd, 32).decode().strip()
                    children = parent_window.query_tree().children
                    if len(children) != 1:
                        raise RuntimeError('Nested server window could not be identified')
                    env = {**os.environ, 'DISPLAY':name, 'PADBRIDGE_TEST_HOST':os.environ['DISPLAY'],
                           'PADBRIDGE_TEST_PARENT':str(children[0].id)}
                    query = subprocess.run(['xrandr'], env=env, capture_output=True, text=True, check=True)
                    if 'default connected' not in query.stdout:
                        raise RuntimeError(query.stdout)
                    cmd = [sys.executable, __file__, '--child'] + (['--unprotected'] if unprotected else [])
                    try:
                        run = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=12)
                    except subprocess.TimeoutExpired as exc:
                        # The old default X handler can also deadlock during exit.
                        out = exc.stdout or b''
                        err = exc.stderr or b''
                        run = subprocess.CompletedProcess(cmd, 124,
                                out.decode(errors='replace') if isinstance(out, bytes) else out,
                                err.decode(errors='replace') if isinstance(err, bytes) else err)
                    key = 'baseline' if unprotected else 'protected'
                    results[key] = {'returncode':run.returncode, 'output':run.stdout.strip(), 'stderr':run.stderr[-1800:]}
                    if unprotected:
                        assert run.returncode != 0 and 'BadMatch' in run.stderr, results[key]
                    else:
                        assert run.returncode == 0, results[key]
                finally:
                    os.close(read_fd)
                    server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
    finally:
        parent_window.destroy()
        host.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if '--child' in sys.argv:
        child('--unprotected' in sys.argv)
    else:
        parent()
