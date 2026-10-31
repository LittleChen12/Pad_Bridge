# SPDX-License-Identifier: GPL-3.0-or-later
import socket
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from odx11 import protocol
from padbridge_app.stream_sender import StreamSender
from padbridge_app.stream_metrics import FrameTimings, RollingStatistics
from padbridge_app.encoding_profiles import conversion_fragment, encoder_fragment


class StatisticsTests(unittest.TestCase):
    def test_rolling_fps_expires_during_a_stall_and_filters_invalid_values(self):
        now = [0.0]
        stats = RollingStatistics(clock=lambda: now[0])
        for i in range(121):
            now[0] = i / 60
            stats.record(send=2, invalid=float('nan'))
        fps, values = stats.snapshot()
        self.assertEqual(fps, 60)
        self.assertEqual(values['send_p95'], 2)
        self.assertNotIn('invalid', values)
        now[0] += 1
        self.assertLess(stats.snapshot()[0], 31)
        now[0] += 2
        self.assertEqual(stats.snapshot(), (0, {}))

    def test_pts_matches_stages_and_dropped_frames_are_bounded(self):
        now = [0]
        trace = FrameTimings(capacity=2, clock=lambda: now[0])
        for key in (1, 2, 3):
            trace.capture(key, 2)
        self.assertEqual(trace.finish(1), {})
        for stage, at in (('admitted', .001), ('encoding', .004), ('encoded', .009)):
            now[0] = at
            trace.stage(2, stage)
        values = trace.finish(2)
        for key, expected in (('capture',2),('capture_queue',1),('convert',3),('encode',5)):
            self.assertAlmostEqual(values[key], expected)
        self.assertEqual(trace.finish(2), {})
        trace.discard(3)
        self.assertEqual(trace.frames, {})


class BlockingSocket:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.sent = []
        self.closed = False

    def sendall(self, data):
        self.entered.set()
        if not self.release.wait(2):
            raise TimeoutError('test send timed out')
        if self.closed:
            raise OSError('closed')
        self.sent.append(data)

    def shutdown(self, *_):
        self.closed = True
        self.release.set()


class SenderTests(unittest.TestCase):
    def test_controls_are_nonblocking_and_video_is_ordered_with_real_send_timestamp(self):
        sock = BlockingSocket()
        sender = StreamSender(sock)
        errors = []
        try:
            sender.control(b'configuration')
            self.assertTrue(sock.entered.wait(1))
            def video():
                try:
                    sender.video(b'\x00\x00\x00\x01\x65encoded-frame', 123)
                except OSError as error:
                    errors.append(error)
            thread = threading.Thread(target=video)
            thread.start()
            with patch('padbridge_app.stream_sender.protocol.encode_video', wraps=protocol.encode_video) as encode:
                sock.release.set()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertFalse(errors)
                self.assertEqual(sock.sent[0], b'configuration')
                self.assertEqual(encode.call_args.args[:2], (b'\x00\x00\x00\x01\x65encoded-frame',123))
                self.assertIsInstance(encode.call_args.args[2], int)
            self.assertEqual(len(sock.sent), 2)
            self.assertIn('send_queue', sender.statistics.snapshot()[1])
        finally:
            sender.close()

    def test_queue_is_bounded_and_close_unblocks_pending_video(self):
        sock = BlockingSocket()
        sender = StreamSender(sock, capacity=1)
        errors, submitted = [], threading.Event()
        try:
            sender.control(b'blocked')
            self.assertTrue(sock.entered.wait(1))
            original = sender._submit
            def submit(item):
                original(item)
                submitted.set()
            sender._submit = submit
            def video():
                try:
                    sender.video(b'frame', None)
                except OSError as error:
                    errors.append(error)
            thread = threading.Thread(target=video)
            thread.start()
            self.assertTrue(submitted.wait(1))
            with self.assertRaises(OSError):
                sender.control(b'overflow')
            sender.close()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertFalse(sender.thread.is_alive())
            self.assertEqual(len(errors), 1)
        finally:
            sender.close()

    def test_real_socket_shutdown_releases_sendall_and_reports_no_spurious_close_error(self):
        writer, reader = socket.socketpair()
        writer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        on_error = Mock()
        sender = StreamSender(writer, on_error)
        sender.control(b'x' * 1000000)
        self.assertTrue(reader.recv(1))
        sender.close()
        writer.close()
        reader.close()
        self.assertFalse(sender.thread.is_alive())
        on_error.assert_not_called()

    def test_packet_error_is_delivered_to_waiter_and_future_submissions(self):
        sock = BlockingSocket()
        failed = threading.Event()
        sender = StreamSender(sock, lambda error: failed.set())
        try:
            with self.assertRaises(OSError):
                sender.video(b'invalid-annexb', 123)
            self.assertTrue(failed.wait(1))
            with self.assertRaises(OSError):
                sender.control(b'later')
        finally:
            sender.close()


class EncodingProfileTests(unittest.TestCase):
    def test_failed_cuda_probe_falls_back_and_stops_both_probes(self):
        from padbridge_app import encoding
        bad, good = Mock(), Mock()
        bad.get_bus.return_value.timed_pop_filtered.return_value = SimpleNamespace(type=1, parse_error=lambda:'CUDA unavailable')
        good.get_bus.return_value.timed_pop_filtered.return_value = SimpleNamespace(type=2)
        gst = SimpleNamespace(ElementFactory=Mock(), parse_launch=Mock(side_effect=[bad,good]),
                              State=SimpleNamespace(PLAYING='playing',NULL='null'), SECOND=1,
                              MessageType=SimpleNamespace(ERROR=1,EOS=2))
        with patch.object(encoding.pipeline,'Gst',gst), patch.object(encoding.pipeline,'init'), \
                patch.object(encoding.x11_capture,'init_threads'):
            self.assertEqual(encoding.select_encoder(), 'nvh264enc')
        for probe in (bad,good):
            self.assertEqual(probe.set_state.call_args.args, ('null',))
        self.assertIn('cudaupload', gst.parse_launch.call_args_list[0].args[0])
        self.assertNotIn('cudaupload', gst.parse_launch.call_args_list[1].args[0])

    def test_gpu_path_keeps_nv12_in_device_memory_including_scaling(self):
        gpu = conversion_fragment('nvcudah264enc', (1920,1200))
        self.assertIn('cudaupload', gpu)
        self.assertIn('cudaconvertscale', gpu)
        self.assertIn('memory:CUDAMemory', gpu)
        self.assertNotIn('videoconvert', gpu)
        self.assertIn('videoscale', conversion_fragment('x264enc', (1920,1200)))

    def test_native_plugins_use_their_actual_parameter_names_and_four_frame_vbv(self):
        cuda = encoder_fragment('nvcudah264enc', 60, 24000)
        self.assertIn('rate-control=cbr', cuda)
        self.assertIn('vbv-buffer-size=1600', cuda)
        legacy = encoder_fragment('nvh264enc', 30, 10000, True)
        self.assertIn('rc-mode=cbr', legacy)
        self.assertIn('vbv-buffer-size=1334', legacy)
        self.assertIn('gop-size=300', legacy)
        self.assertNotIn('intra-refresh', cuda)  # Not available in Ubuntu's 1.24 plugin.
