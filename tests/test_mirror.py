# SPDX-License-Identifier: GPL-3.0-or-later
import ctypes
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from padbridge_app import service as app, preferences as preference_store
from padbridge_app.displays import MirrorDisplay, mirror_size
from odx11 import config, protocol
from odx11.display import Geometry, VirtualDisplay
from odx11.daemon import Session
from padbridge_app.video import VideoOptions
from padbridge_app.x11_capture import CaptureGuard, XErrorEvent


class MirrorTests(unittest.TestCase):
    def test_mirror_never_changes_or_tears_down_physical_output(self):
        cfg = config.parse({}).display
        with patch.object(VirtualDisplay, '__init__', return_value=None), patch.object(VirtualDisplay, '_xrandr') as write:
            screen = MirrorDisplay(cfg)
            screen.cfg, screen.output, screen.root = cfg, None, object()
            screen._randr = Mock()
            screen._randr.get_output_primary.return_value.output = 9
            screen._outputs = lambda: [(9, SimpleNamespace(name='eDP-1', crtc=1), None)]
            geom = Geometry(100, 50, 2560, 1600)
            screen._crtc_geometry = Mock(return_value=geom)
            for panel in ((2224, 1668), (1668, 2224)):
                self.assertEqual(screen.attach(*panel, None), geom)
                self.assertEqual(screen.geometry(), geom)
                screen.teardown()
            write.assert_not_called()

    def test_mirror_scales_video_not_capture_or_touch_coordinates(self):
        self.assertEqual(mirror_size(2560, 1600), (2560, 1600))
        self.assertEqual(mirror_size(2560, 1600, bound=(1920, 1440)), (1920, 1200))
        self.assertEqual(mirror_size(2560, 1600, protocol.DecodeLimits(max_w=1280)), (1280, 800))
        w, h = mirror_size(2560, 1600, protocol.DecodeLimits(max_pps=1280*800*60))
        self.assertLessEqual(w*h*60, 1280*800*60)

    def test_decode_budget_counts_encoded_video_not_large_source(self):
        cfg = config.parse({'video': {'preset': 'custom', 'fps': 60, 'change_tail_ms': 0, 'idle_pause_s': 0}})
        source = Geometry(0, 0, 3840, 2160)
        screen = Mock()
        screen.attach.return_value = source
        screen.stream_size.return_value = (1920, 1080)
        create = Mock(return_value=Mock())
        injector = Mock()
        session = Session(cfg, Mock(), screen, injector, create)
        session.on_payload(json.dumps({'type': 'hello', 'pixelsWide': 2224, 'pixelsHigh': 1668,
                           'videoCaps': [{'codec': 'h264', 'maxPixelsPerSecond': 1920*1080*60}]}).encode())
        self.assertEqual(create.call_args.kwargs['fps'], 60)
        injector.set_geometry.assert_called_with(source)
        session._stop_pipeline()


    def test_ready_callback_resyncs_current_cursor_and_ignores_retired_streams(self):
        cfg = config.parse({'video': {'preset':'custom', 'fps':60, 'idle_pause_s':0, 'change_tail_ms':0}})
        screen = SimpleNamespace(attach=lambda w,h,*a,**kw: Geometry(0,0,w,h))
        pipes = []
        def make(*args, **kwargs):
            p = SimpleNamespace(on_ready=None, start=lambda:None, stop=lambda:None)
            pipes.append(p)
            return p
        session = Session(cfg, Mock(), screen, Mock(), make)
        session._reset_cursor = Mock()
        session.on_payload(json.dumps({'type':'hello','pixelsWide':2560,'pixelsHigh':1600}).encode())
        session._reset_cursor.reset_mock()
        pipes[0].on_ready()
        session._reset_cursor.assert_called_once_with(Geometry(0,0,2560,1600))
        session.on_payload(json.dumps({'type':'hello','pixelsWide':2224,'pixelsHigh':1668}).encode())
        session._reset_cursor.reset_mock()
        pipes[0].on_ready()
        session._reset_cursor.assert_not_called()
        pipes[1].on_ready()
        session._reset_cursor.assert_called_once_with(Geometry(0,0,2224,1668))
        session._stop_pipeline()
        session._reset_cursor.reset_mock()
        pipes[1].on_ready()
        session._reset_cursor.assert_not_called()

    def test_only_shm_get_image_badmatch_is_intercepted(self):
        guard = CaptureGuard.__new__(CaptureGuard)
        guard.generation, guard.shm_opcode = 0, 130
        guard.previous = Mock(return_value=7)
        event = XErrorEvent(error_code=8, request_code=130, minor_code=4)
        self.assertEqual(guard._handle(None, ctypes.pointer(event)), 0)
        self.assertEqual(guard.generation, 1)
        guard.previous.assert_not_called()
        for error, request, minor in ((3,130,4), (8,131,4), (8,130,1)):
            event = XErrorEvent(error_code=error, request_code=request, minor_code=minor)
            self.assertEqual(guard._handle(None, ctypes.pointer(event)), 7)
        self.assertEqual(guard.generation, 1)

    def test_new_dimensions_announced_before_first_frame_after_each_change(self):
        cfg = config.parse({'video': {'preset':'custom', 'fps':60, 'idle_pause_s':0, 'change_tail_ms':0}})
        sent = []
        screen = SimpleNamespace()
        screen.attach = lambda w,h,*a,**kw: Geometry(0,0,w,h)
        def make(geom, on_au, on_error, fps):
            return SimpleNamespace(stream_config={'type':'streamConfig','codec':'h264',
                        'width':geom.w,'height':geom.h,'framesPerSecond':fps},
                    start=lambda: on_au(b'\x00\x00\x00\x01\x65frame',True), stop=lambda:None)
        session = Session(cfg, sent.append, screen, Mock(), make)
        session.on_payload(json.dumps({'type':'hello','pixelsWide':2560,'pixelsHigh':1600}).encode())
        first = json.loads(sent[1][4:])
        self.assertEqual((first['width'],first['height']), (2560,1600))
        self.assertIn(b'\x00\x00\x00\x01',sent[2])
        sent.clear()
        session.on_payload(json.dumps({'type':'hello','pixelsWide':2224,'pixelsHigh':1668}).encode())
        second = json.loads(sent[1][4:])
        self.assertEqual((second['width'],second['height']), (2224,1668))
        self.assertIn(b'\x00\x00\x00\x01',sent[2])
        session._stop_pipeline()


