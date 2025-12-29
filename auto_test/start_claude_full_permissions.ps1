# Claude Code Launcher - Full Permissions Mode
# This script starts Claude Code Router and Claude Code, bypassing all permission checks

Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "    Claude Code Launcher - Full Permissions" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Current Directory: $(Get-Location)" -ForegroundColor Yellow
Write-Host "Start Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Yellow
Write-Host ""

# Check if Claude Code Router is installed
Write-Host "Checking Claude Code Router installation..." -ForegroundColor Blue
$ccrCheck = Get-Command ccr -ErrorAction SilentlyContinue
if ($ccrCheck) {
    Write-Host "✓ Claude Code Router is installed" -ForegroundColor Green
} else {
    Write-Host "✗ Claude Code Router (ccr) not found or not properly installed" -ForegroundColor Red
    Write-Host "Please install Claude Code Router before running this script" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Starting Claude Code via Claude Code Router..." -ForegroundColor Green
Write-Host "Permissions: All permission checks bypassed" -ForegroundColor Yellow
Write-Host ""

# Start Claude Code via Claude Code Router with all permission parameters
ccr code --dangerously-skip-permissions --permission-mode bypassPermissions
