# SPDX-License-Identifier: GPL-3.0-or-later
"""Short-lived maintenance helpers; the controller and worker stay unelevated."""
import json
import subprocess
import sys

from ..paths import ROOT
from . import device_control


def run(arguments):
    command = [sys.executable]
    if not getattr(sys, 'frozen', False):
        command.append(str(ROOT / 'app.py'))
    command.extend(arguments)
    result = device_control.powershell(r'''
$ErrorActionPreference = 'Stop'
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
try {
    $process = Start-Process -FilePath $p.executable -ArgumentList $p.arguments -Verb RunAs -WindowStyle Hidden -PassThru
    $process.WaitForExit()
    @{code=$process.ExitCode} | ConvertTo-Json -Compress
} catch {
    @{code=-1} | ConvertTo-Json -Compress
}
''', {'executable': command[0], 'arguments': subprocess.list2cmdline(command[1:])}, timeout=600)
    code = json.loads(result.stdout)['code']
    if code == -1:
        raise RuntimeError('Windows 管理员确认未完成，请重试并允许此次维护操作。')
    if code:
        raise RuntimeError(f'维护操作未完成（{code}），请查看 PadBridge 日志。')
