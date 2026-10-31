# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows streaming session: bounded I/O, reconnect, and graceful resource cleanup."""
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import queue
import signal
import socket
import threading
import time
import uuid

from odx11 import protocol, usbmux
from .. import network
from ..video import VideoOptions, mirror_size
from . import desktop, encoding, storage, transport, virtual_display
from .input import Injector
from .receiver_layout import LayoutHistory
from .stream_sender import StreamSender

log = logging.getLogger(__name__)


def validate_hello(hello, expected_id=''):
    if not hello or hello.get('type') != 'hello' or not protocol.panel_pixels(hello):
        raise ValueError('目标设备没有返回有效的 OpenDisplay hello。')
    pv = hello.get('pv', 1)
    if type(pv) is not int or not 1 <= pv <= 3:
        raise ValueError('接收端协议版本暂不兼容。')
    if expected_id and hello.get('id') != expected_id:
        raise ValueError('接收端身份发生变化，请断开后重新搜索。')
    return hello


def stream_options(hello, monitor, video):
    limits = protocol.decode_limits(hello)
    for limit in limits:
        if limit is not None and (not math.isfinite(limit) or limit < 1):
            raise ValueError('接收端解码上限无效。')
    rate = hello.get('displayMaxFrameRate', 60)
    if type(rate) is not int or rate < 1:
        rate = 60
    fps = max(1, min(video.fps, rate, int(limits.max_fps or video.fps)))
    return mirror_size(monitor.w, monitor.h, limits, video.size, fps), fps


