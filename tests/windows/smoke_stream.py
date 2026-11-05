# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit real-desktop smoke: capture/encode locally; never save screen pixels.

Uses an isolated APPDATA/LOCALAPPDATA and a loopback OpenDisplay receiver. Checks
decode, renegotiation, keyframes, reconnection and background-worker termination.
"""
import json
import argparse
import os
from pathlib import Path
import socket
import sys
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor/opendisplay-x11')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, help='Also exercise the packaged controller and worker')
    parser.add_argument('--virtual', action='store_true', help='Explicitly test the installed automatic virtual screen')
    parser.add_argument('--require-graphics', action='store_true',
                        help='Require Windows Graphics Capture before and after reconnect')
    parser.add_argument('--display-position', choices=('left', 'right'), default='right',
                        help='Check the default side of an automatically created virtual screen')
    parser.add_argument('--fps', type=int, default=30, choices=(30, 60, 90, 120))
    parser.add_argument('--force-fps', action='store_true')
    parser.add_argument('--receiver-fps', type=int, help='Receiver-advertised ceiling; defaults to requested FPS')
    parser.add_argument('--seconds', type=float, default=0,
                        help='Minimum duration of each connection, for throughput measurements')
    args = parser.parse_args()
    import av
    from odx11 import protocol
    with tempfile.TemporaryDirectory(prefix='padbridge-smoke-') as directory:
        os.environ['LOCALAPPDATA'] = os.environ['APPDATA'] = directory
        from padbridge_app.video import VideoOptions
        from padbridge_app.windows import desktop, service, storage, display_config, device_control
        mode = 'extend' if args.virtual else 'mirror'
        resolution = 'native' if args.virtual else '640x400'
        def command(*values):
            result = subprocess.run([str(args.executable.resolve()), *values], capture_output=True,
                                    text=True, encoding='utf-8', timeout=40,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError(result.stderr or result.stdout)
            return result.stdout
        def start(address):
            if args.executable:
                command('start', '--transport', 'wifi', '--address', address, '--display-mode', mode,
                        '--monitor', 'auto', '--resolution', resolution, '--fps', str(args.fps), '--bitrate', '3',
                        '--display-position', args.display_position, *(['--force-fps'] if args.force_fps else []))
                return json.loads(command('status'))
            return service.start('wifi', address, mode, VideoOptions(resolution, args.fps, 3, args.force_fps), monitor='auto',
                                 display_position=args.display_position)
        original = desktop.monitors()
        if args.virtual:
            assert device_control.ready() and device_control.owned_device().disabled
            assert display_config.current(optional=True) is None, 'virtual smoke requires an idle driver'
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(4)
        server.settimeout(15)
        endpoint = server.getsockname()
        hello = {'type': 'hello', 'pv': 3, 'id': 'loopback-smoke', 'device': 'Test receiver',
                 'pixelsWide': 2224, 'pixelsHigh': 1668, 'displayMaxFrameRate': args.receiver_fps or args.fps,
                 'videoCaps': [{'codec': 'h264', 'maxFrameRate': args.receiver_fps or args.fps}]}
        complete = threading.Event()
        errors, decoded_sizes, controls, counts = [], set(), set(), []
        withdrawn = []
        layout_refreshes = []
        capture_backends = []
        positions = []
        measurements = []

        def exact(peer, length):
            data = bytearray()
            while len(data) < length:
                block = peer.recv(length-len(data))
                if not block:
                    raise EOFError('worker disconnected')
                data.extend(block)
            return bytes(data)

        def serve():
            try:
                # The controller's read-only probe must send no takeover bytes.
                with server.accept()[0] as peer:
                    peer.settimeout(5)
                    peer.sendall(protocol.encode_control(hello))
                    assert peer.recv(1) == b''
                for connection in range(2):
                    with server.accept()[0] as peer:
                        peer.settimeout(10)
                        peer.sendall(protocol.encode_control(hello))
                        decoder = av.CodecContext.create('h264', 'r')
                        frame_count = idrs = 0
                        announced = None
                        video_seen = False
                        refreshed = False
                        renegotiated = False
                        began = time.monotonic()
                        deadline = began + max(18, args.seconds + 10)
                        while time.monotonic() < deadline:
                            size = int.from_bytes(exact(peer, 4), 'big')
                            assert 0 < size < 16*1024*1024
                            payload = exact(peer, size)
                            if protocol.is_control(payload):
                                msg = protocol.decode_control(payload)
                                controls.add(msg['type'])
                                if msg['type'] == 'cursor' and video_seen and not refreshed:
                                    assert msg['v'] == 0, 'native cursor must not be drawn twice'
                                    layout_refreshes.append(announced)
                                    refreshed = True
                                if msg['type'] == 'ping':
                                    peer.sendall(protocol.pong(1, 1))
                                elif msg['type'] == 'streamConfig':
                                    assert msg['framesPerSecond'] == args.fps
                                    announced = (msg['width'], msg['height'])
                                    video_seen = refreshed = False
                            else:
                                assert announced is not None, 'video arrived before streamConfig'
                                video_seen = True
                                start = payload.find(b'\0\0\0\1')
                                assert start >= 0
                                for frame in decoder.decode(av.Packet(payload[start:])):
                                    assert (frame.width, frame.height) == announced
                                    decoded_sizes.add(announced)
                                    frame_count += 1
                                    idrs += bool(frame.key_frame)
                                if frame_count == 5:
                                    peer.sendall(protocol.encode_control({'type': 'kf'}))
                                if connection == 0 and frame_count >= 12 and refreshed and not renegotiated:
                                    renegotiated = True
                                    peer.sendall(protocol.encode_control({**hello, 'maxEncodeWide': 320, 'maxEncodeHigh': 200}))
                                if frame_count >= 26 and idrs >= 2 and time.monotonic()-began >= args.seconds:
                                    state = service.current_status()
                                    backend = state.get('capture_backend')
                                    capture_backends.append(backend)
                                    if args.require_graphics:
                                        assert backend == 'windows-graphics-capture', backend
                                    if args.virtual:
                                        assert state.get('display_position') == args.display_position
                                        screens = desktop.monitors()
                                        captured = next(m for m in screens if m.name == state['capture_monitor'])
                                        assert desktop.refresh_rate(captured.name) >= args.fps
                                        assert [m for m in screens if m.name != captured.name] == original
                                        main = next(m for m in original if m.primary)
                                        assert captured.y == main.y
                                        neighbors = [m for m in original if m.y < captured.y+captured.h
                                                     and m.y+m.h > captured.y]
                                        if args.display_position == 'left':
                                            assert captured.x+captured.w == min(m.x for m in neighbors)
                                        else:
                                            assert captured.x == max(m.x+m.w for m in neighbors)
                                        positions.append([captured.x, captured.y])
                                    counts.append(frame_count)
                                    measurements.append({key: state.get(key) for key in
                                                         ('target_fps', 'actual_fps', 'display_refresh_hz', 'timings_ms')})
                                    break
                        else:
                            raise AssertionError('Timed out waiting for decodable video/keyframes')
                    if args.virtual:
                        deadline = time.monotonic()+10
                        while display_config.current(optional=True) is not None and time.monotonic() < deadline:
                            time.sleep(0.05)
                        assert display_config.current(optional=True) is None, 'dropped connection left a ghost display'
                        assert desktop.monitors() == original, 'physical display layout changed'
                        withdrawn.append(True)
                complete.set()
            except BaseException as exc:
                errors.append(exc)
                complete.set()
            finally:
                server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            address = f'{endpoint[0]}:{endpoint[1]}'
            facts = start(address)
            assert service.active()
            same = start(address)
            assert same['pid'] == facts['pid'], 'duplicate start created a second worker'
            assert complete.wait(max(45, 2*args.seconds+30)), 'receiver did not finish'
            if errors:
                raise errors[0]
        finally:
            if errors:
                print(json.dumps({'failed_status': service.current_status()}, ensure_ascii=False))
                if storage.LOG.exists():
                    print(storage.LOG.read_text(encoding='utf-8')[-6000:])
            if args.executable:
                command('stop')
            else:
                service.stop()
            thread.join(3)
        assert not service.active()
        assert service.current_status()['state'] == 'off'
        assert desktop.monitors() == original, 'capture modified the display layout'
        if args.virtual:
            assert display_config.current(optional=True) is None and device_control.owned_device().disabled
            assert len(withdrawn) == 2 and (2224, 1668) in decoded_sizes
        assert len(decoded_sizes) >= 2 and len(counts) == 2
        assert {'welcome', 'streamConfig', 'ping'} <= controls
        assert len(layout_refreshes) >= 3, 'new geometry must be refreshed after its first video frame'
        # A stale state file may not make the stopped PID active again.
        storage.write_json(storage.STATE, facts)
        assert not service.active()
        print(json.dumps({'result': 'PASS', 'connections': len(counts), 'decoded_frames': sum(counts),
                          'decoded_sizes': sorted(decoded_sizes), 'layout_unchanged': True,
                          'worker_stopped': True, 'packaged': bool(args.executable),
                          'capture_backends': capture_backends,
                          'measurements': measurements,
                          'display_position': args.display_position, 'positions': positions,
                          'virtual_monitor_withdrawals': len(withdrawn)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
