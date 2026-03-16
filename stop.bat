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
set PYTHON_SCRIPT=%~dp0scripts\launchers\stop_by_pid.py

if exist "%PYTHON_SCRIPT%" (
    python "%PYTHON_SCRIPT%"
) else (
    echo [INFO] Using directory-based process management

    REM 回退方案：通过目录匹配进程
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

    echo [INFO] Checking for ComfyUI-related Python processes...

    REM Get the absolute path of current directory
    for /f "delims=" %%D in ('cd') do set PROJECT_DIR=%%D

    REM Use PowerShell to find and kill only Python processes related to this project
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$projectDir = '%PROJECT_DIR%'; " ^
        "$projectDir = $projectDir -replace '\\', '\\\\'; " ^
        "try { " ^
        "    $pythonProcesses = Get-WmiObject Win32_Process -Filter \"Name='python.exe'\"; " ^
        "    $killedCount = 0; " ^
        "    foreach ($proc in $pythonProcesses) { " ^
        "        try { " ^
        "            $process = Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue; " ^
        "            if ($process) { " ^
        "                $workingDir = (Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue).StartInfo.WorkingDirectory; " ^
        "                if ($workingDir -and $workingDir.StartsWith($projectDir, [StringComparison]::OrdinalIgnoreCase)) { " ^
        "                    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue; " ^
        "                    $killedCount++; " ^
        "                } " ^
        "            } " ^
        "        } catch { } " ^
        "    } " ^
        "    if ($killedCount -gt 0) { Write-Host \"[OK] Stopped $killedCount Python processes\" } " ^
        "} catch { }" 2>NUL

    echo [INFO] Checking for project-related CMD processes...

    REM Also kill CMD processes that are running start.bat or stop.bat in the project directory
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$projectDir = '%PROJECT_DIR%'; " ^
        "$projectDir = $projectDir -replace '\\', '\\\\'; " ^
        "try { " ^
        "    $cmdProcesses = Get-WmiObject Win32_Process -Filter \"Name='cmd.exe'\"; " ^
        "    $killedCount = 0; " ^
        "    foreach ($proc in $cmdProcesses) { " ^
        "        $cmdLine = if ($proc.CommandLine) { $proc.CommandLine } else { '' }; " ^
        "        if ($cmdLine -and ($cmdLine -like \"*$projectDir*start*\" -or $cmdLine -like \"*$projectDir*stop*\")) { " ^
        "            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue; " ^
        "            $killedCount++; " ^
        "        } " ^
        "    } " ^
        "    if ($killedCount -gt 0) { Write-Host \"[OK] Stopped $killedCount CMD processes\" } " ^
        "} catch { }" 2>NUL
)

echo.
echo ========================================
echo [OK] All services stopped
echo ========================================
echo.

timeout /t 3 >nul

endlocal
