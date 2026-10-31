# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit, once-only installation of the pinned signed VirtualDrivers package."""
import ctypes as ct
from ctypes import wintypes as wt
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid
import winreg
import xml.etree.ElementTree as ET
import zipfile

from . import desktop, storage, virtual_display as vd, device_control

URL = ('https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/'
       '25.7.23/VirtualDisplayDriver-x86.Driver.Only.zip')
SHA256 = 'e24210692b442b39af763536330ce78b423f19342b7a7792c26de3944e418b3a'
HARDWARE = r'Root\MttVDD'
REGISTRY = r'SOFTWARE\MikeTheTech\VirtualDisplayDriver'


class RestartRequired(RuntimeError):
    """The signed driver was installed, but Windows needs a restart."""


class DeviceInfo(ct.Structure):
    _fields_ = [('size', wt.DWORD), ('guid', ct.c_ubyte*16),
                ('instance', wt.DWORD), ('reserved', ct.c_size_t)]


def install_device(inf, interactive=False):
    setup = ct.WinDLL('setupapi', use_last_error=True)
    setup.SetupDiCreateDeviceInfoList.argtypes = [ct.c_void_p, wt.HWND]
    setup.SetupDiCreateDeviceInfoList.restype = wt.HANDLE
    setup.SetupDiCreateDeviceInfoW.argtypes = [wt.HANDLE, wt.LPCWSTR, ct.c_void_p,
                                              wt.LPCWSTR, wt.HWND, wt.DWORD, ct.POINTER(DeviceInfo)]
    setup.SetupDiSetDeviceRegistryPropertyW.argtypes = [wt.HANDLE, ct.POINTER(DeviceInfo),
                                                       wt.DWORD, ct.c_void_p, wt.DWORD]
    setup.SetupDiCallClassInstaller.argtypes = [wt.DWORD, wt.HANDLE, ct.POINTER(DeviceInfo)]
    setup.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
    setup.SetupDiRemoveDevice.argtypes = [wt.HANDLE, ct.POINTER(DeviceInfo)]
    guid = (ct.c_ubyte*16).from_buffer_copy(uuid.UUID('4d36e968-e325-11ce-bfc1-08002be10318').bytes_le)
    handle = setup.SetupDiCreateDeviceInfoList(ct.byref(guid), None)
    if handle == ct.c_void_p(-1).value:
        raise ct.WinError(ct.get_last_error())
    info = DeviceInfo(size=ct.sizeof(DeviceInfo))
    registered = False
    try:
        if not setup.SetupDiCreateDeviceInfoW(handle, 'Display', ct.byref(guid), 'PadBridge virtual display',
                                              None, 1, ct.byref(info)):
            raise ct.WinError(ct.get_last_error())
        ids = ct.create_unicode_buffer(HARDWARE+'\0')
        if not setup.SetupDiSetDeviceRegistryPropertyW(handle, ct.byref(info), 1, ids, ct.sizeof(ids)):
            raise ct.WinError(ct.get_last_error())
        if not setup.SetupDiCallClassInstaller(0x19, handle, ct.byref(info)):
            raise ct.WinError(ct.get_last_error())
        registered = True
        newdev = ct.WinDLL('newdev', use_last_error=True)
        newdev.UpdateDriverForPlugAndPlayDevicesW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR,
                                                              wt.DWORD, ct.POINTER(wt.BOOL)]
        reboot = wt.BOOL()
        # The interactive variant leaves publisher confirmation to the human in
        # Windows' own dialog. Never import certificates or bypass verification.
        flags = 1 | (0 if interactive else 4)
        if not newdev.UpdateDriverForPlugAndPlayDevicesW(None, HARDWARE, str(inf), flags, ct.byref(reboot)):
            error = ct.get_last_error()
            if error & 0xffffffff == 0xe0000242:
                raise RuntimeError('Windows 需要首次确认驱动发布者。请从界面安装扩展组件，或添加 --interactive 显示系统确认窗口。')
            raise ct.WinError(error)
        return bool(reboot.value)
    except BaseException:
        if registered:
            setup.SetupDiRemoveDevice(handle, ct.byref(info))
        raise
    finally:
        setup.SetupDiDestroyDeviceInfoList(handle)


def verify_signatures(directory):
    # Arguments are passed via JSON on stdin, never interpolated into shell code.
    script = "$paths = [Console]::In.ReadToEnd() | ConvertFrom-Json; $paths | ForEach-Object { Get-AuthenticodeSignature -LiteralPath $_ } | ForEach-Object { @{ status=$_.Status.ToString(); signer=$_.SignerCertificate.Subject } } | ConvertTo-Json -Compress"
    paths = [str(directory/name) for name in ('mttvdd.cat', 'MttVDD.dll')]
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            input=json.dumps(paths), capture_output=True, text=True, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    signatures = json.loads(result.stdout)
    if len(signatures) != 2 or any(s['status'] != 'Valid' or 'O=SignPath Foundation' not in s['signer']
                                   for s in signatures):
        raise RuntimeError('虚拟显示驱动签名校验未通过，已取消安装。')


