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
#   - 週一至五 13:35  → public subset（TWSE + TPEx + Yahoo + FinMind + MOPS + 集保）
#   - 週五 14:35      → all（完整 pipeline，含 Playwright 源）
#
# 兩者都會在 pipeline 之後接續跑：
#   1. build_universe.py  → 合併真實來源（帶 provenance）
#   2. emit_factors.js    → 產生 point-in-time 因子庫（唯一因子實作在 data.js）
#   3. run_backtest.py    → 產生回測報告（樣本不足會自報不足）

[CmdletBinding()]
param(
    [switch]$Register,
    [switch]$Unregister,
    [switch]$RunNow,
    [ValidateSet('all', 'public', 'private', 'twse', 'tpex', 'finmind', 'mops', 'tdcc', 'yahoo_price', 'wantgoo_price', 'pyramid', 'goodinfo')]
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

# 因子庫必須由 Node 產生（data.js 是唯一的因子實作，不可改用 Python 重寫）
$NodeCmd = (Get-Command node -ErrorAction SilentlyContinue).Source

function Invoke-Step {
    param([string]$Label, [scriptblock]$Action)
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Label"
    try {
        & $Action
    } catch {
        # 單一步驟失敗不應該讓整條排程中斷（後面的步驟仍然有價值）
        Write-Warning "$Label 失敗：$_"
    }
}

function Run-Pipeline {
    param([string]$SourceArg)
    Set-Location -LiteralPath $RepoRoot

    Invoke-Step "Running pipeline with --source $SourceArg" {
        & $PythonCmd -m backend.scripts.run_local --source $SourceArg
    }
    Invoke-Step "Merging real sources (build_universe)" {
        & $PythonCmd backend/scripts/build_universe.py
    }
    if ($NodeCmd) {
        Invoke-Step "Emitting point-in-time factor database" {
            & $NodeCmd backend/scripts/emit_factors.js
        }
    } else {
        Write-Warning "找不到 node，跳過因子庫發佈（回測會因此沒有 point-in-time 資料）"
    }
    Invoke-Step "Generating backtest report" {
        & $PythonCmd -m backend.scripts.run_backtest --weeks 4
    }
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