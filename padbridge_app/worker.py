# SPDX-License-Identifier: GPL-3.0-or-later
"""The streaming worker; started only when the user connects."""
import atexit
import fcntl
import json
import logging
import os
from odx11 import config, daemon, input as odinput
from . import network
from .displays import release, choose_connector, HybridDisplay, MirrorDisplay
from .encoding import NativePipeline, select_encoder
from .paths import RUNTIME, CONFIG, CONNECTION
from .preferences import DISPLAY_POSITIONS
from .video import VideoOptions
from .stream_sender import connection_factory
log = logging.getLogger('padbridge.worker')


def run(transport='usb', address='', display_mode='extend', video=None, display_position='right'):
    if transport not in ('usb', 'wifi'):
        raise ValueError('连接方式必须为 USB 或 Wi-Fi。')
    if display_mode not in ('extend', 'mirror'):
        raise ValueError('显示模式必须为扩展或镜像。')
    video = video or VideoOptions()
    if display_position not in DISPLAY_POSITIONS:
        raise ValueError('副屏位置必须为左侧、右侧或下方。')
    tcp = network.parse_endpoint(address) if transport == 'wifi' else None
    if os.environ.get('XDG_SESSION_TYPE', 'x11') != 'x11':
        raise RuntimeError('当前版本需要 Ubuntu on Xorg 会话。')
    RUNTIME.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = (RUNTIME / 'worker.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('副屏程序已经在运行。') from None
    release()
    cfg = config.load(str(CONFIG))
    cfg.video.preset = 'custom'
    cfg.video.fps = video.fps
    if display_mode == 'extend':
        connector = choose_connector()
        if not os.access(connector / 'status', os.W_OK):
            raise PermissionError('需要先完成系统的显示接口授权。')
        cfg.display.connector = connector.name.split('-', 1)[1]
    if tcp:
        network.probe(tcp)
    NativePipeline.bitrate_kbps = video.bitrate(transport)
    NativePipeline.transport = transport
    NativePipeline.encoder = select_encoder(allow_cuda=cfg.video.convert != 'cpu')
    CONNECTION.write_text(json.dumps({'pid': os.getpid(), 'transport': transport,
                                      'display_mode': display_mode,
                                      'display_position': display_position,
                                      'video_options': video.to_dict(),
                                      'address': network.format_endpoint(*tcp) if tcp else '',
                                      'bitrate_mbps': NativePipeline.bitrate_kbps / 1000}))
    screen = (MirrorDisplay(cfg.display, video.size) if display_mode == 'mirror'
              else HybridDisplay(cfg.display, connector, video.size, display_position))
    atexit.register(screen.teardown)
    try:
        injector = odinput.Injector(cfg.input)
        def make_pipeline(geom, on_au, on_error, fps=None):
            size = screen.stream_size(geom, fps) if display_mode == 'mirror' else None
            return NativePipeline(geom, cfg.video, daemon.display_name(), on_au, on_error, fps,
                                  output_size=size)
        log.info('连接方式：%s%s', transport, f' {network.format_endpoint(*tcp)}' if tcp else '')
        # GUI controls are a per-run snapshot. Restart explicitly to apply changes.
        daemon.run(cfg, screen, injector, make_pipeline, tcp=tcp,
                   prepare_socket=network.configure_video_socket if tcp else None,
                   statistics_interval=1, connection_factory=connection_factory)
    finally:
        screen.teardown()
        CONNECTION.unlink(missing_ok=True)
        lock.close()
