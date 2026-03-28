@echo off
chcp 65001 >/dev/null
setlocal enabledelayedexpansion

echo ========================================
echo   Docker Unit Tests
echo ========================================
echo.

cd /d "%~dp0..\..\docker"

echo [1/4] Cleanup old containers...
docker-compose -f docker-compose-test.yml down -v 2>/dev/null

echo.
echo [2/4] Start test environment...
docker-compose -f docker-compose-test.yml up --build
set TEST_EXIT_CODE=!ERRORLEVEL!

echo.
echo [3/4] Show test logs...
docker logs zjt_test 2>&1 | findstr /C:"test summary" /C:"passed" /C:"failed" /C:"OK" /C:"ERROR"

echo.
if !TEST_EXIT_CODE! equ 0 (
    echo ========================================
    echo   All tests passed!
    echo ========================================
) else (
    echo ========================================
    echo   Tests failed, exit code: !TEST_EXIT_CODE!
    echo ========================================
    docker logs zjt_test 2>&1 | findstr /V "^$" | findstr /E "OK ERROR"
)

echo.
echo [4/4] Cleanup...
docker-compose -f docker-compose-test.yml down -v

echo.
echo ========================================
echo   Done
echo ========================================
pause
exit /b !TEST_EXIT_CODE!
