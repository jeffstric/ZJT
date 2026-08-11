@echo off
setlocal enabledelayedexpansion

title ComfyUI Server Stop
color 0C

echo.
echo ========================================
echo   ComfyUI Server Stop
echo ========================================
echo.

REM 使用 Python 脚本读取 PID 文件并停止相关进程
set "SCRIPT_DIR=%~dp0"
set "PYTHON_SCRIPT=%SCRIPT_DIR%scripts\launchers\stop_by_pid.py"
set "UV_CMD=%SCRIPT_DIR%bin\uv\uv.exe"
set "PYTHON_REQUEST=cpython-3.10.20-windows-x86_64-none"
set "UV_PYTHON_INSTALL_DIR=%SCRIPT_DIR%bin\python"
set "UV_PYTHON_DOWNLOADS=never"
set "BUNDLED_PYTHON=%UV_PYTHON_INSTALL_DIR%\%PYTHON_REQUEST%\python.exe"
if "%UV_CACHE_DIR%"=="" set "UV_CACHE_DIR=%SCRIPT_DIR%bin\uv-cache"

if exist "%PYTHON_SCRIPT%" if exist "%UV_CMD%" if exist "%BUNDLED_PYTHON%" (
    "%UV_CMD%" run --no-project --no-python-downloads --python "%BUNDLED_PYTHON%" "%PYTHON_SCRIPT%"
) else (
    echo [ERROR] Safe PID-based stop is unavailable.
    echo [ERROR] Refusing to kill processes by image name because other ZJT/MySQL instances may be running.
    endlocal
    exit /b 1
)

echo.
echo ========================================
echo [OK] All services stopped
echo ========================================
echo.

endlocal
exit /b 0