class VideoOptionsTests(unittest.TestCase):
    def test_defaults_keep_existing_transport_profiles(self):
        video = VideoOptions()
        self.assertEqual((video.fps, video.size), (60, None))
        self.assertEqual(video.bitrate('usb'), 24000)
        self.assertEqual(video.bitrate('wifi'), 10000)
        self.assertEqual(VideoOptions(bitrate_mbps=18).bitrate('wifi'), 18000)

    def test_invalid_inputs_are_rejected_before_display_is_touched(self):
        for options in ({'resolution':'1921x1080'}, {'resolution':'640x481'},
                        {'resolution':'1200x1600'}, {'resolution':'9999x8888'},
                        {'resolution':'1920x1080;exit'}, {'fps':0}, {'fps':121},
                        {'fps':True}, {'bitrate_mbps':-1}, {'bitrate_mbps':51}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                VideoOptions(**options)

    def test_saved_old_preferences_migrate_without_losing_wifi(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(preference_store, 'PREFERENCES', Path(folder)/'prefs.json'):
            preference_store.PREFERENCES.write_text(json.dumps({'transport':'wifi','address':'192.0.2.42:9000','name':'iPad'}))
            prefs = app.preferences()
            self.assertEqual(prefs['display_mode'], 'extend')
            self.assertEqual(prefs['video_options'], VideoOptions().to_dict())
            self.assertEqual(prefs['address'], '192.0.2.42:9000')
            self.assertEqual(prefs['display_position'], 'right')

    def test_mirror_launch_needs_no_connector_permission_and_passes_settings(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(preference_store, 'PREFERENCES', Path(folder)/'prefs.json'), \
                patch.object(app, 'active', return_value=False), patch.object(app, 'authorize') as auth, \
                patch.object(app.subprocess, 'run') as run:
            video = VideoOptions('1920x1440', 30, 8)
            app.start('usb', display_mode='mirror', video=video)
            auth.assert_not_called()
            command = run.call_args.args[0]
            for flag, value in (('--display-mode','mirror'),('--resolution','1920x1440'),('--fps','30'),('--bitrate','8')):
                self.assertEqual(command[command.index(flag)+1], value)
            self.assertEqual(app.preferences()['video_options'], video.to_dict())

    def test_extend_position_is_saved_and_passed_only_after_validation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(preference_store, 'PREFERENCES', Path(folder)/'prefs.json'), \
                patch.object(app, 'active', return_value=False), patch.object(app, 'authorize') as auth, \
                patch.object(app.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                app.start('usb', display_position='above')
            auth.assert_not_called()
            run.assert_not_called()
            for position in ('left', 'below'):
                with self.subTest(position=position):
                    app.start('usb', display_position=position)
                    command = run.call_args.args[0]
                    self.assertEqual(command[command.index('--display-position')+1], position)
                    self.assertEqual(app.preferences()['display_position'], position)

    def test_changing_running_parameters_requires_stop(self):
        with patch.object(app, 'active', return_value=True), patch.object(app, 'current_status', return_value={}), \
                patch.object(app.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                app.start(video=VideoOptions(fps=30))
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
