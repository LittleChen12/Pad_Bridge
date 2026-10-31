# SPDX-License-Identifier: GPL-3.0-or-later
# Installed under Program Files with an Administrators/SYSTEM-only write ACL.
# This privileged helper accepts only a boolean, never executable text or a path.
param([Parameter(Mandatory=$true)][ValidateRange(0, 1)][int]$Enabled)
$ErrorActionPreference = 'Stop'
$device = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'device.json') -Raw | ConvertFrom-Json
if ($device.instance_id -notmatch '^ROOT\\DISPLAY\\[0-9]{4}$') { throw 'Unexpected display instance.' }
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class PadBridgeDisplayControl {
    [DllImport("cfgmgr32.dll", CharSet=CharSet.Unicode)]
    static extern uint CM_Locate_DevNodeW(out uint instance, string id, uint flags);
    [DllImport("cfgmgr32.dll", CharSet=CharSet.Unicode)]
    static extern uint CM_Get_DevNode_Registry_PropertyW(uint instance, uint property,
        out uint type, byte[] buffer, ref uint length, uint flags);
    [DllImport("cfgmgr32.dll")]
    static extern uint CM_Enable_DevNode(uint instance, uint flags);
    [DllImport("cfgmgr32.dll")]
    static extern uint CM_Disable_DevNode(uint instance, uint flags);
    public static void SetEnabled(string id, bool enabled) {
        uint instance, type, length = 8192;
        uint result = CM_Locate_DevNodeW(out instance, id, 0);
        if (result != 0) throw new Exception("Device unavailable: " + result);
        byte[] buffer = new byte[length];
        result = CM_Get_DevNode_Registry_PropertyW(instance, 2, out type, buffer, ref length, 0);
        if (result != 0 || type != 7) throw new Exception("Cannot verify hardware ID.");
        string[] ids = System.Text.Encoding.Unicode.GetString(buffer, 0, (int)length).Split('\0');
        if (!Array.Exists(ids, x => String.Equals(x, @"Root\MttVDD", StringComparison.OrdinalIgnoreCase)))
            throw new Exception("Refusing to change another device.");
        // UI_NOT_OK | PERSIST: the idle monitor also stays absent after reboot.
        result = enabled ? CM_Enable_DevNode(instance, 0) : CM_Disable_DevNode(instance, 3);
        if (result != 0) throw new Exception("Display state change failed: " + result);
    }
}
'@
[PadBridgeDisplayControl]::SetEnabled($device.instance_id, [bool]$Enabled)
