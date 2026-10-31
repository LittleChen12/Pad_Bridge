@echo off
setlocal
set "PYTHONUTF8=1"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Run: powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
    exit /b 1
)
if "%~1"=="" (
    start "PadBridge" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py" ui
    exit /b 0
)
"%~dp0.venv\Scripts\python.exe" "%~dp0app.py" %*
exit /b %errorlevel%
