# SPDX-License-Identifier: GPL-3.0-or-later
import json
import threading
import time
from unittest.mock import Mock
import pytest
from odx11 import protocol
from padbridge_app.windows import stream_sender as ss


def test_network_backpressure_allows_one_pending_frame_and_preserves_wire_order():
    blocked, release, two_captured = threading.Event(), threading.Event(), threading.Event()
    written, captured, errors = [], [], []
    class Socket:
        def sendall(self, data):
            if not protocol.is_control(data[4:]) and not blocked.is_set():
                blocked.set()
                assert release.wait(3)
            written.append(data)
    sender = ss.StreamSender(Socket(), threading.Event())
    receipts = []
    def produce():
        try:
            sender.send_control(protocol.encode_control({'type': 'streamConfig', 'width': 320, 'height': 200}))
            for index in range(3):
                with sender.frame_slot() as submit:
                    captured.append(index)
                    receipts.append(submit([(b'\0\0\0\1\x65'+bytes([index]), True)], 123, 2, 3))
                    if index == 1:
                        two_captured.set()
        except BaseException as exc:
            errors.append(exc)
    producer = threading.Thread(target=produce)
    producer.start()
    try:
        assert blocked.wait(1) and two_captured.wait(1)
        time.sleep(.06)
        assert captured == [0, 1], 'must wait before capturing a third frame'
        release.set()
        producer.join(2)
        assert not producer.is_alive() and not errors
        assert receipts[-1].sent.wait(2)
        assert protocol.decode_control(written[0][4:])['type'] == 'streamConfig'
        assert [data[-1] for data in written[1:]] == [0, 1, 2], 'H.264 frames may not be discarded'
        for data in written[1:]:
            payload = data[4:]
            prefix = json.loads(payload[:payload.find(b'\0\0\0\1')])
            assert prefix['cap'] == 123 and prefix['snd'] > 123
        _, timings = sender.statistics()
        assert timings['capture'] == 2 and timings['encode'] == 3
        assert timings['send_queue'] > 0
    finally:
        release.set()
        producer.join(2)
        sender.close()


def test_failed_writer_is_reported_to_capture_and_control_paths():
    sock = Mock()
    sock.sendall.side_effect = OSError('receiver disconnected')
    sender = ss.StreamSender(sock, threading.Event())
    try:
        sender.send_control(protocol.welcome())
        sender.thread.join(1)
        with pytest.raises(ConnectionError, match='receiver disconnected'):
            with sender.frame_slot():
                pass
        with pytest.raises(ConnectionError, match='receiver disconnected'):
            sender.send_control(protocol.ping())
    finally:
        sender.close()


def test_statistics_exclude_setup_and_recover_after_stall(monkeypatch):
    sender = ss.StreamSender(Mock(), threading.Event())
    try:
        with sender.lock:
            sender.sent_at.extend(100+n/60 for n in range(120))
        monkeypatch.setattr(ss.time, 'monotonic', lambda: 102)
        assert 59 <= sender.statistics()[0] <= 60
        monkeypatch.setattr(ss.time, 'monotonic', lambda: 110)
        assert sender.statistics()[0] == 0
        with sender.lock:
            sender.sent_at.extend(110+n/60 for n in range(120))
        monkeypatch.setattr(ss.time, 'monotonic', lambda: 112)
        assert 59 <= sender.statistics()[0] <= 60
    finally:
        sender.close()


def test_statistics_expose_long_frames_hidden_by_average(monkeypatch):
    sender = ss.StreamSender(Mock(), threading.Event())
    try:
        with sender.lock:
            sender.sent_at.extend([100+n/60 for n in range(11)]+[100.25])
            sender.timings.extend([(1, 4, .1, .2)]*19+[(12, 35, 50, 10)]*2)
        monkeypatch.setattr(ss.time, 'monotonic', lambda: 100.25)
        _, timings = sender.statistics()
        assert timings['encode'] < 7
        assert timings['encode_p95'] == 35
        assert timings['send_p95'] == 50
        assert timings['frame_interval_max'] == 83.33
        sender.reset_statistics()
        assert sender.statistics() == (0.0, {})
    finally:
        sender.close()
