# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line and desktop entry point."""
import argparse
import json
import logging
import os
import sys
from odx11 import state
from . import network, displays
from .service import start, stop, current_status, doctor, authorize
from .preferences import preferences
from .video import VideoOptions
log = logging.getLogger('padbridge')


def gui():
    from .ui.application import run
    return run()


def main():
    parser = argparse.ArgumentParser(description='PadBridge · iPad USB / Wi-Fi 扩展与镜像')
    parser.add_argument('command', nargs='?', default='ui',
                        choices=('ui', 'start', 'stop', 'status', 'doctor', 'discover', 'authorize', 'run', 'release', 'encoder-test'))
    parser.add_argument('--transport', choices=('usb', 'wifi'), help='USB 数据线或局域网 Wi-Fi')
    parser.add_argument('--address', help='iPad 局域网 IP[:端口]；Wi-Fi 模式可留空自动搜索')
    parser.add_argument('--display-mode', choices=('extend', 'mirror'), help='扩展屏幕或镜像主屏')
    parser.add_argument('--resolution', help='native 或横屏宽x高；镜像时作为等比缩放上限')
    parser.add_argument('--fps', type=int, help='目标帧率，15～60')
    parser.add_argument('--bitrate', type=int, help='目标码率 Mbps，1～50；0 为 USB 24 / Wi-Fi 10')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    if args.command == 'ui':
        return gui()
    video = None
    if args.command in ('start', 'run'):
        data = preferences()['video_options'] if args.command == 'start' else VideoOptions().to_dict()
        for key, value in (('resolution', args.resolution), ('fps', args.fps), ('bitrate_mbps', args.bitrate)):
            if value is not None:
                data[key] = value
        video = VideoOptions.from_dict(data)
    if args.command == 'start':
        start(args.transport, args.address, args.display_mode, video)
    elif args.command == 'stop':
        stop()
    elif args.command == 'status':
        print(json.dumps(current_status(), ensure_ascii=False, indent=2))
    elif args.command == 'doctor':
        print(json.dumps(doctor(), ensure_ascii=False, indent=2))
    elif args.command == 'discover':
        print(json.dumps([r.to_dict() for r in network.discover()], ensure_ascii=False, indent=2))
    elif args.command == 'authorize':
        print(authorize().name)
    elif args.command == 'run':
        from . import worker
        worker.run(args.transport or 'usb', args.address or '', args.display_mode or 'extend', video)
    elif args.command == 'release':
        displays.release()
    elif args.command == 'encoder-test':
        from . import encoding
        print(encoding.select_encoder())
    return 0


def entrypoint():
    try:
        return main()
    except Exception as exc:
        if len(sys.argv) > 1 and sys.argv[1] == 'run':
            state.StateFile().write({'state': state.PROBLEM, 'problem': str(exc), 'pid': os.getpid()})
        log.exception('%s', exc)
        return 1
