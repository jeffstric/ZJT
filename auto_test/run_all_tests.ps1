# 自动化测试脚本 - 循环执行所有模块测试
# 每个模块在独立的 Claude 会话中运行，避免上下文溢出

$ProgressFile = "test_progress.json"
$MaxModules = 4

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  视频工作流自动化测试启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

while ($true) {
    # 读取当前进度
    $progress = Get-Content $ProgressFile | ConvertFrom-Json
    $currentIndex = $progress.current_module_index

    if ($currentIndex -ge $MaxModules) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  所有模块测试完成！" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        break
    }

    $currentModule = $progress.modules[$currentIndex]
    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Yellow
    Write-Host "  开始测试模块: $($currentModule.name)" -ForegroundColor Yellow
    Write-Host "  进度: $($currentIndex + 1)/$MaxModules" -ForegroundColor Yellow
    Write-Host "----------------------------------------" -ForegroundColor Yellow
    Write-Host ""

    # 启动 Claude 执行测试（使用 --print 模式自动执行）
    claude --print "/run-test"

    # 检查进度是否更新
    $newProgress = Get-Content $ProgressFile | ConvertFrom-Json
    if ($newProgress.current_module_index -eq $currentIndex) {
        Write-Host "警告: 模块测试未完成，可能遇到问题" -ForegroundColor Red
        Write-Host "请检查后手动运行 /run-test 继续" -ForegroundColor Red
        break
    }

    Write-Host ""
    Write-Host "模块 $($currentModule.name) 测试完成，继续下一模块..." -ForegroundColor Green
    Start-Sleep -Seconds 2
}
