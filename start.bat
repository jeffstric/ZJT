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

echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo [OK] %PYTHON_VERSION%
echo.

echo [2/5] Checking uv package manager...
where uv >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing uv...
    
    python -m pip install uv
    
    if errorlevel 1 (
        echo [ERROR] Failed to install uv
        echo.
        pause
        exit /b 1
    )
    
    echo [OK] uv installed
) else (
    echo [OK] uv found
)
echo.

echo [3/5] Checking config file...
if not exist "config_%comfyui_env%.yml" (
    echo [INFO] Config file not found, will be auto-created from config.example.yml
) else (
    echo [OK] config_%comfyui_env%.yml found
)
echo.

echo [4/5] Checking MySQL...
if not exist "bin\mysql" (
    echo [ERROR] MySQL directory not found: bin\mysql
    echo Please deploy MySQL to bin\mysql directory
    echo.
    pause
    exit /b 1
)
echo [OK] MySQL directory found
echo.

echo [5/5] Starting services...
echo ========================================
echo.

uv run --with-requirements requirements.txt start_windows.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo [ERROR] Program exited with code: %errorlevel%
    echo ========================================
    echo.
    pause
)

endlocal
