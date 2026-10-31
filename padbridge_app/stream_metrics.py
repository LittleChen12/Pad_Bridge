# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, thread-safe measurements of completed frames and pipeline stages."""
from collections import OrderedDict, deque
import math
import threading
import time


class RollingStatistics:
    def __init__(self, clock=time.monotonic, window=2.0):
        self.clock, self.window = clock, window
        self.samples = deque(maxlen=512)
        self.lock = threading.Lock()

    def record(self, **timings):
        values = {key: float(value) for key, value in timings.items()
                  if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0}
        with self.lock:
            self.samples.append((self.clock(), values))

    def snapshot(self):
        now = self.clock()
        with self.lock:
            while self.samples and self.samples[0][0] < now - self.window:
                self.samples.popleft()
            samples = tuple(self.samples)
        times = [at for at, _ in samples]
        fps = (len(times) - 1) / max(.001, now - times[0]) if len(times) > 1 else 0.0
        result = {}
        def percentile(values):
            ordered = sorted(values)
            return round(ordered[math.ceil(len(ordered) * .95) - 1], 2)
        for key in {key for _, values in samples for key in values}:
            values = [values[key] for _, values in samples if key in values]
            result[key] = round(sum(values) / len(values), 2)
            result[key + '_p95'] = percentile(values)
        if len(times) > 1:
            intervals = [(b-a)*1000 for a, b in zip(times, times[1:])]
            result['frame_interval_p95'] = percentile(intervals)
            result['frame_interval_max'] = round(max(intervals), 2)
        return round(fps, 1), result


class FrameTimings:
    """Match stages by normalized GStreamer PTS; dropped raw frames cannot leak state."""
    def __init__(self, capacity=128, clock=time.monotonic):
        self.capacity, self.clock = capacity, clock
        self.frames = OrderedDict()
        self.lock = threading.Lock()

    def capture(self, key, elapsed_ms):
        with self.lock:
            self.frames[key] = {'captured': self.clock(), 'capture': max(0, elapsed_ms)}
            while len(self.frames) > self.capacity:
                self.frames.popitem(last=False)

    def stage(self, key, name):
        with self.lock:
            if key in self.frames:
                self.frames[key][name] = self.clock()

    def discard(self, key):
        with self.lock:
            self.frames.pop(key, None)

    def finish(self, key):
        with self.lock:
            frame = self.frames.pop(key, {})
        result = {key: frame[key] for key in ('capture',) if key in frame}
        for name, begin, end in (('capture_queue','captured','admitted'),
                                 ('convert','admitted','encoding'),
                                 ('encode','encoding','encoded')):
            if begin in frame and end in frame:
                result[name] = max(0, (frame[end]-frame[begin])*1000)
        return result
