# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit desktop test: mirror -> native extension, without moving windows twice."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'vendor/opendisplay-x11')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path)
    args = parser.parse_args()
    import av
    from odx11 import protocol
    with tempfile.TemporaryDirectory(prefix='padbridge-modes-') as directory:
        os.environ['APPDATA'] = os.environ['LOCALAPPDATA'] = directory
        from padbridge_app.video import VideoOptions
        from padbridge_app.windows import desktop, service, display_config, device_control
        assert device_control.owned_device().disabled, 'test requires an idle virtual display'
        original = desktop.monitors()
        records, errors = [], []
        done = threading.Event()
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(4)
        listener.settimeout(1)
        address = '127.0.0.1:' + str(listener.getsockname()[1])
        hello = {'type': 'hello', 'pv': 3, 'id': 'mode-switch-smoke',
                 'pixelsWide': 2224, 'pixelsHigh': 1668, 'displayMaxFrameRate': 30}

        def exact(peer, size):
            data = bytearray()
            while len(data) < size:
                chunk = peer.recv(size-len(data))
                if not chunk:
                    raise EOFError()
                data.extend(chunk)
            return bytes(data)

        def serve():
            previous_size = None
            while not done.is_set():
                try:
                    peer, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                record = None
                try:
                    with peer:
                        peer.settimeout(5)
                        peer.sendall(protocol.encode_control(hello))
                        decoder = av.CodecContext.create('h264', 'r')
                        while not done.is_set():
                            length = int.from_bytes(exact(peer, 4), 'big')
                            assert 0 < length < 16*1024*1024
                            payload = exact(peer, length)
                            if protocol.is_control(payload):
                                if protocol.decode_control(payload)['type'] == 'ping':
                                    peer.sendall(protocol.pong(1, 1))
                                continue
                            start = payload.find(b'\0\0\0\1')
                            for frame in decoder.decode(av.Packet(payload[start:])):
                                size = (frame.width, frame.height)
                                if record is None:
                                    # Legacy receiver fits the view using the
                                    # last session's raster, until next connect.
                                    record = {'size': size, 'view_size': previous_size or size,
                                              'frames': 0, 'screens': [m.name for m in desktop.monitors()]}
                                    records.append(record)
                                previous_size = size
                                record['frames'] += 1
                except (EOFError, ConnectionResetError, BrokenPipeError):
                    pass
                except BaseException as exc:
                    errors.append(exc)
                    done.set()

        def command(*arguments):
            result = subprocess.run([str(args.executable.resolve()), *arguments], capture_output=True,
                                    timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))

        def start(mode):
            if args.executable:
                command('start', '--transport', 'wifi', '--address', address, '--display-mode', mode,
                        '--monitor', 'auto', '--resolution', 'native', '--fps', '30', '--bitrate', '8')
            else:
                service.start('wifi', address, mode, VideoOptions('native', 30, 8), monitor='auto')

        def stop():
            command('stop') if args.executable else service.stop()

        def wait_for(predicate):
            deadline = time.monotonic()+25
            while not predicate():
                if errors:
                    raise errors[0]
                if time.monotonic() > deadline:
                    raise AssertionError(f'mode switch timed out: {records}')
                time.sleep(0.05)

        receiver = threading.Thread(target=serve, daemon=True)
        receiver.start()
        try:
            start('mirror')
            wait_for(lambda: records and records[-1]['frames'] >= 12)
            stop()
            start('extend')
            wait_for(lambda: len(records) >= 3 and records[-1]['frames'] >= 18)
            # One mirror socket, one short priming socket, one stable extension.
            assert len(records) == 3, 'layout synchronization must not loop'
            assert records[1]['size'] == records[2]['size'] == (2224, 1668)
            assert records[2]['view_size'] == (2224, 1668)
            assert records[1]['screens'] == records[2]['screens'], 'virtual display was recreated during synchronization'
            assert service.current_status()['state'] == 'streaming'
        finally:
            stop()
            done.set()
            listener.close()
            receiver.join(3)
        assert not errors, errors
        assert display_config.current(optional=True) is None
        assert desktop.monitors() == original
        print(json.dumps({'result': 'PASS', 'packaged': bool(args.executable), 'sessions': records,
                          'layout_restored': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
