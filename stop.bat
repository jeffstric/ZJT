@echo off
setlocal enabledelayedexpansion

title ComfyUI Server Stop
color 0C

echo.
echo ========================================
echo   ComfyUI Server Stop
echo ========================================
echo.

tasklist /FI "IMAGENAME eq mysqld.exe" 2>NUL | find /I /N "mysqld.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [INFO] Stopping MySQL service...
    taskkill /F /IM mysqld.exe >NUL 2>&1
    if errorlevel 1 (
        echo [WARN] Failed to stop MySQL
    ) else (
        echo [OK] MySQL stopped
    )
) else (
    echo [INFO] MySQL not running
)

tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I /N "python.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [INFO] Stopping Python application...
    
    for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST ^| find "PID:"') do (
        set PID=%%i
        echo [INFO] Found Python process PID: !PID!
    )
    
    taskkill /F /IM python.exe >NUL 2>&1
    if errorlevel 1 (
        echo [WARN] Failed to stop Python
    ) else (
        echo [OK] Python stopped
    )
) else (
    echo [INFO] Python not running
)

echo.
echo ========================================
echo [OK] All services stopped
echo ========================================
echo.

timeout /t 3 >nul

endlocal