def stream(sock, stopped, target, video, publish, virtual=None, layout_history=None):
    sock.settimeout(2)
    size = int.from_bytes(network._exact(sock, 4), 'big')
    if not 0 < size < protocol.MAX_INBOUND:
        raise ValueError('OpenDisplay 握手长度无效。')
    hello = validate_hello(protocol.decode_control(network._exact(sock, size)), target.get('receiver_id', ''))
    expected_id = target.get('receiver_id') or hello.get('id', '')
    layout_history = layout_history or LayoutHistory()
    messages = queue.Queue(maxsize=128)
    reader_done = threading.Event()
    read_error = []
    last_received = [time.monotonic()]

    def receive():
        parser = protocol.Deframer()
        try:
            while not reader_done.is_set():
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    raise EOFError('iPad 已断开连接。')
                last_received[0] = time.monotonic()
                for payload in parser.feed(data):
                    message = protocol.decode_control(payload)
                    if message:
                        messages.put_nowait(message)
        except (OSError, EOFError, protocol.ProtocolError, queue.Full) as exc:
            read_error.append(exc)

    reader = threading.Thread(target=receive, name='padbridge-receiver', daemon=True)
    reader.start()
    sender = StreamSender(sock, stopped)
    encoder = capture = injector = None
    source = signature = None
    next_frame = next_check = next_ping = 0.0
    first_frame = None
    refresh_at = None
    reset_at = None
    reset_layout = False
    remember_layout = False
    receiver_stats = {}
    try:
        sender.send_control(protocol.welcome())
        while not stopped.is_set():
            sender.check()
            if read_error:
                raise ConnectionError(str(read_error[0]))
            now = time.monotonic()
            if now-last_received[0] > 15:
                raise TimeoutError('接收端长时间没有响应。')
            for _ in range(128):
                try:
                    message = messages.get_nowait()
                except queue.Empty:
                    break
                kind = message['type']
                if kind == 'hello':
                    hello = validate_hello(message, expected_id)
                    sender.send_control(protocol.welcome())
                    next_check = 0
                elif kind == 'ping':
                    sender.send_control(protocol.pong(message.get('t'), round(time.time()*1000)))
                elif kind == 'kf' and encoder:
                    encoder.force_keyframe = True
                elif kind == 'stats':
                    receiver_stats = {str(k)[:64]: v for k, v in list(message.items())[:32]
                                      if type(v) in (int, float) and math.isfinite(v)}
                elif kind in ('closing', 'sleeping'):
                    raise ConnectionError('OpenDisplay 已关闭或进入休眠。')
                elif kind in ('touch', 'scroll') and injector:
                    try:
                        injector.handle(message)
                    except OSError as exc:
                        log.debug('触控未注入：%s', exc)
            if now >= next_check:
                if virtual:
                    panel = protocol.panel_pixels(hello)
                    current = virtual.attach(video.size or tuple(panel))
                else:
                    current = desktop.choose_monitor(target['display_mode'], target.get('monitor', ''))
                size, fps = stream_options(hello, current, video)
                new_signature = (current, size, fps)
                if new_signature != signature:
                    if injector:
                        injector.release_all()
                    if capture:
                        capture.close()
                        capture = None
                    if encoder:
                        encoder.close()
                    source = current
                    encoder = encoding.create_encoder(size, fps, video.bitrate(target['transport']))
                    capture = desktop.create_capture(source)
                    injector = Injector(source)
                    signature = new_signature
                    sender.send_control(protocol.encode_control({'type': 'streamConfig', 'codec': 'h264',
                                 'width': size[0], 'height': size[1], 'framesPerSecond': fps}))
                    # The capture backend includes the real Windows cursor.
                    sender.send_control(protocol.encode_control({'type': 'cursor', 'v': 0}))
                    sender.reset_statistics()
                    refresh_at = None
                    first_frame = None
                    reset_layout = layout_history.needs_reset(expected_id, size)
                    remember_layout, reset_at = True, None
                    next_frame = time.monotonic()
                actual_fps, timings = sender.statistics()
                publish(state='dialing' if reset_layout else 'streaming',
                        problem='正在同步 iPad 画面比例…' if reset_layout else '',
                        encoder=encoder.name, capture_monitor=source.name,
                        capture_size=[source.w, source.h], stream_size=list(size), target_fps=fps,
                        receiver_panel=list(protocol.panel_pixels(hello)),
                        actual_fps=actual_fps, encoder_input_format=encoder.input_format,
                        capture_backend=capture.backend, receiver_stats=receiver_stats,
                        timings_ms=timings)
                next_check = time.monotonic() + 1
            if now >= next_ping:
                sender.send_control(protocol.ping(capFps=round(sender.statistics()[0])))
                next_ping = now + 2
            if first_frame is not None and first_frame.sent.is_set() and remember_layout:
                layout_history.remember(expected_id, size)
                remember_layout = False
                refresh_at = first_frame.sent_at+0.1
                if reset_layout:
                    reset_at = first_frame.sent_at+0.18
            if refresh_at is not None and now >= refresh_at:
                # Keep the cursor state synchronized after the first new-size
                # frame, matching the Linux sender without moving the pointer.
                sender.send_control(protocol.encode_control({'type': 'cursor', 'v': 0}))
                refresh_at = None
            if reset_at is not None and now >= reset_at:
                # The receiver has consumed the new SPS/IDR, but older iOS views
                # retain their previous fitted rect for the entire connection.
                # Reopen just the video socket once; keep the virtual desktop.
                return True
            if now < next_frame:
                # Event.wait on Windows follows the coarse wait timeout and can
                # round a 3 ms remainder up to a full scheduler tick. Python's
                # sleep uses a high-resolution waitable timer; keep each wait
                # below 5 ms so stop and inbound controls remain responsive.
                time.sleep(min(next_frame-now, 0.005))
                continue
            with sender.frame_slot() as submit:
                captured = round(time.time()*1000)
                capture_started = time.perf_counter()
                pixels = capture.grab()
                encode_started = time.perf_counter()
                encoded = encoder.encode_bgra(pixels, source.w, source.h)
                encoded_at = time.perf_counter()
                receipt = submit(encoded, captured, (encode_started-capture_started)*1000,
                                 (encoded_at-encode_started)*1000)
                if first_frame is None and receipt is not None:
                    first_frame = receipt
            # Do not build a queue of old desktop frames after a slow network send.
            next_frame = max(next_frame + 1/fps, time.monotonic())
    finally:
        reader_done.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sender.close()
        reader.join(3)
        if injector:
            try:
                injector.release_all()
            except OSError:
                pass
        if capture:
            capture.close()
        if encoder:
            encoder.close()


