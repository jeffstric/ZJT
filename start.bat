@echo off
setlocal enabledelayedexpansion

title zjt server
color 0A

REM 设置 UTF-8 编码，解决中文路径和文件编码问题
set PYTHONUTF8=1
chcp 65001 >nul 2>&1

REM 镜像源配置
REM   UV_MIRROR     - Python install mirror: auto/ghfast/ghproxy/direct
REM   UV_PIP_MIRROR - PyPI mirror: aliyun/tsinghua/tencent/official
if "%UV_MIRROR%"=="" set UV_MIRROR=auto
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

REM uv 托管的 CPython 安装到项目目录（默认 bin\python），避免写入 %APPDATA%\uv\python
REM 可通过环境变量 UV_PYTHON_INSTALL_DIR 覆盖；便于整包拷贝/离线分发
if "%UV_PYTHON_INSTALL_DIR%"=="" set "UV_PYTHON_INSTALL_DIR=%SCRIPT_DIR%bin\python"
if not exist "%UV_PYTHON_INSTALL_DIR%" mkdir "%UV_PYTHON_INSTALL_DIR%"

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

REM === 网络环境检测（仅在 auto 模式下执行，PowerShell 3秒超时测试国内镜像可达性） ===
if not "%UV_MIRROR%"=="auto" goto :mirror_manual_detect
echo [1.1/4] Detecting network environment...
set "COMFYUI_MIRROR_MODE=domestic"
powershell -NoProfile -Command "if((Test-NetConnection -ComputerName ghfast.top -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue) -and $?) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 goto :mirror_overseas
echo   [INFO] Domestic network detected, using China mirrors
set "UV_MIRROR=ghfast"
set "UV_PIP_MIRROR=aliyun"
set "COMFYUI_MIRROR_MODE=domestic"
set "UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
goto :mirror_detect_done

:mirror_overseas
echo   [INFO] Overseas network detected, using direct mirrors
set "UV_MIRROR=direct"
set "UV_PIP_MIRROR=official"
set "COMFYUI_MIRROR_MODE=overseas"
set "UV_INDEX_URL=https://pypi.org/simple/"
goto :mirror_detect_done

:mirror_manual_detect
echo [1.1/4] Using manually configured mirror: %UV_MIRROR%
set "COMFYUI_MIRROR_MODE=manual"

:mirror_detect_done
echo.

REM === 预下载 Python，多镜像自动回退 ===
REM 逻辑在 scripts\tools\install_python.ps1：按 PID 精确等待/终止下载进程。
REM 不可用 tasklist/taskkill 按进程名判断——托盘链路存在常驻的外层 uv.exe，会被误杀；
REM 也不可再用 timeout /t 计秒——无控制台（stdin 重定向）时它会立即报错退出。
echo [1.2/4] Ensuring Python 3.10 is available...
echo   Install dir: %UV_PYTHON_INSTALL_DIR%
set "MIRROR_IDX=0"
set "AUTO_RETRY=1"

REM 根据网络检测结果或用户手动配置设置镜像索引
if not "!UV_MIRROR!"=="auto" (
    if "%UV_MIRROR%"=="ghfast" set "MIRROR_IDX=0"
    if "%UV_MIRROR%"=="ghproxy" set "MIRROR_IDX=1"
    if "%UV_MIRROR%"=="gh-proxy" set "MIRROR_IDX=2"
    if "%UV_MIRROR%"=="moeyy" set "MIRROR_IDX=3"
    if "%UV_MIRROR%"=="direct" set "MIRROR_IDX=4"
    REM 仅用户手动指定镜像时才禁止回退，auto检测结果允许回退
    if "%COMFYUI_MIRROR_MODE%"=="manual" set "AUTO_RETRY=0"
)

if not exist "%SCRIPT_DIR%logs" mkdir "%SCRIPT_DIR%logs"
set "PS_NO_FALLBACK="
if "!AUTO_RETRY!"=="0" set "PS_NO_FALLBACK=-NoFallback"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\tools\install_python.ps1" -UvCmd "!UV_CMD!" -LogFile "%SCRIPT_DIR%logs\startup_python_install.log" -StartMirrorIdx !MIRROR_IDX! !PS_NO_FALLBACK!
if errorlevel 1 goto :mirror_all_failed
goto :mirror_done

:mirror_all_failed
echo [ERROR] All mirrors failed to download Python 3.10
echo.
echo   Detail log: %SCRIPT_DIR%logs\startup_python_install.log
echo   Possible solutions:
echo   1. Set UV_MIRROR=direct and use a VPN
echo   2. Set UV_MIRROR=ghfast or UV_MIRROR=ghproxy to specify mirror
echo   3. On a machine with network, run:
echo        bin\uv\uv.exe python install cpython-3.10-windows-x86_64-none
echo      then copy the folder:
echo        %UV_PYTHON_INSTALL_DIR%\cpython-3.10*
echo      to the same path on this machine
echo   4. Or download from:
echo      https://github.com/astral-sh/python-build-standalone/releases
echo   5. Check your network/firewall settings
echo.
pause
exit /b 1

:mirror_done
echo.
REM ==========================================

REM === 启动前检查更新 ===
echo [1.5/4] Checking for updates...

REM 自愈：清理 litellm 的 uv 缓存（litellm>=1.92 引入 Rust 编译，普通用户机器无 MSVC linker 会构建失败）
REM 客户机器上可能残留旧版 requirements.txt 解析决策导致 uv 仍选 1.92.0，每次启动前清一次确保走 1.91.x 纯 Python 路径
"!UV_CMD!" cache clean litellm >nul 2>&1

"!UV_CMD!" run --python cpython-3.10-windows-x86_64-none --with-requirements requirements.txt scripts\upgrade_check.py
set "UPGRADE_RC=%errorlevel%"
if %UPGRADE_RC% equ 2 (
    echo [ERROR] 更新检查遇到严重错误
    pause
    exit /b 1
)
if %UPGRADE_RC% equ 1 (
    echo [WARN] 更新检查失败，继续使用本地版本
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

"!UV_CMD!" run --python cpython-3.10-windows-x86_64-none --with-requirements requirements.txt scripts\launchers\start_windows.py

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
