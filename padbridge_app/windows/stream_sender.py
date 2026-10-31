# SPDX-License-Identifier: GPL-3.0-or-later
"""Ordered TCP writer with at most one frame behind the frame being sent."""
from collections import deque
from contextlib import contextmanager
import queue
import math
import threading
import time

from odx11 import protocol


class FrameReceipt:
    def __init__(self):
        self.sent = threading.Event()
        self.sent_at = None


class StreamSender:
    def __init__(self, sock, stopped):
        self.sock, self.stopped = sock, stopped
        self.closed = threading.Event()
        self.error = None
        self.items = queue.Queue(maxsize=8)
        # The reservation includes capture/encode, queued video, and sendall.
        # It is taken BEFORE capture, so backpressure never collects old pixels.
        self.slots = threading.BoundedSemaphore(2)
        self.lock = threading.Lock()
        self.sent_at = deque(maxlen=240)
        self.timings = deque(maxlen=120)
        self.thread = threading.Thread(target=self._run, name='padbridge-sender', daemon=True)
        self.thread.start()

    def check(self):
        if self.error is not None:
            raise ConnectionError(str(self.error)) from self.error
        if self.closed.is_set() or self.stopped.is_set():
            raise ConnectionError('串流已停止。')

    def _put(self, item):
        while True:
            self.check()
            try:
                self.items.put(item, timeout=0.05)
                return
            except queue.Full:
                pass

    def send_control(self, data):
        self._put((data, None))

    @contextmanager
    def frame_slot(self):
        while True:
            self.check()
            if self.slots.acquire(timeout=0.05):
                break
        submitted = False

        def submit(encoded, captured, capture_ms, encode_ms):
            nonlocal submitted
            if submitted:
                raise RuntimeError('帧已提交。')
            if not encoded:
                return None
            receipt = FrameReceipt()
            self._put((encoded, (captured, capture_ms, encode_ms, time.monotonic(), receipt)))
            submitted = True
            return receipt

        try:
            yield submit
        finally:
            if not submitted:
                self.slots.release()

    def _run(self):
        try:
            while not self.closed.is_set() and not self.stopped.is_set():
                try:
                    data, video = self.items.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    if video is None:
                        self.sock.sendall(data)
                        continue
                    captured, capture_ms, encode_ms, queued_at, receipt = video
                    began = time.monotonic()
                    try:
                        for au, _ in data:
                            # Timestamp at actual write, including any queue wait.
                            self.sock.sendall(protocol.encode_video(au, captured, round(time.time()*1000)))
                        ended = time.monotonic()
                        with self.lock:
                            self.sent_at.append(ended)
                            self.timings.append((capture_ms, encode_ms, (ended-began)*1000, (began-queued_at)*1000))
                        receipt.sent_at = ended
                        receipt.sent.set()
                    finally:
                        self.slots.release()
                finally:
                    self.items.task_done()
        except BaseException as exc:
            self.error = exc

    def statistics(self):
        now = time.monotonic()
        with self.lock:
            while self.sent_at and self.sent_at[0] < now-2:
                self.sent_at.popleft()
            times, timings = tuple(self.sent_at), tuple(self.timings)
        fps = round((len(times)-1)/max(0.001, now-times[0]), 1) if len(times) > 1 else 0.0
        average = {name: round(sum(t[i] for t in timings)/len(timings), 2)
                   for i, name in enumerate(('capture', 'encode', 'send', 'send_queue'))} if timings else {}
        # Means alone hide an occasional long frame. Keep the tail visible in
        # diagnostics alongside the receiver's independently measured intervals.
        def p95(values):
            values = sorted(values)
            return round(values[math.ceil(len(values)*0.95)-1], 2)
        if timings:
            for i, name in enumerate(('capture', 'encode', 'send', 'send_queue')):
                average[name+'_p95'] = p95(t[i] for t in timings)
        if len(times) > 1:
            intervals = [(b-a)*1000 for a, b in zip(times, times[1:])]
            average['frame_interval_p95'] = p95(intervals)
            average['frame_interval_max'] = round(max(intervals), 2)
        return fps, average

    def reset_statistics(self):
        with self.lock:
            self.sent_at.clear()
            self.timings.clear()

    def close(self):
        # Caller shuts the socket down first, waking any blocked sendall.
        self.closed.set()
        self.thread.join(3)
