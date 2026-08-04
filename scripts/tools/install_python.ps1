#Requires -Version 3.0
<#
.SYNOPSIS
    安装 uv 托管的 CPython（多镜像自动回退），供 start.bat 调用。

.DESCRIPTION
    关键点：下载进程按 PID 精确跟踪与终止。
    托盘链路（点我启动.bat）中存在长期存活的外层 uv.exe（detached uv run 是
    托盘 python 的父进程），任何按进程名的 tasklist/taskkill 都会误等、误杀它。
    本脚本使用 Start-Process -PassThru 拿到精确 PID，Wait-Process -Timeout 等待，
    超时仅 taskkill /T /PID 终止该进程树，不触碰任何其他 uv 进程。
    不读取 stdin，可在无控制台（托盘隐藏）环境下正常工作。

.PARAMETER UvCmd
    uv 可执行文件路径（通常为 bin uv uv.exe）。

.PARAMETER Request
    uv python 请求串，默认 cpython-3.10-windows-x86_64-none。

.PARAMETER StartMirrorIdx
    起始镜像索引（0=ghfast 1=ghproxy 2=gh-proxy 3=moeyy 4=direct）。

.PARAMETER NoFallback
    用户手动指定镜像时传入：只试起始镜像，不自动回退。

.PARAMETER LogFile
    日志文件路径。每轮启动重建（不无限增长），每条尝试记录镜像名/时间/结果/退出码。

.PARAMETER TimeoutOverrideSec
    >0 时覆盖所有镜像的超时秒数（供自动化测试注入）。

.PARAMETER MirrorUrlOverride
    非空时镜像表收缩为单个该 URL 的镜像（供自动化测试注入，如黑洞地址）。
#>
param(
    [Parameter(Mandatory = $true)][string]$UvCmd,
    [string]$Request = "cpython-3.10.20-windows-x86_64-none",
    [int]$StartMirrorIdx = 0,
    [switch]$NoFallback,
    [string]$LogFile = "",
    [int]$TimeoutOverrideSec = 0,
    [string]$MirrorUrlOverride = ""
)

$ErrorActionPreference = "Continue"

$Mirrors = @(
    @{ Name = "ghfast";   Url = "https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download";        TimeoutSec = 80 },
    @{ Name = "ghproxy";  Url = "https://ghproxy.cn/https://github.com/astral-sh/python-build-standalone/releases/download";        TimeoutSec = 80 },
    @{ Name = "gh-proxy"; Url = "https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download";      TimeoutSec = 80 },
    @{ Name = "moeyy";    Url = "https://github.moeyy.xyz/https://github.com/astral-sh/python-build-standalone/releases/download";  TimeoutSec = 80 },
    @{ Name = "direct";   Url = "";                                                                                                 TimeoutSec = 120 }
)
if ($MirrorUrlOverride) {
    $overrideTimeout = if ($TimeoutOverrideSec -gt 0) { $TimeoutOverrideSec } else { 80 }
    $Mirrors = @(@{ Name = "override"; Url = $MirrorUrlOverride; TimeoutSec = $overrideTimeout })
    $StartMirrorIdx = 0
}

if ($LogFile) {
    $logDir = Split-Path -Parent $LogFile
    if ($logDir -and -not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    Set-Content -Path $LogFile -Value "=== ZJT python install log, started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" -Encoding UTF8
}

function Write-InstallLog([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    if ($script:LogFile) {
        Add-Content -Path $script:LogFile -Value $line -Encoding UTF8
    }
}

function Test-PythonReady {
    & $UvCmd python find --managed-python $Request *> $null
    return ($LASTEXITCODE -eq 0)
}

# 前置短路：已安装则直接成功，不进入下载流程
Write-InstallLog "Checking if $Request is already installed..."
if (Test-PythonReady) {
    Write-InstallLog "short-circuit: $Request already installed, skip download"
    exit 0
}

$exitCode = 1
for ($i = $StartMirrorIdx; $i -lt $Mirrors.Count; $i++) {
    $m = $Mirrors[$i]
    $mirrorName = [string]$m.Name
    $mirrorUrl = [string]$m.Url
    $timeoutSec = if ($TimeoutOverrideSec -gt 0) { $TimeoutOverrideSec } else { [int]$m.TimeoutSec }

    $uvArgs = @("python", "install", $Request)
    if ($mirrorUrl) { $uvArgs += @("--mirror", $mirrorUrl) }

    $tag = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $tmpOut = Join-Path $env:TEMP "zjt_pyinst_${tag}_out.log"
    $tmpErr = Join-Path $env:TEMP "zjt_pyinst_${tag}_err.log"

    Write-InstallLog ("Trying mirror {0} ({1}/{2}), timeout {3}s ..." -f $mirrorName, ($i + 1), $Mirrors.Count, $timeoutSec)

    $proc = $null
    try {
        $proc = Start-Process -PassThru -WindowStyle Hidden -FilePath $UvCmd `
            -ArgumentList $uvArgs -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
    }
    catch {
        Write-InstallLog "Failed to start uv: $($_.Exception.Message)"
    }

    if ($proc) {
        try {
            Wait-Process -Id $proc.Id -Timeout $timeoutSec -ErrorAction SilentlyContinue
            $proc.Refresh()
            if (-not $proc.HasExited) {
                # 只终止本次下载进程树（精确 PID），不碰外层托盘常驻的 uv.exe
                Write-InstallLog "Mirror $mirrorName timed out after ${timeoutSec}s, killing pid $($proc.Id) tree..."
                & taskkill.exe /F /T /PID $proc.Id 2>&1 | Out-Null
                $proc.WaitForExit()
            }
            $proc.Refresh()
            if ($proc.ExitCode -eq 0) {
                # 仅下载进程退出码为 0 时才终验，避免"超时但碰巧有旧 Python"误判成功
                Write-InstallLog "Mirror ${mirrorName}: uv exited 0, verifying..."
                if (Test-PythonReady) {
                    Write-InstallLog "SUCCESS via $mirrorName"
                    $exitCode = 0
                }
                else {
                    Write-InstallLog "Mirror ${mirrorName}: uv exited 0 but 'python find' failed"
                }
            }
            else {
                Write-InstallLog "Mirror $mirrorName failed, uv exit code $($proc.ExitCode)"
            }
        }
        finally {
            foreach ($tmp in @($tmpOut, $tmpErr)) {
                try {
                    if ((Test-Path $tmp) -and $LogFile) {
                        Add-Content -Path $LogFile -Value "----- uv output ($([IO.Path]::GetFileName($tmp))) -----" -Encoding UTF8
                        Get-Content -Path $tmp -Encoding UTF8 | Add-Content -Path $LogFile -Encoding UTF8
                    }
                }
                catch { }
                Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            }
        }
    }

    if ($exitCode -eq 0) { break }
    if ($NoFallback) {
        Write-InstallLog "NoFallback set, stop after mirror $mirrorName"
        break
    }
}

if ($exitCode -eq 0) {
    Write-InstallLog "Python $Request is ready."
}
else {
    Write-InstallLog "All mirrors failed to install $Request"
}
exit $exitCode
