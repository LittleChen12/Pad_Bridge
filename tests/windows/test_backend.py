# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
from types import SimpleNamespace
import plistlib
import socket
import struct
import threading
from unittest.mock import Mock, patch

import pytest
from odx11 import protocol, usbmux
from padbridge_app import preferences
from padbridge_app.video import VideoOptions, mirror_size
from padbridge_app.windows import desktop, encoding, service, storage, transport, worker

HELLO = {'type': 'hello', 'pv': 3, 'id': 'test-only', 'pixelsWide': 2224, 'pixelsHigh': 1668}
MAIN = desktop.Monitor('primary', 0, 0, 2560, 1600, True)
SECOND = desktop.Monitor('secondary', -1920, 0, 1920, 1080)


def test_primary_is_selected_by_flag_not_enumeration_order():
    assert desktop.choose_monitor('mirror', available=[SECOND, MAIN]) == MAIN


def test_graphics_capture_uses_exact_monitor_identity():
    outputs = [[SimpleNamespace(devicename='secondary')], [SimpleNamespace(devicename='primary')]]
    assert desktop.graphics_output(outputs, 'primary') == (1, 0)
    with pytest.raises(RuntimeError):
        desktop.graphics_output(outputs, 'missing')
    with pytest.raises(RuntimeError):
        desktop.graphics_output(outputs + outputs, 'primary')


def test_recreated_graphics_monitor_uses_fresh_adapter_and_output():
    primary = SimpleNamespace(devicename='primary')
    old = SimpleNamespace(devicename='retired-virtual')
    new = SimpleNamespace(devicename='new-virtual')
    before = SimpleNamespace(enum_outputs=lambda: [primary, old])
    after = SimpleNamespace(enum_outputs=lambda: [new, primary])
    backend = SimpleNamespace(enum_dxgi_adapters=Mock(side_effect=[[before], [after]]),
                              Device=lambda adapter: adapter, Output=lambda pointer: pointer,
                              DXCamera=Mock(side_effect=lambda **kwargs: kwargs))
    # The library's import-time singleton still describes the retired monitor.
    setattr(backend, '__factory', SimpleNamespace(outputs=[[primary, old]]))
    first = desktop.create_graphics_camera(backend, old.devicename)
    second = desktop.create_graphics_camera(backend, new.devicename)
    assert first['device'] is before and first['output'] is old
    assert second['device'] is after and second['output'] is new
    assert second['backend'] == 'winrt'
    assert backend.enum_dxgi_adapters.call_count == 2


def test_unavailable_graphics_capture_falls_back_to_gdi():
    with patch.object(desktop, 'GraphicsCapture', side_effect=RuntimeError('no WGC')), \
            patch.object(desktop, 'Capture', return_value='fallback') as fallback:
        assert desktop.create_capture(MAIN) == 'fallback'
        fallback.assert_called_once_with(MAIN)


def test_nvenc_low_latency_settings_emit_the_first_frame_immediately():
    try:
        encoder = encoding.Encoder('h264_nvenc', (640, 400), 30, 3000)
    except Exception:
        pytest.skip('NVENC is unavailable on this machine; software path is covered separately')
    try:
        output = encoder.encode_bgra(bytes(640*400*4), 640, 400)
        assert len(output) == 1 and output[0][1], 'NVENC must not queue multiple frames'
        assert encoder.context.options == {}, 'unsupported codec options must not silently linger'
    finally:
        encoder.close()


def test_extension_requires_existing_nonprimary_monitor():
    assert desktop.choose_monitor('extend', 'secondary', [MAIN, SECOND]) == SECOND
    for screens, name in (([MAIN], ''), ([MAIN, SECOND], 'primary'),
                          ([MAIN, SECOND, desktop.Monitor('third', 2560, 0, 1280, 720)], '')):
        with pytest.raises(RuntimeError, match='副屏'):
            desktop.choose_monitor('extend', name, screens)


