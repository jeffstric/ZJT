@echo off
setlocal enabledelayedexpansion

title ComfyUI Server Startup
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
echo   ComfyUI Server Startup
echo   Environment: %comfyui_env%
echo ========================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

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

REM === 预下载 Python，支持多镜像自动回退（默认 80 秒超时） ===
echo [1.2/4] Ensuring Python 3.10 is available...
set "PYTHON_READY=0"
set "MIRROR_IDX=0"
set "AUTO_RETRY=1"
set "SUCCESS_FLAG=%TEMP%\comfyui_python_ok.flag"
set "MIRROR_TIMEOUT=80"

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

:try_mirror
if "!MIRROR_IDX!"=="0" set "MIRROR_NAME=ghfast"
if "!MIRROR_IDX!"=="0" set "MIRROR_URL=https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download"
if "!MIRROR_IDX!"=="0" set "MIRROR_TIMEOUT=80"
if "!MIRROR_IDX!"=="1" set "MIRROR_NAME=ghproxy"
if "!MIRROR_IDX!"=="1" set "MIRROR_URL=https://ghproxy.cn/https://github.com/astral-sh/python-build-standalone/releases/download"
if "!MIRROR_IDX!"=="1" set "MIRROR_TIMEOUT=80"
if "!MIRROR_IDX!"=="2" set "MIRROR_NAME=gh-proxy"
if "!MIRROR_IDX!"=="2" set "MIRROR_URL=https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download"
if "!MIRROR_IDX!"=="2" set "MIRROR_TIMEOUT=80"
if "!MIRROR_IDX!"=="3" set "MIRROR_NAME=moeyy"
if "!MIRROR_IDX!"=="3" set "MIRROR_URL=https://github.moeyy.xyz/https://github.com/astral-sh/python-build-standalone/releases/download"
if "!MIRROR_IDX!"=="3" set "MIRROR_TIMEOUT=80"
if "!MIRROR_IDX!"=="4" set "MIRROR_NAME=direct"
if "!MIRROR_IDX!"=="4" set "MIRROR_URL="
if "!MIRROR_IDX!"=="4" set "MIRROR_TIMEOUT=120"
if "!MIRROR_IDX!"=="5" goto :mirror_all_failed

del "!SUCCESS_FLAG!" 2>nul
echo   Trying !MIRROR_NAME! mirror (!MIRROR_TIMEOUT!s timeout)...

if not "!MIRROR_URL!"=="" goto :mirror_has_url
start /B "" "!UV_CMD!" python install cpython-3.10-windows-x86_64-none >nul 2>&1
goto :wait_for_completion

:mirror_has_url
start /B "" "!UV_CMD!" python install cpython-3.10-windows-x86_64-none --mirror "!MIRROR_URL!" >nul 2>&1

:wait_for_completion
set "TIMEOUT_COUNT=0"
:wait_loop
tasklist /FI "IMAGENAME eq uv.exe" 2>nul | find /I "uv.exe" >nul
if errorlevel 1 (
    REM uv 进程已结束，检查是否成功
    "!UV_CMD!" python find cpython-3.10-windows-x86_64-none >nul 2>&1
    if not errorlevel 1 (
        echo 1 > "!SUCCESS_FLAG!"
    )
    goto :mirror_check
)

REM 进程还在运行，继续等待
set /a "TIMEOUT_COUNT+=1"
if !TIMEOUT_COUNT! GEQ !MIRROR_TIMEOUT! (
    REM 超时，杀掉进程
    taskkill /F /IM uv.exe >nul 2>&1
    goto :mirror_check
)
timeout /t 1 /nobreak >nul
goto :wait_loop

:mirror_check
if exist "!SUCCESS_FLAG!" (
    set "PYTHON_READY=1"
    del "!SUCCESS_FLAG!" 2>nul
    echo   [OK] Python ready via !MIRROR_NAME!
    goto :mirror_done
)

echo   [WARN] !MIRROR_NAME! failed, trying next...
if "!AUTO_RETRY!"=="0" goto :mirror_all_failed
set /a "MIRROR_IDX+=1"
goto :try_mirror

:mirror_all_failed
echo [ERROR] All mirrors failed to download Python 3.10
echo.
echo   Possible solutions:
echo   1. Set UV_MIRROR=direct and use a VPN
echo   2. Set UV_MIRROR=ghfast or UV_MIRROR=ghproxy to specify mirror
echo   3. Manually download Python 3.10 and place it in the uv managed path
echo      Download URL: https://github.com/astral-sh/python-build-standalone/releases
echo   4. Check your network/firewall settings
echo.
pause
exit /b 1

:mirror_done
echo.
REM ==========================================

REM === 启动前检查更新 ===
echo [1.5/4] Checking for updates...
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

!UV_CMD! run --python cpython-3.10-windows-x86_64-none --with-requirements requirements.txt scripts\launchers\start_windows.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo [ERROR] Program exited with code: !errorlevel!
    echo ========================================
    echo.
    pause
)

endlocal
