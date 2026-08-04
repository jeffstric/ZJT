@echo off
setlocal enabledelayedexpansion

set PYTHONUTF8=1
chcp 65001 >nul 2>&1

title ZhiJuTong Launcher

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM ============================================================
REM ZhiJuTong launcher - persistent runtime managed by bundled uv.
REM Keep this file ASCII-only so every Windows code page parses it.
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

REM The release package normally contains a complete relocatable Python.
REM If it is missing, bundled uv downloads the same build into bin\python.
REM A system Python must never be selected.
set "PYTHON_REQUEST=cpython-3.10.20-windows-x86_64-none"
set "UV_PYTHON_INSTALL_DIR=%SCRIPT_DIR%bin\python"
set "UV_PYTHON_DOWNLOADS=auto"
set "BUNDLED_PYTHON=%UV_PYTHON_INSTALL_DIR%\%PYTHON_REQUEST%\python.exe"
if "%UV_CACHE_DIR%"=="" set "UV_CACHE_DIR=%SCRIPT_DIR%bin\uv-cache"
if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%"

if exist "%UV_PYTHON_INSTALL_DIR%\pyvenv.cfg" (
    echo [ERROR] bin\python is a non-portable virtual environment.
    echo Please re-extract a complete package with bundled Python.
    pause
    exit /b 1
)
if not exist "!BUNDLED_PYTHON!" (
    echo [INFO] Bundled Python not found, downloading to bin\python ...
    echo This only happens once. Please keep the network connected.
    echo.
    "!UV_CMD!" python install !PYTHON_REQUEST!
    if errorlevel 1 (
        echo [WARN] Official source failed, retrying with China mirror...
        set "UV_PYTHON_INSTALL_MIRROR=https://registry.npmmirror.com/-/binary/python-build-standalone"
        "!UV_CMD!" python install !PYTHON_REQUEST!
    )
    if not exist "!BUNDLED_PYTHON!" (
        echo [ERROR] Failed to download Python automatically.
        echo Please check your network, or re-extract the complete package.
        pause
        exit /b 1
    )
    echo [OK] Python downloaded to bin\python.
)
"!BUNDLED_PYTHON!" -I -c "import encodings" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Bundled Python is damaged or non-portable.
    echo Please re-extract the complete application package.
    pause
    exit /b 1
)

REM Network auto-detect: domestic -> China mirrors, overseas -> official sources.
echo Detecting network environment...
powershell -NoProfile -Command "if((Test-NetConnection -ComputerName mirrors.aliyun.com -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue) -and $?) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 goto overseas

echo Domestic network detected, using China mirrors.
set "LAUNCHER_SOURCE=domestic"
set "UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
set "UV_HTTP_TIMEOUT=120"
goto run_launcher

:overseas
echo Overseas network detected, using official sources.
set "LAUNCHER_SOURCE=overseas"
set "UV_INDEX_URL=https://pypi.org/simple/"
set "UV_HTTP_TIMEOUT=120"

:run_launcher
echo.
echo Preparing the ZhiJuTong tray launcher via uv...
echo Using the Python bundled with this package. No Python download is required.
echo First launch prepares dependencies; later launches reuse the persistent runtime.
echo.

REM bootstrap.py has stdlib-only imports and invokes bundled uv for venv/pip work.
"!BUNDLED_PYTHON!" -X utf8 scripts\launchers\bootstrap.py
if not errorlevel 1 goto launcher_done

REM Retry once with the opposite Python-package index; base Python stays local.
if "!LAUNCHER_SOURCE!"=="domestic" (
    echo [WARN] China mirrors failed, retrying with official sources...
    set "UV_INDEX_URL=https://pypi.org/simple/"
) else (
    echo [WARN] Official sources failed, retrying with China mirrors...
    set "UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
)

"!BUNDLED_PYTHON!" -X utf8 scripts\launchers\bootstrap.py
if not errorlevel 1 goto launcher_done

echo.
echo ========================================
echo [ERROR] Launcher bootstrap failed.
echo See logs\launcher_bootstrap.log for details.
echo ========================================
echo.
pause
exit /b 1

:launcher_done
endlocal
exit /b 0
