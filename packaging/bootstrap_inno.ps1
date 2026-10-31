# Build dependency only: extract a pinned, signed compiler in portable mode.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskTools = Join-Path $taskRoot '.cache\tools'
$taskCompilerDir = Join-Path $taskTools 'inno-7.1.1'
$taskInstaller = Join-Path $taskTools 'innosetup-7.1.1-x64.exe'
$taskHash = '8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0'
New-Item -ItemType Directory -Path $taskTools -Force | Out-Null
if (-not (Test-Path -LiteralPath $taskInstaller)) {
    Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe' -OutFile $taskInstaller -UseBasicParsing
}
if ((Get-FileHash -LiteralPath $taskInstaller -Algorithm SHA256).Hash -ne $taskHash) {
    throw 'Inno Setup download checksum mismatch.'
}
$taskSignature = Get-AuthenticodeSignature -LiteralPath $taskInstaller
if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch 'CN=Pyrsys B\.V\.') {
    throw 'Inno Setup download signature is invalid.'
}
if (-not (Test-Path -LiteralPath (Join-Path $taskCompilerDir 'ISCC.exe'))) {
    $taskArguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/CURRENTUSER', '/PORTABLE=1', '/NOICONS', ('/DIR="' + $taskCompilerDir + '"'))
    $taskProcess = Start-Process -FilePath $taskInstaller -ArgumentList $taskArguments -WindowStyle Hidden -Wait -PassThru
    if ($taskProcess.ExitCode -ne 0) { throw "Inno Setup extraction failed: $($taskProcess.ExitCode)" }
}
$taskCompiler = Join-Path $taskCompilerDir 'ISCC.exe'
if (-not (Test-Path -LiteralPath $taskCompiler)) { throw 'Inno Setup compiler is missing.' }
Write-Host "Compiler ready: $taskCompiler"
