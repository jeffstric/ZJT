@echo off
setlocal enabledelayedexpansion

set PYTHONUTF8=1
chcp 65001 >nul 2>&1

title ZhiJuTong Launcher

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM ============================================================
REM ZhiJuTong launcher - packaging-free startup via uv
REM
REM Runs scripts\launchers\launcher.py with the bundled uv, reusing
REM dependencies from requirements.txt - pystray/Pillow etc.
REM
REM Unlike the PyInstaller-built exe that AV software frequently flags,
REM this is a plain-text script plus an officially-signed python.exe:
REM no bootloader signature, no self-extraction. If the exe is ever
REM quarantined by antivirus, this bat still launches the app.
REM
REM The Chinese-named twin entry just forwards to this file,
REM so CN users get a friendly name and overseas users get this one.
REM ============================================================

set "UV_CMD=%SCRIPT_DIR%bin\uv\uv.exe"
if not exist "!UV_CMD!" (
    echo [ERROR] uv not found at !UV_CMD!
    echo Please make sure the package is fully extracted.
    echo It should contain bin\uv\uv.exe
    echo.
    pause
    exit /b 1
)

REM Network auto-detect: domestic -> China mirrors, overseas -> official sources.
REM Aligns with start.bat so both CN and overseas users get fast installs.
echo Detecting network environment...
powershell -NoProfile -Command "if((Test-NetConnection -ComputerName ghfast.top -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue) -and $?) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 goto overseas

echo Domestic network detected, using China mirrors.
set "UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
set "UV_PYTHON_INSTALL_MIRROR=https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download"
set "UV_HTTP_TIMEOUT=120"
goto run_launcher

:overseas
echo Overseas network detected, using official sources.
set "UV_INDEX_URL=https://pypi.org/simple/"
set "UV_HTTP_TIMEOUT=120"

:run_launcher
echo.
echo Starting ZhiJuTong tray launcher via uv...
echo First launch prepares the Python 3.10 env and dependencies, please wait 1-3 min.
echo.

REM The launcher hides this console once the tray is ready.
REM On failure the window stays open so the exit code below is visible.
"!UV_CMD!" run --python cpython-3.10-windows-x86_64-none --with-requirements requirements.txt scripts\launchers\launcher.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo [ERROR] Launcher exited with code !errorlevel!
    echo ========================================
    echo.
    pause
)

endlocal
