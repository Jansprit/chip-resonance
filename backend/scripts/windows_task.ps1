# scripts/windows_task.ps1 — Windows Task Scheduler 觸發腳本
#
# 用法（以系統管理員身份執行 PowerShell）：
#   # 註冊兩個排程
#   .\backend\scripts\windows_task.ps1 -Register
#
#   # 手動觸發一次完整 pipeline
#   .\backend\scripts\windows_task.ps1 -RunNow -Source all
#
#   # 移除排程
#   .\backend\scripts\windows_task.ps1 -Unregister
#
# 排程內容：
#   - 週一至五 13:35  → public subset（TWSE + TPEx + FinMind + MOPS）
#   - 週五 14:35      → all（完整 pipeline，含 Playwright 源）

[CmdletBinding()]
param(
    [switch]$Register,
    [switch]$Unregister,
    [switch]$RunNow,
    [ValidateSet('all', 'public', 'private', 'twse', 'tpex', 'finmind', 'mops', 'tdcc', 'pyramid', 'goodinfo')]
    [string]$Source = 'all'
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$PythonCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonCmd) {
    $PythonCmd = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}
if (-not $PythonCmd) {
    Write-Error "Python not found in PATH"
    exit 1
}

$TaskNamePublic = "Chip-Resonance Pipeline (Public)"
$TaskNameFull   = "Chip-Resonance Pipeline (Full)"

function Run-Pipeline {
    param([string]$SourceArg)
    Set-Location -LiteralPath $RepoRoot
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Running pipeline with --source $SourceArg"
    & $PythonCmd -m backend.scripts.run_local --source $SourceArg
}

if ($Register) {
    Write-Host "Registering Windows Task Scheduler entries..."
    $PublicCmd = "-NoProfile -ExecutionPolicy Bypass -Command `"Set-Location -LiteralPath '$RepoRoot'; & '$PythonCmd' -m backend.scripts.run_local --source public`""
    $FullCmd   = "-NoProfile -ExecutionPolicy Bypass -Command `"Set-Location -LiteralPath '$RepoRoot'; & '$PythonCmd' -m backend.scripts.run_local --source all`"`

    # 週一到週五 13:35 跑 public
    $ActionPublic = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $PublicCmd
    $TriggerPublic = New-ScheduledTaskTrigger -Daily -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "13:35"
    Register-ScheduledTask -TaskName $TaskNamePublic -Action $ActionPublic -Trigger $TriggerPublic -Description "Daily public subset scraper (TWSE+TPEx+FinMind+MOPS)" -RunLevel Highest

    # 週五 14:35 跑 full（含 Playwright 源）
    $ActionFull = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $FullCmd
    $TriggerFull = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "14:35"
    Register-ScheduledTask -TaskName $TaskNameFull -Action $ActionFull -Trigger $TriggerFull -Description "Friday full pipeline (incl. Pyramid/Goodinfo/TDCC)" -RunLevel Highest

    Write-Host "Done. Check 'Task Scheduler Library' for tasks:"
    Write-Host "  - $TaskNamePublic"
    Write-Host "  - $TaskNameFull"
    exit 0
}

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskNamePublic -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskNameFull   -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled tasks."
    exit 0
}

if ($RunNow) {
    Run-Pipeline -SourceArg $Source
    exit 0
}

# Default: show usage
Write-Host @"
Usage:
    .\backend\scripts\windows_task.ps1 -Register          # 註冊兩個排程
    .\backend\scripts\windows_task.ps1 -Unregister        # 移除排程
    .\backend\scripts\windows_task.ps1 -RunNow -Source all # 立即跑一次

Current schedule:
    - 週一到週五 13:35: public subset (TWSE+TPEx+FinMind+MOPS)
    - 週五 14:35: full pipeline (含 Playwright 源)
"@