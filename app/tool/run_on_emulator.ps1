#!/usr/bin/env pwsh
<#
.SYNOPSIS
    在 Android 模拟器上跑 App 并连本机后端（用 adb reverse，无需改防火墙）。

.DESCRIPTION
    ## 为什么需要这个脚本

    安卓模拟器访问宿主机有两种方式，本机只有一种可用：

      1. `10.0.2.2`（模拟器的宿主机别名）—— **本机走不通**。
         实测：模拟器能 ping 通 8.8.8.8，但 `10.0.2.2:<port>` 连不上；
         在宿主机开临时监听确认过，**只收到 127.0.0.1 的连接，没有来自模拟器的**。
         原因是 Windows 防火墙入站默认阻止，而 uvicorn 没有对应的放行规则。
      2. `adb reverse tcp:8000 tcp:8000` —— **可用**。
         把模拟器的 `127.0.0.1:8000` 反向转发到宿主机的 8000，
         流量走 adb 通道、不过防火墙。因此 App 用 `KB_BASE_URL=http://127.0.0.1:8000`。

    ## 用法

        # 1) 先起后端（另开一个终端）
        cd backend
        python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

        # 2) 再跑这个脚本
        pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/run_on_emulator.ps1'"

    ## 注意

    - 拉起模拟器后 `adb reverse` 会在**模拟器重启后失效**，需要重跑本脚本。
    - 只影响当前这台模拟器与当前这次连接，不改动系统代理或防火墙。

.PARAMETER Avd
    AVD 名称，默认 `rehab_pixel8`。

.PARAMETER BackendPort
    后端端口，默认 8000。

.PARAMETER SkipBoot
    不启动模拟器（已在运行），只做反向转发与 `flutter run`。

.PARAMETER Release
    用 release 模式（默认 debug，便于热重载与看日志）。
#>
[CmdletBinding()]
param(
    [string]$Avd = 'rehab_pixel8',
    [int]$BackendPort = 8000,
    [switch]$SkipBoot,
    [switch]$Release
)

$ErrorActionPreference = 'Stop'

$sdk = @('D:\Android\sdk', "$env:LOCALAPPDATA\Android\Sdk") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sdk) { throw '找不到 Android SDK' }

$adb = Join-Path $sdk 'platform-tools\adb.exe'
$emulator = Join-Path $sdk 'emulator\emulator.exe'
if (-not (Test-Path $adb)) { throw "找不到 adb：$adb" }

function Get-Devices {
    (& $adb devices) | Select-Object -Skip 1 | Where-Object { $_ -match '\tdevice$' }
}

# --------------------------------------------------------------------------- #
# 1) 模拟器
# --------------------------------------------------------------------------- #
if (-not (Get-Devices)) {
    if ($SkipBoot) { throw '没有已连接的设备，且指定了 -SkipBoot' }
    Write-Host "[emulator] 启动 $Avd …" -ForegroundColor Cyan
    Start-Process -FilePath $emulator `
        -ArgumentList @('-avd', $Avd, '-no-snapshot-load', '-gpu', 'swiftshader_indirect', '-no-boot-anim') `
        | Out-Null

    Write-Host '[emulator] 等待设备上线（最多 180s）…' -ForegroundColor DarkGray
    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Date) -lt $deadline) {
        if (Get-Devices) { break }
        Start-Sleep -Seconds 5
    }
    if (-not (Get-Devices)) { throw '模拟器未在 180s 内上线' }
    # 系统还没起完时 flutter run 会失败，等 boot_completed。
    & $adb wait-for-device | Out-Null
    while (((& $adb shell getprop sys.boot_completed) -join '').Trim() -ne '1') {
        Start-Sleep -Seconds 3
    }
    Write-Host '[emulator] 已就绪' -ForegroundColor Green
} else {
    Write-Host "[emulator] 复用已连接设备：$((Get-Devices) -join ', ')" -ForegroundColor Green
}

$device = ((Get-Devices) | Select-Object -First 1) -replace '\s.*$', ''

# --------------------------------------------------------------------------- #
# 2) 反向端口转发（关键：绕开防火墙）
# --------------------------------------------------------------------------- #
Write-Host "[adb] reverse tcp:$BackendPort -> tcp:$BackendPort" -ForegroundColor Cyan
& $adb -s $device reverse "tcp:$BackendPort" "tcp:$BackendPort" | Out-Null
& $adb -s $device reverse --list

# 顺带确认后端真的在监听（本机侧探测即可）。
try {
    $health = Invoke-RestMethod "http://127.0.0.1:$BackendPort/api/v1/health" -TimeoutSec 5
    Write-Host "[backend] 可达，status=$($health.status)" -ForegroundColor Green
} catch {
    Write-Warning @"
本机 $BackendPort 端口不可达 —— 后端还没起？
  cd backend
  python -m uvicorn app.main:app --host 0.0.0.0 --port $BackendPort
"@
}

# --------------------------------------------------------------------------- #
# 3) 跑 App
# --------------------------------------------------------------------------- #
$mode = if ($Release) { '--release' } else { '--debug' }
$baseUrl = "http://127.0.0.1:$BackendPort"
Write-Host "[flutter] run $mode -d $device --dart-define=KB_BASE_URL=$baseUrl" -ForegroundColor Cyan
Write-Host '（首次会构建并安装，约 1–2 分钟）' -ForegroundColor DarkGray

Push-Location (Join-Path $PSScriptRoot '..')
try {
    flutter run -d $device $mode "--dart-define=KB_BASE_URL=$baseUrl"
} finally {
    Pop-Location
}
