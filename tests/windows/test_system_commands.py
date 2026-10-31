# SPDX-License-Identifier: GPL-3.0-or-later
"""System PowerShell must ignore incompatible modules inherited from the launching shell."""
from pathlib import Path

from padbridge_app.windows import device_control


def test_signature_cmdlet_uses_windows_module_with_contaminated_parent_environment(tmp_path, monkeypatch):
    module = tmp_path / 'Microsoft.PowerShell.Security'
    module.mkdir()
    (module / 'Microsoft.PowerShell.Security.psd1').write_text(
        "@{RootModule='Microsoft.PowerShell.Security.psm1'; ModuleVersion='99.0'; "
        "FunctionsToExport=@('Get-AuthenticodeSignature')}", encoding='utf-8')
    (module / 'Microsoft.PowerShell.Security.psm1').write_text(
        "throw 'Incompatible inherited PowerShell module'", encoding='utf-8')
    monkeypatch.setenv('PSModulePath', str(tmp_path))
    result = device_control.powershell(
        '(Get-Command Get-AuthenticodeSignature -ErrorAction Stop).Module.Path', {})
    assert Path(result.stdout.strip()).is_relative_to(device_control.POWERSHELL.parent / 'Modules')
