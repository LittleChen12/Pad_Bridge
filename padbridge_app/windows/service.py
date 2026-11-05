# SPDX-License-Identifier: GPL-3.0-or-later
"""User-owned background process; independent of systemd and Windows Services."""
import importlib.metadata
import platform
import subprocess
import sys
import time
import uuid
from .. import network
from ..paths import ROOT
from ..preferences import preferences, save_preferences
from ..video import VideoOptions
from . import desktop, storage, transport, virtual_display


def current_status():
    facts = storage.read_json(storage.STATE)
    if storage.owned_process(facts):
        return facts
    if facts.get('state') == 'problem':
        return facts
    return {'state': 'off'}


def active():
    return storage.owned_process(storage.read_json(storage.STATE)) is not None


def authorize():
    raise RuntimeError('Windows 无需 Linux 显示接口授权。请在 Windows 显示设置中配置已有副屏。')


def start(transport=None, address=None, display_mode=None, video=None, monitor=None, display_position=None):
    with storage.Lock('controller.lock', wait=5):
        saved = preferences()
        transport = transport or saved['transport']
        display_mode = display_mode or saved['display_mode']
        video = video or VideoOptions.from_dict(saved['video_options'])
        monitor = saved.get('monitor', '') if monitor is None else monitor
        display_position = saved.get('display_position', 'right') if display_position is None else display_position
        address = saved['address'] if address is None else address
        if transport not in ('usb', 'wifi'):
            raise ValueError('连接方式必须为 USB 或 Wi-Fi。')
        if display_position not in ('left', 'right'):
            raise ValueError('副屏位置必须为左侧或右侧。')
        automatic = display_mode == 'extend' and monitor in ('', virtual_display.AUTO)
        if active():
            facts = current_status()
            if any((facts.get('transport') != transport, facts.get('display_mode') != display_mode,
                    facts.get('video_options') != video.to_dict(),
                    display_mode == 'extend' and monitor and facts.get('monitor') != monitor,
                    automatic and facts.get('display_position', 'right') != display_position,
                    transport == 'wifi' and address and facts.get('address') != network.format_endpoint(*network.parse_endpoint(address)))):
                raise RuntimeError('请先断开连接，再修改连接或画面参数。')
            return facts
        if automatic:
            if not virtual_display.available():
                raise RuntimeError('扩展屏幕需要虚拟显示组件，请先点击“安装扩展组件”。')
            if video.fps > 60:
                from . import driver_setup, elevation
                if not driver_setup.high_refresh_ready():
                    elevation.run(['install-display-driver', '--interactive'])
                    if not driver_setup.high_refresh_ready():
                        raise RuntimeError('120 Hz 扩展组件尚未就绪，请重新运行安装器修复。')
            screen = None
        else:
            screen = desktop.choose_monitor(display_mode, monitor)
        target = {'transport': transport, 'address': address, 'name': '', 'receiver_id': ''}
        if transport == 'wifi':
            target.update(network.resolve_target(address))
        else:
            # Missing Apple software is an actionable startup error; no cable is
            # a normal waiting state. Wi-Fi never touches the Apple service.
            from .transport import list_devices
            list_devices()
        target.update(display_mode=display_mode, display_position=display_position, video_options=video.to_dict(),
                      monitor=(virtual_display.AUTO if automatic else screen.name) if display_mode == 'extend' else '')
        token = uuid.uuid4().hex
        if getattr(sys, 'frozen', False):
            command = [sys.executable]
        else:
            command = [sys.executable, str(ROOT / 'app.py')]
        command += ['run', '--worker-token', token, '--transport', transport,
                    '--display-mode', display_mode, '--display-position', display_position,
                    '--resolution', video.resolution,
                    '--fps', str(video.fps), '--bitrate', str(video.bitrate_mbps)]
        if video.force_fps:
            command.append('--force-fps')
        if target['monitor']:
            command += ['--monitor', target['monitor']]
        if transport == 'wifi':
            command += ['--address', target['address'], '--receiver-id', target['receiver_id']]
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            facts = storage.read_json(storage.STATE)
            if facts.get('token') == token:
                if facts.get('state') == 'problem':
                    raise RuntimeError(facts.get('problem', '工作进程启动失败。'))
                if storage.owned_process(facts):
                    save_preferences(target)
                    return facts
            if process.poll() is not None:
                raise RuntimeError(f'工作进程启动失败（{process.returncode}）。日志：{storage.LOG}')
            time.sleep(0.05)
        # This is our Popen handle, not a PID taken from a stale state file.
        process.terminate()
        process.wait(5)
        raise RuntimeError(f'工作进程启动超时。日志：{storage.LOG}')


def stop():
    with storage.Lock('controller.lock', wait=5):
        facts = storage.read_json(storage.STATE)
        process = storage.owned_process(facts)
        if process:
            storage.write_json(storage.STOP, {'token': facts['token']})
            import psutil
            try:
                process.wait(timeout=20)
            except psutil.TimeoutExpired:
                process = storage.owned_process(facts)
                if process:
                    process.terminate()
                    process.wait(timeout=5)
        # Only clear the generation that this stop operation observed.
        if storage.read_json(storage.STATE).get('token') == facts.get('token'):
            storage.write_json(storage.STATE, {'state': 'off'})
        storage.STOP.unlink(missing_ok=True)
        virtual_display.recover()
        virtual_display.park_idle()


def cleanup_idle():
    with storage.Lock('controller.lock', wait=5):
        if not active():
            with storage.Lock('worker.lock'):
                virtual_display.recover()
                virtual_display.park_idle()


def doctor(probe=True):
    result = {'platform': platform.platform(), 'python': platform.python_version(),
              'running': active(), 'connection': current_status(), 'log': str(storage.LOG),
              'capabilities': {'mirror': True, 'existing_extended_monitor': True,
                               'automatic_virtual_monitor': virtual_display.available()}}
    result['dependencies'] = {name: importlib.metadata.version(name)
                              for name in ('av', 'zeroconf', 'psutil', 'PySide6-Essentials')}
    try:
        result['monitors'] = [m.to_dict() for m in desktop.monitors()]
    except OSError as exc:
        result['display_error'] = str(exc)
    try:
        result['usb_devices'] = len(transport.list_devices(timeout=1))
    except (OSError, RuntimeError, ValueError) as exc:
        result.update(usb_devices=None, usb_status=str(exc))
    return result
