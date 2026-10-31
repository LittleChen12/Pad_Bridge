# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line and desktop entry point."""
import argparse
import json
import logging
import os
import sys
from . import network
from .paths import WINDOWS
from .preferences import preferences
from .video import VideoOptions
log = logging.getLogger('padbridge')


def gui():
    if WINDOWS:
        from .windows.ui import run
    else:
        from .ui.application import run
    return run()


def main():
    if WINDOWS:
        from .windows import service
    else:
        from . import service
    parser = argparse.ArgumentParser(description='PadBridge · iPad USB / Wi-Fi 扩展与镜像')
    parser.add_argument('command', nargs='?', default='ui',
                        choices=('ui', 'start', 'stop', 'status', 'doctor', 'discover', 'authorize', 'run', 'release', 'encoder-test', 'monitors', 'install-display-driver'))
    parser.add_argument('--transport', choices=('usb', 'wifi'), help='USB 数据线或局域网 Wi-Fi')
    parser.add_argument('--address', help='iPad 局域网 IP[:端口]；Wi-Fi 模式可留空自动搜索')
    parser.add_argument('--display-mode', choices=('extend', 'mirror'), help='扩展屏幕或镜像主屏')
    parser.add_argument('--resolution', help='native 或横屏宽x高；镜像时作为等比缩放上限')
    parser.add_argument('--fps', type=int, help='目标帧率，15～60')
    parser.add_argument('--bitrate', type=int, help='目标码率 Mbps，1～50；0 为 USB 24 / Wi-Fi 10')
    parser.add_argument('--monitor', help='Windows 扩展模式的显示器名称（monitors 命令查询）')
    parser.add_argument('--display-position', choices=('left', 'right'),
                        help='新连接的副屏默认放在电脑桌面左侧或右侧')
    parser.add_argument('--worker-token', help=argparse.SUPPRESS)
    parser.add_argument('--receiver-id', default='', help=argparse.SUPPRESS)
    parser.add_argument('--interactive', action='store_true', help='安装显示驱动时显示 Windows 发布者确认窗口')
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
        extra = {'display_position': args.display_position}
        if WINDOWS:
            extra['monitor'] = args.monitor
        service.start(args.transport, args.address, args.display_mode, video, **extra)
    elif args.command == 'stop':
        service.stop()
    elif args.command == 'status':
        print(json.dumps(service.current_status(), ensure_ascii=False, indent=2))
    elif args.command == 'doctor':
        print(json.dumps(service.doctor(), ensure_ascii=False, indent=2))
    elif args.command == 'discover':
        print(json.dumps([r.to_dict() for r in network.discover()], ensure_ascii=False, indent=2))
    elif args.command == 'authorize':
        print(service.authorize().name)
    elif args.command == 'run':
        if WINDOWS:
            from .windows import worker
            worker.run(args.transport or 'usb', args.address or '', args.display_mode or 'mirror',
                       video, monitor=args.monitor or '', token=args.worker_token,
                       receiver_id=args.receiver_id, display_position=args.display_position or 'right')
        else:
            from . import worker
            worker.run(args.transport or 'usb', args.address or '', args.display_mode or 'extend', video,
                       display_position=args.display_position or 'right')
    elif args.command == 'release':
        if WINDOWS:
            service.stop()
        else:
            from . import displays
            displays.release()
    elif args.command == 'encoder-test':
        if WINDOWS:
            from .windows import encoding
        else:
            from . import encoding
        print(encoding.select_encoder())
    elif args.command == 'monitors':
        if not WINDOWS:
            raise RuntimeError('monitors 命令仅用于 Windows。')
        from .windows.desktop import monitors
        print(json.dumps([m.to_dict() for m in monitors()], ensure_ascii=False, indent=2))
    elif args.command == 'install-display-driver':
        if not WINDOWS:
            raise RuntimeError('此命令仅用于 Windows。')
        from .windows.driver_setup import install
        print(install(interactive=args.interactive))
    return 0


def entrypoint():
    try:
        if WINDOWS:
            from .windows.installation import running_application
            with running_application():
                return main()
        return main()
    except Exception as exc:
        if not WINDOWS and len(sys.argv) > 1 and sys.argv[1] == 'run':
            from odx11 import state
            state.StateFile().write({'state': state.PROBLEM, 'problem': str(exc), 'pid': os.getpid()})
        log.exception('%s', exc)
        return 1
