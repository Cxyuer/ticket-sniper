# 多项目抢票的起停脚本 —— Windows 版（对应 macOS 的 run.sh）
#
#   .\run.ps1 projects              列出 config 里的项目
#   .\run.ps1 start                 启动所有项目的 seat + api
#   .\run.ps1 start <项目>           只启动该项目
#   .\run.ps1 start <项目> seat      只启动该项目的座位监控
#   .\run.ps1 start <项目> api       只启动该项目的接口监控
#   .\run.ps1 stop [项目]            停（不传项目 = 全停）
#   .\run.ps1 status                谁在跑 + 日志多久没更新
#   .\run.ps1 logs [项目]            跟踪日志
#   .\run.ps1 backend               当前浏览器后端
#   .\run.ps1 login [项目]           首次登录（弹一个独立的 Chrome 窗口）
#
# 通道说明：
#   seat   座位图监控 + 分级抢座，走 Playwright 后端（自带 Chrome profile）
#   api    票档接口监控，零依赖，锁屏也活着
#   同程小程序通道（ly_watch.py）依赖 macOS 截图和辅助功能点击，Windows 上不启动
#
# 首次用建议：
#   python -m pip install playwright
#   .\run.ps1 login <项目>        # 登录一次，cookie 存进 profile 目录
#   .\run.ps1 start <项目>
#
# 如果提示「禁止运行脚本」，用这条绕过：
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 start <项目>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# 有 venv 就用 venv 的解释器；Start-Process 需要能拿到的完整路径
$Py = if (Test-Path ".venv\Scripts\python.exe") {
    (Resolve-Path ".venv\Scripts\python.exe").Path
} else {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if (-not $c) { Write-Host "找不到 python，请先装 Python 3.10+ 并加入 PATH"; exit 1 }
    $c.Source
}
$LogDir = Join-Path $env:TEMP "ticket-sniper"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-Projects {
    ((& $Py "maoyan\desktop\api_watch.py" --list) -split "`r?`n") | Where-Object { $_ }
}

function Get-Running([string]$pattern) {
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$pattern*" }
}

function Get-Log([string]$name, [string]$proj) {
    Join-Path $LogDir "ts_${proj}_$name.out"
}

function Start-Seat([string]$proj) {
    if (Get-Running "seat_watch.py --project $proj") { Write-Host "  seat      : 已在跑"; return }

    $code = "import sys;sys.path.insert(0,'.');from common.config import load_project;print(load_project('$proj')['performance_id'])"
    $perf = ((& $Py -c $code) | Out-String).Trim()
    if (-not $perf) { Write-Host "  seat      : 跳过（$proj 没配 performance_id）"; return }

    $tab = ((& $Py "tools\find_tab.py" $perf 2>$null) | Out-String).Trim()
    if (-not $tab) {
        Write-Host "  seat      : 没找到座位页 —— 先在浏览器打开这一页，或用 .\run.ps1 login $proj"
        return
    }

    $log = Get-Log "seat" $proj
    Start-Process -FilePath $Py -WindowStyle Hidden `
        -ArgumentList @("maoyan\desktop\seat_watch.py", "--project", $proj, "--tab", $tab) `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    Write-Host "  seat      : 已启动 tab=$tab → $log"
}

function Start-Api([string]$proj) {
    if (Get-Running "api_watch.py --project $proj") { Write-Host "  api       : 已在跑"; return }

    $log = Get-Log "api" $proj
    Start-Process -FilePath $Py -WindowStyle Hidden `
        -ArgumentList @("maoyan\desktop\api_watch.py", "--project", $proj) `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    Write-Host "  api       : 已启动 → $log"
}

function Stop-Channel([string]$pattern) {
    $procs = Get-Running $pattern
    if (-not $procs) { return $false }
    $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    return $true
}

function Format-Fresh([string]$path, [int]$limit = 180) {
    if (-not (Test-Path $path)) { return "⚪" }
    $age = [int]((Get-Date) - (Get-Item $path).LastWriteTime).TotalSeconds
    if ($age -le $limit) { return "✅" }
    return "⚠️${age}s未更新"
}

$projects = Get-Projects
$cmd = if ($args.Count -ge 1) { $args[0] } else { "status" }
$arg2 = if ($args.Count -ge 2) { $args[1] } else { "" }
$arg3 = if ($args.Count -ge 3) { $args[2] } else { "" }

switch ($cmd) {
    "projects" {
        $projects | ForEach-Object { Write-Host $_ }
    }

    "start" {
        if ($arg2) {
            if ($projects -notcontains $arg2) {
                Write-Host "没有项目「$arg2」，可选: $($projects -join ' ')"
                exit 1
            }
            $targets = @($arg2)
        } else {
            $targets = $projects
        }

        foreach ($proj in $targets) {
            Write-Host "[$proj]"
            if ($arg3 -eq "seat" -or -not $arg3) { Start-Seat $proj }
            if ($arg3 -eq "api" -or -not $arg3) { Start-Api $proj }
        }
    }

    "stop" {
        if ($arg2) {
            if (Stop-Channel "seat_watch.py --project $arg2") { Write-Host "  [$arg2] seat 已停" }
            if (Stop-Channel "api_watch.py --project $arg2") { Write-Host "  [$arg2] api 已停" }
        } else {
            if (Stop-Channel "seat_watch.py") { Write-Host "  seat 已停" }
            if (Stop-Channel "api_watch.py") { Write-Host "  api 已停" }
        }
        exit 0
    }

    "status" {
        foreach ($proj in $projects) {
            $seat = if (Get-Running "seat_watch.py --project $proj") { Format-Fresh (Get-Log "seat" $proj) 240 } else { "⚪" }
            $api = if (Get-Running "api_watch.py --project $proj") { Format-Fresh (Get-Log "api" $proj) 120 } else { "⚪" }
            Write-Host "  [$proj] seat:$seat api:$api"
        }
        Write-Host "  [同程]   ⚪（macOS 专属，Windows 不跑）"
        $b = ((& $Py -c "import sys;sys.path.insert(0,'.');import common.browser as b;print(b.backend_name())") | Out-String).Trim()
        Write-Host "  后端: $b"
    }

    "backend" {
        & $Py -c "import sys;sys.path.insert(0,'.');import common.browser as b;print('后端:',b.backend_name())"
    }

    "login" {
        $proj = if ($arg2) { $arg2 } else { @($projects)[0] }
        & $Py "tools\open_browser.py" --project $proj --login
    }

    "logs" {
        if ($arg2) {
            Get-Content -Path (Get-Log "seat" $arg2), (Get-Log "api" $arg2) -Wait -Tail 30
        } else {
            $files = Get-ChildItem -Path $LogDir -Filter "ts_*.out" | ForEach-Object { $_.FullName }
            if ($files) { Get-Content -Path $files -Wait -Tail 20 }
        }
    }

    default {
        Get-Content -Path $PSCommandPath | Select-Object -First 26 |
            ForEach-Object { $_ -replace '^# ?', '' }
    }
}
