@echo off
setlocal enabledelayedexpansion

title zjt server
color 0A

REM 设置 UTF-8 编码，解决中文路径和文件编码问题
set PYTHONUTF8=1
chcp 65001 >nul 2>&1

REM PyPI 镜像配置。Python 已随程序包提供，用户侧禁止下载 Python。
REM   UV_PIP_MIRROR - PyPI mirror: aliyun/tsinghua/tencent/official
if "%UV_PIP_MIRROR%"=="" set UV_PIP_MIRROR=aliyun

REM PyPI 镜像
if "%UV_PIP_MIRROR%"=="aliyun" (
    set "UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
) else if "%UV_PIP_MIRROR%"=="tsinghua" (
    set "UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/"
) else if "%UV_PIP_MIRROR%"=="tencent" (
    set "UV_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple/"
) else if "%UV_PIP_MIRROR%"=="official" (
    set "UV_INDEX_URL=https://pypi.org/simple/"
)

if "%comfyui_env%"=="" (
    set comfyui_env=prod
)

echo.
echo ========================================
echo   zjt server Startup
echo   Environment: %comfyui_env%
echo ========================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Use only the complete Python distribution bundled with this package.
set "PYTHON_REQUEST=cpython-3.10.20-windows-x86_64-none"
set "UV_PYTHON_INSTALL_DIR=%SCRIPT_DIR%bin\python"
set "UV_PYTHON_DOWNLOADS=never"
set "BUNDLED_PYTHON=%UV_PYTHON_INSTALL_DIR%\%PYTHON_REQUEST%\python.exe"
if "%UV_CACHE_DIR%"=="" set "UV_CACHE_DIR=%SCRIPT_DIR%bin\uv-cache"
if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%"

echo [1/4] Checking uv package manager...
set "UV_CMD=%SCRIPT_DIR%bin\uv\uv.exe"
if not exist "!UV_CMD!" (
    echo [INFO] Downloading uv...
    if not exist "bin\uv" mkdir "bin\uv"
    powershell -ExecutionPolicy ByPass -c "Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'bin\uv\uv.zip'"

    if errorlevel 1 (
        echo [ERROR] Failed to download uv
        echo.
        pause
        exit /b 1
    )

    powershell -ExecutionPolicy ByPass -c "Expand-Archive -Path 'bin\uv\uv.zip' -DestinationPath 'bin\uv' -Force"
    del "bin\uv\uv.zip" >nul 2>&1
    echo [OK] uv downloaded
) else (
    echo [OK] uv found
)

REM === 网络环境检测（只选择 PyPI 依赖源，不下载 Python） ===
echo [1.1/4] Detecting network environment...
powershell -NoProfile -Command "if((Test-NetConnection -ComputerName mirrors.aliyun.com -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue) -and $?) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 goto :mirror_overseas
echo   [INFO] Domestic network detected, using China mirrors
set "UV_PIP_MIRROR=aliyun"
set "UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
goto :mirror_detect_done

:mirror_overseas
echo   [INFO] Overseas network detected, using direct mirrors
set "UV_PIP_MIRROR=official"
set "UV_INDEX_URL=https://pypi.org/simple/"
goto :mirror_detect_done

:mirror_detect_done
echo.

echo [1.2/4] Checking bundled Python 3.10...
if exist "%UV_PYTHON_INSTALL_DIR%\pyvenv.cfg" (
    echo [ERROR] bin\python is a non-portable virtual environment.
    echo Please re-extract a complete package with bundled Python.
    pause
    exit /b 1
)
if not exist "!BUNDLED_PYTHON!" (
    echo [ERROR] Bundled Python not found: !BUNDLED_PYTHON!
    echo Please re-extract the complete application package.
    pause
    exit /b 1
)
"!BUNDLED_PYTHON!" -X utf8 -c "import sys; print('[OK] Bundled Python', sys.version.split()[0])"
if errorlevel 1 (
    echo [ERROR] Bundled Python is damaged. Please re-extract the package.
    pause
    exit /b 1
)
echo.
REM ==========================================

REM === 启动前检查更新 ===
echo [1.5/4] Checking for updates...

"!UV_CMD!" run --no-python-downloads --python "!BUNDLED_PYTHON!" --with-requirements requirements.txt scripts\upgrade_check.py
set "UPGRADE_RC=%errorlevel%"
if %UPGRADE_RC% equ 2 (
    echo [ERROR] 更新检查遇到严重错误
    pause
    exit /b 1
)
if %UPGRADE_RC% equ 1 (
    echo [INFO] 更新检查未完成（网络/源不可用），继续使用本地版本
)
if %UPGRADE_RC% equ 10 (
    echo [INFO] 代码已更新，正在重新启动...
    endlocal
    "%~f0" %*
    exit /b
)
echo.
REM =====================

echo [2/4] Checking config file...
if not exist "config_%comfyui_env%.yml" (
    echo [INFO] Config file not found, will be auto-created from config.example.yml
) else (
    echo [OK] config_%comfyui_env%.yml found
)
echo.

echo [3/4] Checking MySQL...
if not exist "bin\mysql" (
    echo [ERROR] MySQL directory not found: bin\mysql
    echo Please deploy MySQL to bin\mysql directory
    echo.
    pause
    exit /b 1
)
echo [OK] MySQL directory found
echo.

echo [4/4] Starting services...
echo ========================================
echo.

"!UV_CMD!" run --no-python-downloads --python "!BUNDLED_PYTHON!" --with-requirements requirements.txt scripts\launchers\start_windows.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo [ERROR] Program exited with code: !errorlevel!
    echo ========================================
    echo.
    pause
)

if not "%TRAY_MODE%"=="1" (
    echo.
    echo Press any key to exit...
    pause >nul
)
endlocal
