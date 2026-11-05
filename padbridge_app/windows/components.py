# SPDX-License-Identifier: GPL-3.0-or-later
"""Installer-only provisioning; ordinary application startup never installs software."""
import configparser
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

import psutil

from . import device_control, driver_setup

APPLE_URL = ('https://swcdn.apple.com/content/downloads/20/49/047-76422/'
             'qcw2a7028lr8yp4rdkrfyzkvlhi9q1gg2g/AppleMobileDeviceSupport64.msi')
APPLE_SHA256 = 'b60533fb54e7bd81ffc52d99678a9cce04e58cb54a76281bd7b1309f20d360e9'
APPLE_SERVICE = 'Apple Mobile Device Service'


def usb_ready():
    from . import transport
    try:
        # An empty device list is success: setup must work without an iPad.
        transport.list_devices(timeout=1)
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def apple_service_exists():
    try:
        psutil.win_service_get(APPLE_SERVICE).status()
        return True
    except psutil.NoSuchProcess:
        return False


def probe():
    apple = 'ready' if usb_ready() else ('repair' if apple_service_exists() else 'missing')
    device = device_control.owned_device()
    if device:
        display = 'ready' if device_control.ready() and driver_setup.high_refresh_ready() else 'repair'
    elif device_control.devices():
        # A different application's VirtualDrivers instance must not be adopted.
        display = 'conflict'
    else:
        display = 'missing'
    return {'apple': apple, 'display': display, 'restart': '0', 'error': ''}


def verify_apple(package):
    package = Path(package)
    with package.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != APPLE_SHA256:
            raise RuntimeError('Apple USB 组件校验失败，请重新运行安装器下载。')
    result = device_control.powershell(r'''
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$s = Get-AuthenticodeSignature -LiteralPath $p.path
@{status=$s.Status.ToString(); signer=$s.SignerCertificate.Subject} | ConvertTo-Json -Compress
''', {'path': str(package)})
    signature = json.loads(result.stdout)
    if signature['status'] != 'Valid' or 'O=Apple Inc.' not in (signature['signer'] or ''):
        raise RuntimeError('Apple USB 组件的发布者签名无效，已取消安装。')


def start_apple_service():
    device_control.powershell(r'''
$ErrorActionPreference = 'Stop'
Start-Service -Name 'Apple Mobile Device Service'
''', {})


def wait_for_usb(timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if usb_ready():
            return True
        time.sleep(.25)
    return False


def provision(apple_package=None, interactive=False, log_dir=None):
    state = probe()
    if state['display'] == 'conflict':
        raise RuntimeError('检测到其他软件管理的 Virtual Display Driver，无法自动配置。'
                           '请先处理该驱动后重试；安装器不会覆盖它。')
    if state['apple'] == state['display'] == 'ready':
        return state
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('需要管理员权限配置 USB 和扩展组件，请允许安装器的 Windows 确认窗口。')
    if state['apple'] == 'missing':
        if not apple_package:
            raise RuntimeError('缺少 Apple USB 安装文件，请重新运行 PadBridge 安装器。')
        verify_apple(apple_package)
        log_dir = Path(log_dir) if log_dir else Path(apple_package).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/msiexec.exe'),
                                 '/i', str(Path(apple_package).resolve()), '/qn', '/norestart',
                                 'REBOOT=ReallySuppress', '/L*v', str(log_dir / 'apple-usb.log')],
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
        if result.returncode not in (0, 3010, 1641):
            raise RuntimeError(f'Apple USB 组件安装失败（{result.returncode}），请关闭其他安装程序后重试。'
                               f'日志：{log_dir / "apple-usb.log"}')
        state['restart'] = '1' if result.returncode in (3010, 1641) else '0'
    if state['apple'] != 'ready':
        try:
            start_apple_service()
        except subprocess.CalledProcessError:
            if state['restart'] != '1':
                raise RuntimeError('Apple USB 服务无法启动，请查看安装日志后重试。') from None
        if wait_for_usb():
            state['apple'] = 'ready'
        elif state['restart'] == '1':
            state['apple'] = 'restart'
        else:
            raise RuntimeError('Apple USB 服务未响应，安装未完成。请重新运行安装器修复。')
    if state['display'] != 'ready':
        try:
            driver_setup.install(interactive=interactive)
        except driver_setup.RestartRequired:
            state['restart'] = '1'
            state['display'] = 'restart'
        else:
            if not device_control.owned_device() or not device_control.ready() or not driver_setup.high_refresh_ready():
                raise RuntimeError('扩展组件未通过安装后检查，请重新运行安装器。')
            state['display'] = 'ready'
    return state


def run(result_path, check=False, apple_package=None, interactive=False, log_dir=None):
    """Write UTF-16 INI for Inno Setup, including failures; never report partial success."""
    state = {'apple': 'unknown', 'display': 'unknown', 'restart': '0', 'error': ''}
    code = 1
    try:
        from .installation import prepare_system_helper
        prepare_system_helper()
        if check and apple_package:
            verify_apple(apple_package)
        state = probe() if check else provision(apple_package, interactive, log_dir)
        code = 0
    except Exception as exc:
        if isinstance(exc, driver_setup.PublisherConfirmationRequired):
            state['reason'] = 'publisher-confirmation'
            code = 24
        log = Path(log_dir or Path(result_path).parent) / 'components-error.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        details = traceback.format_exc()
        if isinstance(exc, subprocess.CalledProcessError):
            details += f'\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}\n'
            message = 'Windows 组件配置命令执行失败'
        else:
            message = str(exc)
        log.write_text(details, encoding='utf-8')
        state['error'] = message.replace('\r', ' ').replace('\n', ' ').rstrip('。.') + f'。日志：{log}'
    parser = configparser.ConfigParser(interpolation=None)
    parser['components'] = state
    with Path(result_path).open('w', encoding='utf-16') as stream:
        parser.write(stream)
    print(json.dumps(state, ensure_ascii=False))
    return code
