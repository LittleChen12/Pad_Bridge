# SPDX-License-Identifier: GPL-3.0-or-later
"""Repair the old elevated-mkdir ACL, scoped to this user's preferences only."""
import ctypes
import json
import os
from pathlib import Path
import tempfile

from .. import preferences as prefs
from . import device_control, elevation


def user_sid():
    result = device_control.powershell(
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value | ConvertTo-Json', {})
    return json.loads(result.stdout)


def repair(expected_sid):
    # Never repair a different administrator's profile after credential-based
    # UAC. No caller-supplied paths or recursive ACL reset are accepted.
    path = prefs.PREFERENCES.parent
    result = device_control.powershell(r'''
$ErrorActionPreference = 'Stop'
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
if ($sid.Value -ne $p.sid) { throw '请使用原登录账户完成配置权限修复。' }
$directory = Get-Item -LiteralPath $p.directory -Force
if ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '配置目录不能是重解析点。' }
$acl = Get-Acl -LiteralPath $directory.FullName
$rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.SetAccessRule($rule)
Set-Acl -LiteralPath $directory.FullName -AclObject $acl
$file = Join-Path $directory.FullName 'connection.json'
if (Test-Path -LiteralPath $file) {
    if ((Get-Item -LiteralPath $file -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '配置文件不能是重解析点。' }
    $acl = Get-Acl -LiteralPath $file
    $acl.SetAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')))
    Set-Acl -LiteralPath $file -AclObject $acl
}
''', {'directory': str(path), 'sid': expected_sid})
    return result


def probe():
    path = prefs.PREFERENCES
    path.parent.mkdir(parents=True, exist_ok=True)
    # Opening a temporary file tests the real Windows access token, unlike
    # os.access; also check the old file before silently loading defaults.
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.access-')
    os.close(fd)
    Path(name).unlink()
    if path.exists():
        with path.open('r+b'):
            pass


def prepare():
    try:
        probe()
    except PermissionError:
        elevation.run(['repair-preferences', '--caller-sid', user_sid()])
        probe()
    else:
        # An elevated launch can write even to the broken old directory. Repair
        # it now so the next normal launch also works, without another UAC.
        if ctypes.windll.shell32.IsUserAnAdmin():
            repair(user_sid())