def configuration():
    root = ET.Element('vdd_settings')
    ET.SubElement(ET.SubElement(root, 'monitors'), 'count').text = '1'
    ET.SubElement(ET.SubElement(root, 'gpu'), 'friendlyname').text = 'default'
    modes = ET.SubElement(root, 'resolutions')
    sizes = [(2224, 1668), (1920, 1440), (1920, 1200), (1600, 1200), (1280, 960),
             (1920, 1080), (1280, 720), (2560, 1600), (2560, 1440), (2048, 1536),
             (2360, 1640), (2388, 1668), (2732, 2048), (2266, 1488), (2420, 1668), (2752, 2064)]
    for w, h in sizes:
        for width, height in ((w, h), (h, w)):
            mode = ET.SubElement(modes, 'resolution')
            for key, value in (('width', width), ('height', height), ('refresh_rate', 60)):
                ET.SubElement(mode, key).text = str(value)
    options = ET.SubElement(root, 'options')
    for key in ('CustomEdid', 'PreventSpoof', 'EdidCeaOverride', 'SDR10bit', 'HDRPlus', 'logging', 'debuglogging'):
        ET.SubElement(options, key).text = 'false'
    ET.SubElement(options, 'HardwareCursor').text = 'true'
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def install(interactive=False, archive=None):
    from . import service
    if service.active():
        raise RuntimeError('安装扩展组件前请先断开串流。')
    if device_control.owned_device():
        if not device_control.ready():
            device_control.configure()
        vd.recover()
        vd.park_idle()
        return vd.INSTALL_DIR
    if not ct.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('首次安装需要管理员权限：请以管理员身份启动 PadBridge，再安装扩展组件。')
    if any(a.is_vdd for a in vd.adapters()) or vd.INSTALL_DIR.exists():
        raise RuntimeError('检测到已有虚拟显示驱动或安装目录。为保留现有配置，请使用已有副屏，或检查原驱动。')
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY):
            raise RuntimeError('检测到已有 Virtual Display Driver 配置，已取消覆盖。')
    except FileNotFoundError:
        pass
    before = [m.to_dict() for m in desktop.monitors()]
    with tempfile.TemporaryDirectory(prefix='padbridge-driver-') as temporary:
        directory = Path(temporary)
        bundled = Path(__file__).with_name('VirtualDisplayDriver.zip')
        archive = Path(archive) if archive else bundled
        if not archive.is_file():
            archive = directory/'driver.zip'
            with urllib.request.urlopen(URL, timeout=30) as response, archive.open('wb') as destination:
                shutil.copyfileobj(response, destination)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError('虚拟显示驱动校验值不匹配，已取消安装。')
        with zipfile.ZipFile(archive) as package:
            # Extract only known filenames from the pinned package.
            for name in ('MttVDD.inf', 'MttVDD.dll', 'mttvdd.cat'):
                (directory/name).write_bytes(package.read('VirtualDisplayDriver/'+name))
        verify_signatures(directory)
        vd.INSTALL_DIR.mkdir(parents=True)
        for name in ('MttVDD.inf', 'MttVDD.dll', 'mttvdd.cat'):
            shutil.copy2(directory/name, vd.INSTALL_DIR/name)
        (vd.INSTALL_DIR/'vdd_settings.xml').write_bytes(configuration())
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY) as key:
            winreg.SetValueEx(key, 'VDDPATH', 0, winreg.REG_SZ, str(vd.INSTALL_DIR))
        storage.write_json(vd.OWNER, {'hardware_id': HARDWARE, 'source': URL, 'sha256': SHA256,
                                    'previous_layout': before})
        try:
            reboot = install_device(vd.INSTALL_DIR/'MttVDD.inf', interactive)
        except BaseException:
            # These exact files/key were created above after rejecting existing
            # installs. Roll back only our installation inputs, no tree deletion.
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY)
            for name in ('MttVDD.inf', 'MttVDD.dll', 'mttvdd.cat', 'vdd_settings.xml', 'padbridge-driver.json'):
                (vd.INSTALL_DIR/name).unlink(missing_ok=True)
            if not any(vd.INSTALL_DIR.iterdir()):
                vd.INSTALL_DIR.rmdir()
            raise
    deadline = time.monotonic()+15
    while time.monotonic() < deadline:
        adapter = vd.owned_adapter()
        if adapter:
            if vd.display_config.current()[1]:
                vd.detach(adapter)
            device_control.configure()
            vd.park_idle()
            if reboot:
                raise RestartRequired('驱动已安装，重启 Windows 后即可使用扩展屏幕。')
            return vd.INSTALL_DIR
        time.sleep(0.2)
    # The PnP device can already exist before a display adapter is enumerated
    # (headless installation / pending reboot). Configure its protected controls
    # now so the first unelevated launch after restart needs no extra setup.
    if device_control.owned_device():
        device_control.configure()
        device_control.set_enabled(False)
        if reboot:
            raise RestartRequired('驱动已安装，重启 Windows 后即可使用扩展屏幕。')
        return vd.INSTALL_DIR
    raise RuntimeError('驱动已安装，但虚拟设备尚未就绪；请重启后重新运行安装器。')