def run(transport_name='usb', address='', display_mode='mirror', video=None,
        monitor='', token=None, receiver_id='', display_position='right'):
    import psutil
    if transport_name not in ('usb', 'wifi'):
        raise ValueError('连接方式必须为 USB 或 Wi-Fi。')
    if display_position not in ('left', 'right'):
        raise ValueError('副屏位置必须为左侧或右侧。')
    video = video or VideoOptions()
    foreground = token is None
    token = token or uuid.uuid4().hex
    proc = psutil.Process()
    target = {'transport': transport_name, 'address': address, 'display_mode': display_mode,
              'monitor': monitor, 'display_position': display_position,
              'receiver_id': receiver_id, 'video_options': video.to_dict()}
    facts = {**target, 'pid': os.getpid(), 'created': proc.create_time(), 'token': token,
             'foreground': foreground, 'command': proc.cmdline(), 'state': 'starting'}
    stopped = threading.Event()
    storage.LOG.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(storage.LOG, maxBytes=2*1024*1024, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    def publish(**changes):
        facts.update(changes, updated=time.time())
        storage.write_json(storage.STATE, facts)

    def watch_stop():
        while not stopped.wait(0.1):
            if storage.read_json(storage.STOP).get('token') == token:
                stopped.set()

    previous_signal = signal.signal(signal.SIGINT, lambda *_: stopped.set())
    virtual = None
    try:
        with storage.Lock('worker.lock'):
            try:
                virtual_display.recover()
                if display_mode == 'extend' and monitor in ('', virtual_display.AUTO):
                    if not virtual_display.available():
                        raise RuntimeError('请先安装扩展组件，再连接 iPad。')
                    virtual = virtual_display.VirtualDisplay(position=display_position)
                else:
                    desktop.choose_monitor(display_mode, monitor)
                endpoint = network.parse_endpoint(address) if transport_name == 'wifi' else None
                layout_history = LayoutHistory()
                publish(state='dialing', problem='正在等待 iPad；请打开 OpenDisplay。')
                watcher = threading.Thread(target=watch_stop, name='padbridge-stop', daemon=True)
                watcher.start()
                while not stopped.is_set():
                    try:
                        if endpoint:
                            sock = socket.create_connection(endpoint, timeout=3)
                        else:
                            devices = transport.list_devices()
                            if not devices:
                                publish(state='idle', problem='请连接 iPad、信任此电脑，并打开 OpenDisplay。')
                                stopped.wait(2)
                                continue
                            if len(devices) > 1:
                                raise RuntimeError('检测到多台 USB 设备，请只保留要连接的一台 iPad。')
                            sock = transport.connect_usb(devices[0]['DeviceID'])
                        network.configure_video_socket(sock)
                        keep_display = False
                        try:
                            with sock:
                                keep_display = stream(sock, stopped, target, video, publish, virtual, layout_history)
                        finally:
                            # A dropped Wi-Fi/USB connection must also withdraw
                            # the monitor while we wait for the next handshake.
                            if virtual and not keep_display:
                                virtual.close()
                        if keep_display:
                            log.info('画面比例变化：保留副屏，重新建立接收端视频会话。')
                            publish(state='dialing', problem='正在同步 iPad 画面比例…')
                            # Let the receiver process disconnect and retire its
                            # old view before accepting the next connection.
                            stopped.wait(0.35)
                    except (OSError, EOFError, RuntimeError, ValueError, protocol.ProtocolError, usbmux.MuxError) as exc:
                        if stopped.is_set():
                            break
                        if virtual:
                            virtual.close()
                        log.info('连接等待重试：%s', exc)
                        publish(state='dialing', problem=str(exc))
                        stopped.wait(2)
                publish(state='off', problem='')
            except BaseException as exc:
                publish(state='problem', problem=str(exc))
                raise
            finally:
                stopped.set()
                if virtual:
                    virtual.close()
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        logging.getLogger().removeHandler(handler)
        handler.close()
