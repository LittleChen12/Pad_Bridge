# SPDX-License-Identifier: GPL-3.0-or-later
"""H.264 pipeline, decoder-aware scaling, and capture error recovery."""
import logging
import time
import threading
from odx11 import pipeline
from . import x11_capture
from .stream_metrics import FrameTimings, RollingStatistics
from .encoding_profiles import ENCODERS, conversion_fragment, encoder_fragment
log = logging.getLogger('padbridge.encoding')


def select_encoder(allow_cuda=True):
    x11_capture.init_threads()
    pipeline.init()
    Gst = pipeline.Gst
    for name in ENCODERS:
        if name == 'nvcudah264enc' and not allow_cuda:
            continue
        if not Gst.ElementFactory.find(name):
            continue
        probe = None
        try:
            probe = Gst.parse_launch(
                'videotestsrc num-buffers=3 ! video/x-raw,format=BGRx,width=1280,height=720,framerate=60/1 '
                '! ' + conversion_fragment(name) + ' ! ' + encoder_fragment(name, 60) +
                ' ! h264parse ! fakesink sync=false')
            probe.set_state(Gst.State.PLAYING)
            result = probe.get_bus().timed_pop_filtered(
                8 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if result and result.type == Gst.MessageType.EOS:
                log.info('编码器自检通过：%s', name)
                return name
            log.warning('编码器 %s 不可用：%s', name,
                        result.parse_error() if result else '超时')
        except Exception as exc:
            log.warning('编码器 %s 不可用：%s', name, exc)
        finally:
            if probe:
                probe.set_state(Gst.State.NULL)
    raise RuntimeError('没有可工作的 H.264 编码器。')


class NativePipeline(pipeline.Pipeline):
    # Two admitted frames at most, including the one awaiting socket delivery.
    encoder = 'x264enc'
    bitrate_kbps = 24000
    transport = 'usb'

    def __init__(self, *args, output_size=None, **kwargs):
        self.output_size = output_size
        self._stopped = False
        self._capture_failed = False
        self._capture_notice = None
        self.on_ready = None  # Optional session callback, always invoked on the main loop.
        self._ready_notice = None
        self._ready_sent = False
        self._timings = FrameTimings()
        self._statistics = RollingStatistics()
        self._current_timings = {}
        self._send_started = None
        self._slots = threading.BoundedSemaphore(2)
        self._backpressure_drops = 0
        super().__init__(*args, **kwargs)

    def _build(self):
        self._stopped = False
        self._capture_failed = False
        Gst = pipeline.Gst
        geom, video, xname, fps = self._args
        self._capture_guard = x11_capture.install(xname)
        self._capture_generation = self._capture_guard.generation
        x, y, w, h = geom
        fps = fps or video.effective('fps')
        self.target_fps = fps
        self.stream_size = self.output_size or (w, h)
        self.stream_config = {'type': 'streamConfig', 'codec': 'h264',
                              'width': self.stream_size[0], 'height': self.stream_size[1],
                              'framesPerSecond': fps}
        size = self.output_size if self.output_size != (w, h) else None
        desc = (
            f'ximagesrc name=capture display-name="{xname}" startx={x} starty={y} '
            f'endx={x+w-1} endy={y+h-1} use-damage=false show-pointer=false '
            f'! video/x-raw,framerate={fps}/1 '
            '! queue name=q leaky=downstream max-size-buffers=1 max-size-bytes=0 max-size-time=0 '
            '! ' + conversion_fragment(self.encoder, size) + ' ! '
            + encoder_fragment(self.encoder, fps, self.bitrate_kbps, self.transport == 'wifi') +
            ' ! h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au '
            '! queue name=delivery max-size-buffers=1 max-size-bytes=0 max-size-time=0 '
            '! appsink name=out sync=false emit-signals=true max-buffers=1 drop=false')
        # The upstream start() fallback is VAAPI-specific. Selection above probes
        # the complete CUDA path; do not enter that unrelated fallback here.
        self.gpu = False
        log.info('串流：%dx%d @ %d fps，%s，%s 转色，目标码率 %.1f Mbps（采集 %dx%d）',
                 *self.stream_size, fps, self.encoder,
                 'CUDA' if self.encoder == 'nvcudah264enc' else 'CPU', self.bitrate_kbps / 1000, w, h)
        self.pipe = Gst.parse_launch(desc)
        self.sink = self.pipe.get_by_name('out')
        self.sink.connect('new-sample', self._on_sample)
        self._count(self.pipe.get_by_name('q').get_static_pad('sink'), '_captured')
        self.pipe.get_by_name('capture').get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER, self._capture_probe)
        self.pipe.get_by_name('conv').get_static_pad('sink').add_probe(Gst.PadProbeType.BUFFER, self._gate)
        for pad_name, stage in (('sink', 'encoding'), ('src', 'encoded')):
            self.pipe.get_by_name('enc').get_static_pad(pad_name).add_probe(
                Gst.PadProbeType.BUFFER, self._stage_probe, stage)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect('message::error', self._on_bus_error)

    def start(self):
        # The base implementation's conversion log/fallback refers to VAAPI.
        if self.pipe.set_state(pipeline.Gst.State.PLAYING) == pipeline.Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('截图或视频编码管线未能启动。')

    def _on_sample(self, sink):
        previous = self.frames
        try:
            result = super()._on_sample(sink)
        finally:
            self._slots.release()
        if self.frames > previous and self._send_started is not None:
            self._statistics.record(**self._current_timings,
                                    send=(time.monotonic()-self._send_started)*1000)
        if self.frames and not self._ready_sent and not self._stopped:
            from gi.repository import GLib
            self._ready_sent = True
            # The first frame carries the new SPS. Let it reach the receiver
            # before the session resends view-dependent state (not extra IDRs).
            self._ready_notice = GLib.timeout_add(100, self._notify_ready)
        return result

    def _notify_ready(self):
        self._ready_notice = None
        if not self._stopped and self.on_ready:
            self.on_ready()
        return False

    def _gate(self, pad, info):
        # ximagesrc ignores XShmGetImage's return value. Drop the invalid raw
        # frame and ask the existing main-loop recovery to reread RandR geometry.
        if self._capture_guard.generation != self._capture_generation:
            if not self._capture_failed:
                from gi.repository import GLib
                self._capture_failed = True
                self._capture_notice = GLib.idle_add(self._capture_error)
            return pipeline.Gst.PadProbeReturn.DROP
        key = self._running_time(pad, info.get_buffer())
        if not self._slots.acquire(blocking=False):
            self._backpressure_drops += 1
            self._timings.discard(key)
            return pipeline.Gst.PadProbeReturn.DROP
        result = super()._gate(pad, info)
        if result == pipeline.Gst.PadProbeReturn.DROP:
            self._slots.release()
            self._timings.discard(key)
        else:
            self._timings.stage(key, 'admitted')
        return result

    def _running_time(self, pad, buf):
        Gst = pipeline.Gst
        event = pad.get_sticky_event(Gst.EventType.SEGMENT, 0)
        if event is None or buf.pts == Gst.CLOCK_TIME_NONE:
            return None
        value = event.parse_segment().to_running_time(Gst.Format.TIME, buf.pts)
        return None if value == Gst.CLOCK_TIME_NONE else value

    def _capture_probe(self, pad, info):
        key = self._running_time(pad, info.get_buffer())
        clock = self.pipe.get_clock()
        if key is not None and clock is not None:
            elapsed = (clock.get_time()-self.pipe.get_base_time()-key)/pipeline.Gst.MSECOND
            self._timings.capture(key, elapsed)
        return pipeline.Gst.PadProbeReturn.OK

    def _stage_probe(self, pad, info, name):
        self._timings.stage(self._running_time(pad, info.get_buffer()), name)
        return pipeline.Gst.PadProbeReturn.OK

    def statistics(self):
        fps, timings = self._statistics.snapshot()
        return {'actual_fps': fps, 'timings_ms': timings, 'encoder': self.encoder,
                'encoder_input_format': 'NV12',
                'conversion_backend': 'cuda' if self.encoder == 'nvcudah264enc' else 'cpu',
                'capture_backend': 'ximagesrc', 'frames_sent': self.frames,
                'backpressure_drops': self._backpressure_drops, 'max_inflight_frames': 2}

    def _capture_error(self):
        self._capture_notice = None
        if not self._stopped:
            self.on_error('显示区域在截图时发生变化，正在重新读取显示布局。')
        return False

    def stop(self):
        from gi.repository import GLib
        self._stopped = True
        super().stop()
        # stop() joins the sample thread before removing its last queued notice.
        if self._ready_notice:
            GLib.source_remove(self._ready_notice)
            self._ready_notice = None
        if self._capture_notice:
            GLib.source_remove(self._capture_notice)
            self._capture_notice = None

    def _capture_ms(self, buf):
        # NVENC adds a large PTS offset to allow DTS reordering. The segment maps
        # that timestamp back to pipeline running time; raw PTS is not elapsed time.
        Gst = pipeline.Gst
        key = self._running_time(self.sink.get_static_pad('sink'), buf)
        self._current_timings = self._timings.finish(key)
        self._send_started = time.monotonic()
        clock = self.pipe.get_clock()
        event = self.sink.get_static_pad('sink').get_sticky_event(Gst.EventType.SEGMENT, 0)
        if clock is None or event is None or buf.pts == Gst.CLOCK_TIME_NONE:
            return None
        capture = event.parse_segment().to_running_time(Gst.Format.TIME, buf.pts)
        if capture == Gst.CLOCK_TIME_NONE:
            return None
        elapsed = clock.get_time() - self.pipe.get_base_time() - capture
        if elapsed < -100 * Gst.MSECOND or elapsed > 10 * Gst.SECOND:
            return None  # Do not publish misleading telemetry after a clock discontinuity.
        return round(time.time() * 1000 - max(0, elapsed) / Gst.MSECOND)