def test_nvenc_gradual_refresh_avoids_periodic_idr_pulses_but_honors_recovery():
    import av
    try:
        encoder = encoding.Encoder('h264_nvenc', (320, 200), 15, 1000)
    except Exception:
        pytest.skip('NVENC unavailable')
    decoder = av.CodecContext.create('h264', 'r')
    keyframes = []
    try:
        for index in range(72):
            if index == 65:
                encoder.force_keyframe = True
            packets = encoder.encode_bgra(bytes(320*200*4), 320, 200)
            assert len(packets) == 1
            data, idr = packets[0]
            assert len(decoder.decode(av.Packet(data))) == 1
            if idr:
                keyframes.append(index)
        assert keyframes == [0, 65]
    finally:
        encoder.close()


def test_portrait_and_negative_origin_preserve_capture_geometry():
    source = desktop.Monitor('portrait', -1200, -100, 1200, 1920)
    size, fps = worker.stream_options(HELLO, source, VideoOptions('1920x1080', 30))
    assert size == (674, 1080) and fps == 30
    assert (source.x, source.y, source.w, source.h) == (-1200, -100, 1200, 1920)


def test_decode_budget_and_frame_rate_are_respected():
    hello = {**HELLO, 'displayMaxFrameRate': 30,
             'videoCaps': [{'codec': 'h264', 'maxWidth': 1920, 'maxHeight': 1200,
                            'maxFrameRate': 24, 'maxPixelsPerSecond': 1280*800*24}]}
    (width, height), fps = worker.stream_options(hello, MAIN, VideoOptions())
    assert fps == 24
    assert width*height*fps <= 1280*800*24
    assert width <= 1920 and height <= 1200 and width % 2 == height % 2 == 0
    assert mirror_size(2560, 1600, bound=(1920, 1440)) == (1920, 1200)


@pytest.mark.parametrize('value', [float('inf'), float('nan'), 0.1])
def test_nonsensical_decoder_limits_are_rejected_or_ignored(value):
    hello = {**HELLO, 'videoCaps': [{'codec': 'h264', 'maxWidth': value}]}
    if value != value:  # upstream treats NaN as absent
        assert worker.stream_options(hello, MAIN, VideoOptions())[0] == (2560, 1600)
    else:
        with pytest.raises(ValueError):
            worker.stream_options(hello, MAIN, VideoOptions())


@pytest.mark.parametrize('hello', [{}, {**HELLO, 'pv': 4}, {**HELLO, 'pv': True},
                                   {'type': 'hello', 'pv': 2}])
def test_bad_handshake_is_rejected_before_capture(hello):
    with pytest.raises(ValueError):
        worker.validate_hello(hello)


def test_receiver_identity_is_checked_on_reconnect():
    with pytest.raises(ValueError, match='身份'):
        worker.validate_hello(HELLO, 'another-receiver')
    assert worker.validate_hello(HELLO, 'test-only') is HELLO


def test_unicode_preferences_are_atomic_and_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / '中文设置' / 'connection.json'
    monkeypatch.setattr(preferences, 'PREFERENCES', path)
    preferences.save_preferences({'transport': 'wifi', 'address': 'ipad.local:9000', 'name': '我的 iPad',
                                  'display_mode': 'mirror', 'display_position': 'left',
                                  'video_options': VideoOptions(fps=30).to_dict()})
    assert preferences.preferences()['name'] == '我的 iPad'
    assert preferences.preferences()['video_options']['fps'] == 30
    assert preferences.preferences()['display_position'] == 'left'
    assert '我的 iPad' in path.read_text(encoding='utf-8')
    assert len(list(path.parent.iterdir())) == 1


def test_corrupt_preferences_fall_back(tmp_path, monkeypatch):
    path = tmp_path / 'connection.json'
    monkeypatch.setattr(preferences, 'PREFERENCES', path)
    for body in ('broken', '[]', '{"transport":"invalid"}'):
        path.write_text(body, encoding='utf-8')
        assert preferences.preferences()['display_mode'] == 'mirror'
        assert preferences.preferences()['display_position'] == 'right'


