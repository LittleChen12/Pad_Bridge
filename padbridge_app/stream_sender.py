# SPDX-License-Identifier: GPL-3.0-or-later
"""One ordered socket writer; the desktop loop never waits for sendall()."""
from dataclasses import dataclass, field
import queue
import socket
import threading
import time
from odx11 import protocol
from .stream_metrics import RollingStatistics


@dataclass
class Pending:
    data: bytes
    video: bool = False
    capture_ms: int | None = None
    queued: float = field(default_factory=time.monotonic)
    done: threading.Event = field(default_factory=threading.Event)
    error: OSError | None = None


class StreamSender:
    def __init__(self, sock, on_error=lambda error: None, capacity=32):
        self.sock, self.on_error = sock, on_error
        self.pending = queue.Queue(maxsize=capacity)
        self.statistics = RollingStatistics()
        self.lock = threading.Lock()
        self.error = None
        self.closed = False
        self.thread = threading.Thread(target=self._run, name='padbridge-sender', daemon=True)
        self.thread.start()

    def _submit(self, item):
        with self.lock:
            if self.closed or self.error:
                raise self.error or OSError('Sender closed')
            try:
                self.pending.put_nowait(item)
            except queue.Full:
                raise OSError('Receiver is not draining the bounded send queue') from None

    def control(self, data):
        self._submit(Pending(data))

    def video(self, data, capture_ms):
        item = Pending(data, True, capture_ms)
        self._submit(item)
        # This is the GStreamer delivery thread, never the GLib desktop loop.
        # Its frame permit is retained until delivery (or socket failure).
        item.done.wait()
        if item.error:
            raise item.error

    def _fail_pending(self, error):
        while True:
            try:
                item = self.pending.get_nowait()
            except queue.Empty:
                return
            if item is not None:
                item.error = error
                item.done.set()

    def _run(self):
        while True:
            item = self.pending.get()
            if item is None:
                return
            try:
                start = time.monotonic()
                packet = (protocol.encode_video(item.data, item.capture_ms,
                          round(time.time()*1000) if item.capture_ms is not None else None)
                          if item.video else item.data)
                self.sock.sendall(packet)
                if item.video:
                    self.statistics.record(send=(time.monotonic()-start)*1000,
                                           send_queue=(start-item.queued)*1000)
            except Exception as cause:
                error = cause if isinstance(cause, OSError) else OSError(str(cause))
                with self.lock:
                    self.error = item.error = error
                    self._fail_pending(error)
                    report = not self.closed
                if report:
                    self.on_error(error)
                return
            finally:
                item.done.set()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self._fail_pending(OSError('Sender closed'))
            self.pending.put_nowait(None)
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.thread.join(timeout=3)


def connection_factory(*args, **kwargs):
    # Importing the sender for tests or diagnostics does not initialise GTK/Gst.
    from odx11.daemon import Connection, GRACE
    from gi.repository import GLib

    class QueuedConnection(Connection):
        def __init__(self, cfg, sock, *args, **kwargs):
            self.writer = StreamSender(sock, lambda error: GLib.idle_add(self._send_failed, str(error)))
            try:
                super().__init__(cfg, sock, *args, **kwargs)
                self.session.send_video = self.writer.video
            except BaseException:
                self.writer.close()
                raise

        def _send_failed(self, error):
            if not self._closed:
                self.session.end(f'send failed: {error}', GRACE)
            return False

        def _send(self, data):
            self.writer.control(data)

        def statistics(self):
            _, timings = self.writer.statistics.snapshot()
            return {key: value for key, value in timings.items() if key.startswith('send')}

        def close(self):
            self.writer.close()  # Wake all frame receipts before Pipeline.stop() joins them.
            super().close()

    return QueuedConnection(*args, **kwargs)
