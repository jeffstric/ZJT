@echo off
chcp 65001 >nul
echo ========================================
echo   Docker 单元测试
echo ========================================
echo.

cd /d "%~dp0..\..\docker"

echo [1/3] 启动测试环境...
docker-compose -f docker-compose-test.yml up -d

echo.
echo [2/3] 等待测试完成并获取日志...
docker-compose -f docker-compose-test.yml logs --tail=200

echo.
echo [3/3] 清理测试环境...
docker-compose -f docker-compose-test.yml down -v

echo.
echo ========================================
echo   测试完成
echo ========================================
pause