@pytest.mark.parametrize('extra', [{}, {'display_position': ['left']}])
def test_old_or_invalid_position_keeps_other_preferences(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(preferences, 'PREFERENCES', tmp_path/'connection.json')
    preferences.save_preferences({'transport': 'wifi', 'address': 'ipad.local:9000', **extra})
    saved = preferences.preferences()
    assert saved['display_position'] == 'right'
    assert saved['transport'] == 'wifi' and saved['address'] == 'ipad.local:9000'


class FakeMux:
    def __init__(self, reply=None, raw=None):
        self.server = socket.socket()
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(1)
        self.endpoint = self.server.getsockname()
        self.reply = usbmux.encode(reply or {}) if raw is None else raw
        self.request = None
        self.error = None

    def __enter__(self):
        def serve():
            try:
                self.server.settimeout(3)
                with self.server.accept()[0] as peer:
                    peer.settimeout(3)
                    header = usbmux.HEADER.unpack(usbmux._recv_exact(peer, 16))
                    self.request = plistlib.loads(usbmux._recv_exact(peer, header[0]-16))
                    for offset in range(0, len(self.reply), 7):
                        peer.sendall(self.reply[offset:offset+7])
                    peer.recv(1)
            except OSError as exc:
                self.error = exc
            finally:
                self.server.close()
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.thread.join(4)
        assert not self.thread.is_alive()


def test_windows_usbmux_tcp_fragmentation_and_usb_filter():
    devices = [{'DeviceID': n, 'Properties': {'ConnectionType': kind}}
               for n, kind in ((1, 'USB'), (2, 'Network'))]
    with FakeMux({'DeviceList': devices}) as peer:
        assert transport.list_devices(peer.endpoint) == devices[:1]
    assert peer.request['MessageType'] == 'ListDevices'


def test_windows_usbmux_network_order_port_and_failed_connect():
    with FakeMux({'Number': 0}) as peer:
        transport.connect_usb(42, peer.endpoint).close()
    assert peer.request['DeviceID'] == 42
    assert peer.request['PortNumber'] == socket.htons(9000)
    with FakeMux({'Number': 3}) as peer:
        with pytest.raises(usbmux.MuxError):
            transport.connect_usb(42, peer.endpoint)


@pytest.mark.parametrize('length', [0, 15, 16, 2**31])
def test_mux_rejects_bad_lengths_without_reading_body(length):
    with FakeMux(raw=struct.pack('<IIII', length, 1, 8, 1)) as peer:
        with pytest.raises(ValueError):
            transport.list_devices(peer.endpoint)


def test_state_roundtrip_handles_utf8_and_invalid_json(tmp_path):
    path = tmp_path / 'state.json'
    storage.write_json(path, {'problem': '连接中断'})
    assert storage.read_json(path) == {'problem': '连接中断'}
    path.write_text('[]', encoding='utf-8')
    assert storage.read_json(path) == {}


def test_stale_pid_is_never_treated_as_owned():
    process = Mock()
    process.create_time.return_value = 200
    facts = {'pid': 123, 'created': 100, 'token': 'generation'}
    with patch('psutil.Process', return_value=process):
        assert storage.owned_process(facts) is None
    process.cmdline.assert_not_called()
    process.terminate.assert_not_called()


def test_same_pid_and_birth_time_still_requires_worker_token():
    process = Mock()
    process.create_time.return_value = 100
    process.cmdline.return_value = ['python.exe', 'app.py', 'run', '--worker-token', 'other-generation']
    with patch('psutil.Process', return_value=process):
        assert storage.owned_process({'pid': 123, 'created': 100, 'token': 'generation'}) is None


def test_running_worker_refuses_changed_wifi_endpoint():
    facts = {'transport': 'wifi', 'display_mode': 'mirror', 'address': '192.0.2.1:9000',
             'video_options': VideoOptions().to_dict()}
    with patch.object(storage, 'Lock'), patch.object(service, 'active', return_value=True), \
            patch.object(service, 'current_status', return_value=facts), \
            patch.object(service.subprocess, 'Popen') as launch:
        with pytest.raises(RuntimeError, match='断开'):
            service.start('wifi', '192.0.2.2', 'mirror', VideoOptions())
        launch.assert_not_called()


def test_running_extension_refuses_position_change_until_reconnect():
    facts = {'transport': 'usb', 'display_mode': 'extend', 'monitor': 'auto',
             'display_position': 'right', 'video_options': VideoOptions().to_dict()}
    with patch.object(storage, 'Lock'), patch.object(service, 'active', return_value=True), \
            patch.object(service, 'current_status', return_value=facts), \
            patch.object(service.subprocess, 'Popen') as launch:
        with pytest.raises(RuntimeError, match='断开'):
            service.start('usb', '', 'extend', VideoOptions(), monitor='auto', display_position='left')
        launch.assert_not_called()


def test_software_encoder_produces_decodable_annexb_and_requested_keyframe():
    import av
    encoder = encoding.Encoder('libx264', (640, 400), 30, 3000)
    decoder = av.CodecContext.create('h264', 'r')
    frames, keyframes = [], []
    try:
        for index in range(6):
            if index == 3:
                encoder.force_keyframe = True
            for data, idr in encoder.encode_bgra(bytes(640*400*4), 640, 400):
                assert data.startswith(b'\0\0\0\1')
                keyframes.append((index, idr))
                frames.extend(decoder.decode(av.Packet(data)))
        frames.extend(decoder.decode(None))
        assert len(frames) == 6
        assert all((f.width, f.height) == (640, 400) for f in frames)
        assert (0, True) in keyframes and (3, True) in keyframes
    finally:
        encoder.close()


def test_hardware_failure_falls_back_to_real_software_encoder(monkeypatch):
    real = encoding.Encoder
    attempts = []
    def create(name, *args):
        attempts.append(name)
        if name == 'h264_nvenc':
            raise RuntimeError('simulated unavailable GPU')
        return real(name, *args)
    monkeypatch.setattr(encoding, 'Encoder', create)
    encoder = encoding.create_encoder((320, 200), 15, 1000)
    try:
        assert encoder.name == 'libx264' and attempts[0] == 'h264_nvenc'
    finally:
        encoder.close()


@pytest.mark.parametrize('input_format', ['bgra', 'yuv420p'])
def test_nvenc_input_paths_keep_colors_and_buffer_reuse_frame_accurate(input_format):
    import av
    import numpy as np
    try:
        encoder = encoding.Encoder('h264_nvenc', (320, 200), 60, 8000, input_format)
    except Exception:
        pytest.skip('NVENC is unavailable')
    pixels = np.empty((400, 640, 4), dtype=np.uint8)
    decoder = av.CodecContext.create('h264', 'r')
    try:
        for bgr in ((10, 20, 240), (230, 20, 10), (20, 220, 20), (96, 96, 96)):
            pixels[:] = (*bgr, 255)
            output = encoder.encode_bgra(pixels, 640, 400)
            assert len(output) == 1, 'capture memory must be consumed synchronously'
            frames = decoder.decode(av.Packet(output[0][0]))
            assert len(frames) == 1 and frames[0].format.name == 'yuv420p'
            assert (frames[0].width, frames[0].height) == (320, 200)
            actual = frames[0].to_ndarray(format='bgra')[24:-24, 24:-24, :3].mean(axis=(0, 1))
            assert max(abs(actual-np.array(bgr))) < 10, (input_format, bgr, actual)
    finally:
        encoder.close()


def test_nvenc_compatibility_path_is_tried_before_software(monkeypatch):
    real = encoding.Encoder
    calls = []
    def create(name, size, fps, bitrate, input_format=None):
        calls.append((name, input_format))
        if name == 'h264_nvenc' and input_format == 'bgra':
            raise RuntimeError('driver rejects RGB input')
        return real(name, size, fps, bitrate, input_format)
    try:
        probe = real('h264_nvenc', (320, 200), 60, 8000, 'yuv420p')
        probe.close()
    except Exception:
        pytest.skip('NVENC is unavailable')
    monkeypatch.setattr(encoding, 'Encoder', create)
    encoder = encoding.create_encoder((320, 200), 60, 8000)
    try:
        assert encoder.name == 'h264_nvenc' and encoder.input_format == 'yuv420p'
        assert calls[:2] == [('h264_nvenc', 'bgra'), ('h264_nvenc', 'yuv420p')]
    finally:
        encoder.close()
