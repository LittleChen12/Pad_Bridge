param([switch]$Smoke)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = "$PSScriptRoot;$PSScriptRoot\vendor\opendisplay-x11"
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run bootstrap.ps1 first.' }
& $python -m pytest -q tests/test_network.py tests/windows vendor/opendisplay-x11/tests/test_protocol.py vendor/opendisplay-x11/tests/test_annexb.py
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $python app.py encoder-test
if ($LASTEXITCODE -ne 0) { throw 'Encoder check failed.' }
if ($Smoke) {
    & $python tests/windows/smoke_stream.py
    if ($LASTEXITCODE -ne 0) { throw 'Desktop streaming smoke test failed.' }
}
