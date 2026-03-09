@echo off
setlocal enabledelayedexpansion

title ComfyUI Server Startup
color 0A

REM 设置 UTF-8 编码，解决中文路径和文件编码问题
set PYTHONUTF8=1
chcp 65001 >nul 2>&1

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
echo.

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

!UV_CMD! run --python cpython-3.12-windows-x86_64-none --with-requirements requirements.txt start_windows.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo [ERROR] Program exited with code: %errorlevel%
    echo ========================================
    echo.
    pause
)

endlocal
