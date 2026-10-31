# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller/worker boundary. Importing this module starts no capture or GPU work."""
import json
import os
import subprocess
from odx11 import state, usbmux, protocol
from . import displays, network
from .paths import ROOT, LAUNCHER, UNIT, CONNECTION
from .preferences import preferences, save_preferences
from .video import VideoOptions


def active():
    result = subprocess.run(['systemctl', '--user', 'is-active', UNIT],
                            capture_output=True, text=True)
    return result.stdout.strip() in ('active', 'activating')


def authorize():
    connector = displays.choose_connector()
    if not os.access(connector / 'status', os.W_OK):
        subprocess.run(['/usr/bin/pkexec', '/usr/bin/python3', '-I',
                        str(ROOT / 'enable_display.py'), connector.name], check=True)
    if not os.access(connector / 'status', os.W_OK):
        raise PermissionError('显示接口授权未完成，请在系统弹窗中输入电脑登录密码。')
    return connector


def current_status():
    facts = state.read()
    try:
        connection = json.loads(CONNECTION.read_text())
        if connection.get('pid') == facts.get('pid'):
            facts.update(connection)
    except (OSError, ValueError, AttributeError):
        pass
    return facts


def start(transport=None, address=None, display_mode=None, video=None, display_position=None):
    if os.environ.get('XDG_SESSION_TYPE', 'x11') != 'x11':
        raise RuntimeError('当前版本需要 Xorg。请在 Ubuntu 登录界面选择“Ubuntu on Xorg”后使用。')
    if active():
        current = current_status()
        if transport and current.get('transport', 'usb') != transport:
            raise RuntimeError('请先停止当前副屏，再切换连接方式。')
        if display_mode and current.get('display_mode', 'extend') != display_mode:
            raise RuntimeError('请先停止当前画面，再切换扩展 / 镜像模式。')
        if video and video.to_dict() != current.get('video_options', VideoOptions().to_dict()):
            raise RuntimeError('请先停止画面，再修改参数并启动。')
        if display_position and display_position != current.get('display_position', 'right'):
            raise RuntimeError('请先断开连接，再修改副屏默认位置。')
        return current
    previous = preferences()
    transport = transport or previous['transport']
    display_mode = display_mode or previous['display_mode']
    video = video or VideoOptions.from_dict(previous['video_options'])
    display_position = display_position or previous['display_position']
    if display_position not in ('left', 'right'):
        raise ValueError('副屏位置必须为左侧或右侧。')
    if transport not in ('usb', 'wifi'):
        raise ValueError('连接方式必须为 USB 或 Wi-Fi。')
    if display_mode not in ('extend', 'mirror'):
        raise ValueError('显示模式必须为扩展或镜像。')
    target = {'transport': 'usb', 'address': previous['address'], 'name': previous['name']}
    if transport == 'wifi':
        target = network.resolve_target(previous['address'] if address is None else address)
    target['display_mode'] = display_mode
    target['video_options'] = video.to_dict()
    target['display_position'] = display_position
    target['monitor'] = previous['monitor']
    if display_mode == 'extend':
        authorize()
    command = ['systemd-run', '--user', '--unit=padbridge', '--collect',
               '--property=Description=PadBridge iPad display',
               '--property=TimeoutStopSec=15', '--property=KillSignal=SIGINT',
               f'--property=ExecStopPost={LAUNCHER} release']
    for name in ('DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE', 'LANG'):
        if name in os.environ:
            command.append(f'--setenv={name}={os.environ[name]}')
    worker = [LAUNCHER, 'run', '--transport', transport, '--display-mode', display_mode]
    worker += ['--resolution', video.resolution, '--fps', str(video.fps),
               '--bitrate', str(video.bitrate_mbps), '--display-position', display_position]
    if transport == 'wifi':
        worker += ['--address', target['address']]
    subprocess.run([*command, *worker], check=True)
    save_preferences(target)
    return target


def stop():
    result = subprocess.run(['systemctl', '--user', 'stop', UNIT], capture_output=True, check=False)
    if result.returncode and active():
        raise RuntimeError('未能停止副屏服务，请查看运行日志。')
    state.StateFile().clear()


def doctor(probe=True):
    result = {'session': os.environ.get('XDG_SESSION_TYPE'), 'display': os.environ.get('DISPLAY')}
    result['running'] = active()
    result['connection'] = current_status() if result['running'] else preferences()
    if result['connection'].get('display_mode', 'extend') == 'extend':
        port = displays.choose_connector()
        result.update(connector=port.name, output=displays.resolve_output(port),
                      authorized=os.access(port / 'status', os.W_OK))
    try:
        devices = usbmux.list_devices('/var/run/usbmuxd', 3)
        result['usb_devices'] = len(devices)
    except (OSError, EOFError, usbmux.MuxError) as exc:
        # usbmuxd may exit after the last cable is unplugged. Wi-Fi is independent.
        devices = []
        result['usb_devices'] = None
        result['usb_status'] = f'usbmuxd 不可用（不影响 Wi-Fi）：{exc}'
    if probe and devices and not result['running']:
        try:
            with usbmux.connect('/var/run/usbmuxd', devices[0]['DeviceID'], 9000, 3) as sock:
                sock.settimeout(3)
                n = int.from_bytes(usbmux._recv_exact(sock, 4), 'big')
                if not 0 < n < protocol.MAX_INBOUND:
                    raise ValueError('Invalid receiver greeting length')
                hello = json.loads(usbmux._recv_exact(sock, n))
                result['receiver'] = {key: hello.get(key) for key in
                                      ('type', 'device', 'pv', 'panel', 'displayMaxFrameRate')}
        except (OSError, EOFError, ValueError, usbmux.MuxError) as exc:
            result['receiver_error'] = str(exc)
    return result
