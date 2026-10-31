param([string]$Python = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Program" }
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if (-not $Python) {
        if (Test-Path -LiteralPath 'runtime\python\python.exe') {
            $Python = Join-Path $PSScriptRoot 'runtime\python\python.exe'
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            $Python = (& py -3 -c 'import sys; print(sys.executable)')
        } else {
            $command = Get-Command python -ErrorAction SilentlyContinue
            if ($command -and $command.Source -notmatch 'WindowsApps') { $Python = $command.Source }
        }
    }
    if (-not $Python) { throw 'Install Python 3.12-3.14 x64, or pass -Python C:\path\python.exe.' }
    Invoke-Checked $Python @('-c', 'import sys,struct; assert (3,12) <= sys.version_info[:2] <= (3,14) and struct.calcsize(''P'')==8, ''Python 3.12-3.14 x64 required''')
    Invoke-Checked $Python @('-m', 'venv', '.venv')
}
$env:PYTHONUTF8 = '1'
Invoke-Checked '.\.venv\Scripts\python.exe' @('-m', 'pip', 'install', '--only-binary=:all:', '-r', 'requirements-windows.txt')
Invoke-Checked '.\.venv\Scripts\python.exe' @('app.py', 'doctor')
Write-Host 'Ready. Run .\padbridge.cmd, or .\padbridge.cmd encoder-test.'
