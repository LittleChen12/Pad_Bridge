# SPDX-License-Identifier: GPL-3.0-or-later
"""Enable only our installed PnP device, including from an unelevated controller."""
import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from . import storage

HARDWARE = r'Root\MttVDD'
VERSION = 1
DIRECTORY = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'PadBridge' / 'DisplayControl'
TASK_FOLDER = r'\PadBridgeDisplayControl'
POWERSHELL = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


class DeviceInfo(ct.Structure):
    _fields_ = [('size', wt.DWORD), ('guid', ct.c_ubyte*16),
                ('instance', wt.DWORD), ('reserved', ct.c_size_t)]


@dataclass(frozen=True)
class Device:
    instance_id: str
    disabled: bool


def devices():
    setup = ct.WinDLL('setupapi', use_last_error=True)
    setup.SetupDiGetClassDevsW.argtypes = [ct.c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
    setup.SetupDiGetClassDevsW.restype = wt.HANDLE
    setup.SetupDiEnumDeviceInfo.argtypes = [wt.HANDLE, wt.DWORD, ct.POINTER(DeviceInfo)]
    setup.SetupDiGetDeviceRegistryPropertyW.argtypes = [wt.HANDLE, ct.POINTER(DeviceInfo), wt.DWORD,
                                                        ct.c_void_p, ct.c_void_p, wt.DWORD, ct.c_void_p]
    setup.SetupDiGetDeviceInstanceIdW.argtypes = [wt.HANDLE, ct.POINTER(DeviceInfo), wt.LPWSTR,
                                                 wt.DWORD, ct.c_void_p]
    setup.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
    cfg = ct.WinDLL('cfgmgr32')
    cfg.CM_Get_DevNode_Status.argtypes = [ct.POINTER(wt.ULONG), ct.POINTER(wt.ULONG), wt.DWORD, wt.ULONG]
    guid = (ct.c_ubyte*16).from_buffer_copy(uuid.UUID('4d36e968-e325-11ce-bfc1-08002be10318').bytes_le)
    handle = setup.SetupDiGetClassDevsW(ct.byref(guid), None, None, 2)
    if handle == ct.c_void_p(-1).value:
        raise ct.WinError(ct.get_last_error())
    result = []
    try:
        for index in range(256):
            info = DeviceInfo(size=ct.sizeof(DeviceInfo))
            if not setup.SetupDiEnumDeviceInfo(handle, index, ct.byref(info)):
                error = ct.get_last_error()
                if error == 259:
                    break
                raise ct.WinError(error)
            ids = ct.create_unicode_buffer(4096)
            if not setup.SetupDiGetDeviceRegistryPropertyW(handle, ct.byref(info), 1, None,
                                                            ids, ct.sizeof(ids), None):
                continue
            if HARDWARE.lower() not in [s.lower() for s in ids[:].split('\0')]:
                continue
            name = ct.create_unicode_buffer(512)
            if not setup.SetupDiGetDeviceInstanceIdW(handle, ct.byref(info), name, len(name), None):
                raise ct.WinError(ct.get_last_error())
            status, problem = wt.ULONG(), wt.ULONG()
            code = cfg.CM_Get_DevNode_Status(ct.byref(status), ct.byref(problem), info.instance, 0)
            if code:
                raise OSError(f'无法读取虚拟显示设备状态：{code}')
            result.append(Device(name.value, problem.value == 22))
        return result
    finally:
        setup.SetupDiDestroyDeviceInfoList(handle)


def owned_device():
    from .virtual_display import OWNER
    owner = storage.read_json(OWNER)
    if owner.get('hardware_id') != HARDWARE:
        return None
    matches = devices()
    if len(matches) != 1:
        return None
    device = matches[0]
    if owner.get('instance_id', device.instance_id).upper() != device.instance_id.upper():
        return None
    return device


def ready():
    from .virtual_display import OWNER
    owner = storage.read_json(OWNER)
    return (owner.get('device_control_version') == VERSION and
            (DIRECTORY / 'display_control.ps1').is_file() and
            storage.read_json(DIRECTORY / 'device.json').get('instance_id') == owner.get('instance_id'))


def powershell(script, data):
    script = '[Console]::OutputEncoding = [Console]::InputEncoding = New-Object Text.UTF8Encoding($false)\n' + script
    return subprocess.run([str(POWERSHELL), '-NoProfile', '-NonInteractive', '-Command', script],
                          input=json.dumps(data), text=True, encoding='utf-8', errors='replace', capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW, timeout=45, check=True)


def configure():
    """Explicit component installation only. Tasks execute a protected, fixed script."""
    from .virtual_display import OWNER
    device = owned_device()
    if not device:
        raise RuntimeError('无法唯一确认 PadBridge 安装的虚拟显示设备。')
    if not ct.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('扩展组件需要更新一次：请以管理员身份启动 PadBridge，点击“安装扩展组件”。')
    # The task runs no project/extraction-directory code and accepts no commands
    # or paths from callers. Only Administrators/SYSTEM may modify its inputs.
    script = r'''
$ErrorActionPreference = 'Stop'
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$directory = [IO.Directory]::CreateDirectory($p.directory)
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)')
Set-Acl -LiteralPath $directory.FullName -AclObject $acl
[IO.File]::WriteAllText((Join-Path $directory.FullName 'display_control.ps1'), $p.script, (New-Object Text.UTF8Encoding($true)))
[IO.File]::WriteAllText((Join-Path $directory.FullName 'device.json'), ($p.device | ConvertTo-Json -Compress))
$fileAcl = New-Object Security.AccessControl.FileSecurity
$fileAcl.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x1200a9;;;BU)')
foreach ($name in @('display_control.ps1', 'device.json')) {
    Set-Acl -LiteralPath (Join-Path $directory.FullName $name) -AclObject $fileAcl
}
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$security = 'D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGX;;;IU)'
try { $folder = $scheduler.GetFolder($p.folder) }
catch { $folder = $scheduler.GetFolder('\').CreateFolder($p.folder.TrimStart('\'), $security) }
$folder.SetSecurityDescriptor($security, 0)
foreach ($enabled in @(0, 1)) {
    $name = if ($enabled) { 'Enable' } else { 'Disable' }
    $definition = $scheduler.NewTask(0)
    $definition.RegistrationInfo.Description = 'PadBridge owned virtual display lifecycle v1'
    $definition.Principal.UserId = 'S-1-5-18'
    $definition.Principal.LogonType = 5
    $definition.Principal.RunLevel = 1
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.ExecutionTimeLimit = 'PT30S'
    $definition.Settings.MultipleInstances = 2
    $action = $definition.Actions.Create(0)
    $action.Path = $p.powershell
    $action.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $directory.FullName 'display_control.ps1') + '" -Enabled ' + $enabled
    if (-not $enabled) { $null = $definition.Triggers.Create(8) }
    $null = $folder.RegisterTaskDefinition($name, $definition, 6, 'SYSTEM', $null, 5, $security)
}
'''
    powershell(script, {'directory': str(DIRECTORY), 'folder': TASK_FOLDER, 'powershell': str(POWERSHELL),
                        'device': {'instance_id': device.instance_id},
                        'script': Path(__file__).with_name('display_control.ps1').read_text(encoding='utf-8')})
    owner = storage.read_json(OWNER)
    storage.write_json(OWNER, {**owner, 'instance_id': device.instance_id, 'device_control_version': VERSION})


def set_enabled(enabled):
    device = owned_device()
    if not device:
        raise RuntimeError('无法唯一确认 PadBridge 虚拟显示设备，已保留当前显示配置。')
    if device.disabled == (not enabled):
        return
    if not ready():
        raise RuntimeError('请先更新扩展组件，才能自动添加和移除 iPad 副屏。')
    action = 'Enable' if enabled else 'Disable'
    # Wait for this exact task instance to finish before another transition.
    # Otherwise a delayed Enable could run after a timed-out connection closed.
    script = r'''
$ErrorActionPreference = 'Stop'
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$task = $scheduler.GetFolder($p.folder).GetTask($p.action)
$running = $task.Run($null)
$deadline = [DateTime]::UtcNow.AddSeconds(20)
$finished = $false
try {
    do {
        Start-Sleep -Milliseconds 50
        try { $running.Refresh() }
        catch [System.Runtime.InteropServices.COMException] {
            # A completed instance is removed from the scheduler. This is its
            # normal completion signal, not a failure to change the device.
            if ($_.Exception.HResult -eq -2147216629) { $finished = $true; break }
            throw
        }
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Display control task timed out.' }
    } while ($running.State -in @(2, 4))
    $finished = $true
    if ($task.LastTaskResult -ne 0) { throw ('Display control failed: ' + $task.LastTaskResult) }
} finally {
    if (-not $finished) { $running.Stop() }
}
'''
    try:
        powershell(script, {'folder': TASK_FOLDER, 'action': action})
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError('虚拟显示启停任务未能完成，请以管理员身份重新安装扩展组件。') from exc
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        current = owned_device()
        if not current or current.instance_id != device.instance_id:
            raise RuntimeError('虚拟显示设备身份发生变化，已停止操作。')
        if current.disabled == (not enabled):
            return
        time.sleep(0.1)
    raise RuntimeError('Windows 未能及时' + ('启用' if enabled else '移除') + '虚拟屏，请重新安装扩展组件后重试。')
