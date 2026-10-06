<#
.SYNOPSIS
    一键启动 / 停止 康复科治疗过程记录系统（后端 API + 管理后台前端）。

.DESCRIPTION
    做的事：
      1. 校验 Python / Node 环境，首次运行时自动建库、导种子、创建管理员；
      2. 起后端 uvicorn（默认 8000）；
      3. 起管理后台 Vite dev（默认 5173，已配置 /api 代理）；
      4. 在命令行窗口里打印登录地址与**管理员账号密码**；
      5. 自动打开浏览器并停在登录页。

.PARAMETER Action
    start（默认）/ stop / restart / status / clean

.PARAMETER IncludeData
    仅与 `clean` 配合：连开发数据库 `data\kf.db` 一起删除
    （下次启动会自动重建并导种子）。默认**保留**数据库。

.PARAMETER NoBrowser
    不自动打开浏览器（服务器上跑或只想看日志时用）。

.PARAMETER BackendPort / FrontendPort
    端口，默认 8000 / 5173。

.EXAMPLE
    .\start.ps1                 # 启动并打开浏览器（只绑本机）
    .\start.ps1 -Lan            # 额外让**内网其它客户端**访问（IPv4，放行防火墙）
    .\start.ps1 -NoBrowser      # 只启动
    .\start.ps1 stop            # 停止（含看门狗）
    .\start.ps1 status          # 看状态

.NOTES
    首次运行若提示脚本被禁止执行，用其中任一种方式：
      powershell -ExecutionPolicy Bypass -File .\start.ps1
      Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

    `-Lan` 会把后端绑到 `0.0.0.0` 并放行防火墙入站端口（这一步可能需要
    **管理员**权限；没有权限时脚本会打印要手动执行的命令）。
    只监听 **IPv4**，不监听 IPv6。
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'clean')]
    [string]$Action = 'start',

    [switch]$NoBrowser,
    # ★ 只绑本机回环，还是会**一并给内网其它客户端**用（2026-10-06）。
    #
    # 默认**不开**：把服务开到局域网上应该是一个显式选择，不该是"悄悄发生"的
    # —— 这个后台没有 TLS、也没有额外的访问控制，能连上就能用。
    #
    # 加了它之后：后端绑 `0.0.0.0`（IPv4 全接口），内网其它机器可以用
    # `http://<本机IPv4>:5173` 访问管理后台（Vite 会把 `/api` 反代到本机后端）。
    # 只用 IPv4、**不监听 IPv6**。
    [switch]$Lan,
    # 仅与 clean 配合：连开发数据库一起删
    [switch]$IncludeData,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,

    # 管理员账号：默认 A001 / 科室管理员。
    # 密码首次运行会随机生成并写入 .dev-admin-password.txt（已 gitignore），
    # 之后每次启动都读同一个文件 —— 这样"每次启动都重置密码"不会把上次的密码弄失效。
    [string]$AdminEmployeeNo = 'A001',
    [string]$AdminName = '科室管理员',
    [string]$AdminPassword
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# --------------------------------------------------------------------------- #
# 路径与常量
# --------------------------------------------------------------------------- #
$Root        = $PSScriptRoot
$BackendDir  = Join-Path $Root 'backend'
$AdminDir    = Join-Path $Root 'admin'
$DataDir     = Join-Path $BackendDir 'data'
$RunDir      = Join-Path $Root '.run'                       # 进程信息（已 gitignore）
$StateFile   = Join-Path $RunDir 'state.json'
$PwdFile     = Join-Path $Root '.dev-admin-password.txt'    # 已 gitignore
$LogDir      = Join-Path $Root '.run\logs'

$BackendUrl  = "http://127.0.0.1:$BackendPort"
$FrontendUrl = "http://localhost:$FrontendPort"
$LoginUrl    = "$FrontendUrl/login"

# 设备无关的 IPv4 网卡地址（内网客户端用这个访问）。
# 排除 169.254.*（APIPA，没拿到 DHCP 时的自分配地址，连不通）。
function Get-LanIPv4 {
    try {
        $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress
        return @($ips)
    } catch {
        return @()
    }
}
# `-Lan` 时后端绑 0.0.0.0；否则只绑回环。
$BackendHost = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }

function Write-Head([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 68) -ForegroundColor DarkCyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ('=' * 68) -ForegroundColor DarkCyan
}
function Write-Step([string]$Text) { Write-Host "  > $Text" -ForegroundColor Gray }
function Write-Ok([string]$Text)   { Write-Host "  [OK]   $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "  [警告] $Text" -ForegroundColor Yellow }
function Write-Err([string]$Text)  { Write-Host "  [错误] $Text" -ForegroundColor Red }

function Test-PortBusy([int]$Port) {
    # 同时查 IPv4/IPv6：Vite 默认监听 ::1，只看 127.0.0.1 会漏判
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$conns
}

function Get-PortOwner([int]$Port) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return @() }
    return @($conns | Select-Object -ExpandProperty OwningProcess -Unique)
}

# --------------------------------------------------------------------------- #
# 找 Python 解释器
#
# 这个项目踩过一次坑：用错解释器（DSH 自带的 3.12，没有第三方库）会误判成
# "依赖装不上"。所以这里把"用哪个 Python"显式化并有记录可查。
# --------------------------------------------------------------------------- #
function Resolve-Python {
    $candidates = New-Object System.Collections.Generic.List[string]

    if ($env:KB_PYTHON) { $candidates.Add($env:KB_PYTHON) }

    $cfg = Join-Path $Root '.python-path'
    if (Test-Path $cfg) {
        $line = (Get-Content $cfg -First 1).Trim()
        if ($line) { $candidates.Add($line) }
    }

    $candidates.Add("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe")
    $candidates.Add("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")

    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }

    # 退回到 PATH 上的 py / python（需能 import fastapi）
    foreach ($name in 'python', 'py') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            $p = $cmd.Source
            $probe = & $p -c "import fastapi, uvicorn; print('ok')" 2>$null
            if ($probe -eq 'ok') { return $p }
        }
    }
    return $null
}

function Resolve-Node {
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm  = Get-Command npm  -ErrorAction SilentlyContinue
    if (-not $node -or -not $npm) { return $null }
    return @{ Node = $node.Source; Npm = $npm.Source }
}

# --------------------------------------------------------------------------- #
# 管理员密码
# --------------------------------------------------------------------------- #
function Get-AdminPassword {
    if ($AdminPassword) { return $AdminPassword }
    if ($env:KB_ADMIN_PASSWORD) { return $env:KB_ADMIN_PASSWORD }

    if (Test-Path $PwdFile) {
        # .Trim() 会去掉 BOM 之外的空白，但 BOM 在 PS 5.1 的 Get-Content 下
        # 通常已被剥掉；为稳妥仍显式去掉 U+FEFF（早期版本用 Set-Content 写出过带 BOM 的文件，
        # 而 Python 侧 read_text 会把 BOM 读成字符串首字符，导致密码"多一个不可见字符"）。
        $saved = (Get-Content $PwdFile -First 1).Trim().TrimStart([char]0xFEFF)
        if ($saved) { return $saved }
    }

    # 随机生成：只用一个对 shell/JSON 都安全的字符集，避免转义问题。
    # 长度 16，含大小写与数字（不含容易看错的 0/O/1/l/I）。
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $bytes = New-Object byte[] 16
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $chars = for ($i = 0; $i -lt 16; $i++) { $alphabet[$bytes[$i] % $alphabet.Length] }
    return ($chars -join '')
}

<#
    把密码写进文件（**必须是 UTF-8 无 BOM**）。

    坑：PowerShell 5.1 的 `Set-Content -Encoding utf8` 会写入 BOM（EF BB BF）。
    这个文件随后会被 Python 读（`Path.read_text(encoding='utf-8')`），
    BOM 会变成一个真实的字符串首字符 U+FEFF，于是密码从 16 位变 17 位，
    用它登录后端会返回 403 —— 而命令行里 `Get-Content` 会剥掉 BOM，
    所以"脚本自己读没问题、Python 读就有问题"，极难定位（实测踩到过）。
    这里改用 .NET 的 UTF8Encoding($false) 明确不写 BOM。
#>
function Save-AdminPassword {
    param([string]$Password)
    [System.IO.File]::WriteAllText($PwdFile, $Password, (New-Object System.Text.UTF8Encoding($false)))
}

# --------------------------------------------------------------------------- #
# 调用外部命令（python / npm 等）
#
# 为什么要包一层：PowerShell 在 $ErrorActionPreference='Stop' 时，会把原生命令写到
# **stderr 的任何一行**当成终止性错误 —— 而这个 CLI 会把"仍在使用开发用 JWT 默认密钥"
# 这类**告警**写到 stderr。结果就是：命令其实成功了，脚本却中断（实测踩到过）。
# 另外 $LASTEXITCODE 在脚本块/函数外读取并不可靠，必须在命令结束的那一刻就取走。
#
# 因此这里统一：把 stderr 合成普通字符串、立刻取退出码、由调用方按退出码判断成败。
# --------------------------------------------------------------------------- #
function Invoke-NativeCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $WorkingDirectory
    try {
        $lines = & $FilePath @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $prev
    }
    return [pscustomobject]@{ ExitCode = $code; Output = @($lines) }
}

function Invoke-BackendCli {
    param([string]$Python, [string[]]$CliArgs)
    return Invoke-NativeCommand -FilePath $Python `
        -Arguments (@('-m', 'app.cli') + $CliArgs) -WorkingDirectory $BackendDir
}

<#
    数据库初始化。

    注意：默认库路径是**仓库根目录**的 `data/kf.db`
    （`config.py` 里 `REPO_ROOT = parents[3]`，即 `backend/app/core/config.py` 上溯三层）。

    `init`（建库+迁移）与 `seed`（导种子）是**两件事**，必须分开判断：
    早先这里用"库文件是否存在"来决定要不要导种子，于是**库存在但为空**时会跳过种子
    —— 表现为字典/选项集/模板/患者反应各页全空，而脚本一声不响（实测踩到过：
    手动跑过 init、或首次 seed 中途失败，都会留下这种空库）。
    所以这里**直接查库**判断是否已导过种子，`seed` 本身是幂等的，重复跑没有副作用。
#>
function Initialize-Data {
    param([string]$Python)

    # 用"字典主项目是否有数据"作为"是否导过种子"的判据：
    # 主项目是字典的根，选项集/模板/患者反应都挂在它下面，它为空说明种子没进去。
    #
    # 这里不去猜库文件在哪：默认是**仓库根目录的 `data/kf.db`**
    # （`config.py` 里 `REPO_ROOT = parents[3]`），但也可能被 `KB_DB_PATH` 覆盖。
    # 直接问"库里的表"才是唯一可靠的判据。
    # 注意两个坑（都踩过）：
    #   1. `@'...'@` 是**字面** here-string，里面的 `%` 不会折叠，所以
    #      `print("...%%d" %% count)` 生成出来是非法 Python（SyntaxError）；
    #   2. 用 `-f` 插入路径时，Python 代码里的 `{count}` 会被 PowerShell 当成
    #      格式化占位符，抛 "Input string was not in a correct format"。
    # 因此下面用 f-string 写 Python、并靠 `.Replace()` 插入路径，两个坑一起避开。
    $probe = @'
import sys
sys.path.insert(0, r"__BACKEND_DIR__")
from app.core.config import get_settings
from app.db import storage

# 输出带前缀的一行：stdout/stderr 是合并收集的，靠"取最后一行"解析容易取到告警而失败。
try:
    conn = storage.connect(get_settings(), read_only=True)
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM main_item").fetchone()[0])
    finally:
        conn.close()
    print(f"KB_MAIN_ITEM_COUNT={count}")
except Exception as exc:
    print(f"KB_PROBE_ERROR={type(exc).__name__}: {exc}")
'@
    $probe = $probe.Replace('__BACKEND_DIR__', $BackendDir)

    if (-not (Test-Path $RunDir)) { New-Item -ItemType Directory -Path $RunDir -Force | Out-Null }
    $probeFile = Join-Path $RunDir '_probe_seed.py'
    [System.IO.File]::WriteAllText($probeFile, $probe, (New-Object System.Text.UTF8Encoding($false)))
    $probeResult = Invoke-NativeCommand -FilePath $Python -Arguments @($probeFile) -WorkingDirectory $BackendDir
    Remove-Item $probeFile -Force -ErrorAction SilentlyContinue

    # 按**前缀**找结果，不依赖行序
    $mainItemCount = -1
    foreach ($line in $probeResult.Output) {
        $text = "$line"
        if ($text -match 'KB_MAIN_ITEM_COUNT=(\d+)') {
            $mainItemCount = [int]$Matches[1]
        } elseif ($text -match 'KB_PROBE_ERROR=(.+)') {
            Write-Host "        种子探测未成功：$($Matches[1])" -ForegroundColor DarkGray
        }
    }
    $isFirstRun = $mainItemCount -lt 0

    if ($isFirstRun) {
        Write-Step '首次运行：建库并应用迁移…'
    } else {
        Write-Step '检查数据库迁移…'
    }
    $r = Invoke-BackendCli -Python $Python -CliArgs @('init')
    if ($r.ExitCode -ne 0) {
        $r.Output | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
        throw '建库/迁移失败，请查看上方输出'
    }

    if ($mainItemCount -eq 0) {
        Write-Step '检测到字典为空：导入种子数据（字典 / 反应定义 / 选项集 / 四大高频模板）…'
        $r = Invoke-BackendCli -Python $Python -CliArgs @('seed')
        if ($r.ExitCode -ne 0) {
            $r.Output | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
            throw '种子导入失败，请查看上方输出'
        }
        Write-Ok '种子数据已导入'
    } elseif ($mainItemCount -gt 0) {
        Write-Ok "种子数据已存在（字典主项目 $mainItemCount 项），跳过导入"
    } else {
        # 探测异常（既不是"空"也不是"有"）：不阻断启动，种子可用 CLI 手动补。
        Write-Warn '无法确认种子是否已导入；如页面数据为空，请手动执行：python -m app.cli seed'
    }
}

function Ensure-Admin {
    param([string]$Python, [string]$Password)

    $env:KB_ADMIN_PASSWORD = $Password
    Write-Step "配置管理员账号 $AdminEmployeeNo（已存在则重置密码为下面展示的值）…"
    $r = Invoke-BackendCli -Python $Python `
        -CliArgs @('create-admin', $AdminEmployeeNo, '--name', $AdminName)

    # 退出码为 0 即成功；stderr 上的"开发用默认密钥"告警不算失败，但展示出来让人知道
    foreach ($line in $r.Output) {
        if ($line -match '提醒|警告|warning') {
            Write-Host "        $line" -ForegroundColor DarkYellow
        }
    }
    if ($r.ExitCode -ne 0) {
        $r.Output | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
        throw '创建管理员失败，请查看上方输出'
    }
    # 把密码落盘，保证下次启动展示的是同一个密码（否则每次启动旧密码都会失效）。
    # 必须无 BOM —— 见 Save-AdminPassword 的注释（带 BOM 会让 Python 读出的密码多一个字符）。
    Save-AdminPassword -Password $Password

    # 密码可用性的自校验放在**起完服务之后**做（见 Invoke-Start 里的 Test-AdminLogin）：
    # 本函数在启动后端之前调用，此时接口还不可达，这里验了也只能是"跳过"，
    # 徒增一次误导性的输出。
    return ($r.Output -join "`n")
}

<#
    用指定密码调一次登录接口，确认密码真的可用。

    只在**后端已经起来之后**调用（`Invoke-Start` 里 `Wait-HttpOk` 之后）。
    若健康检查不通（例如后端刚崩了），返回"跳过"而不是失败 —— 那种情况
    已经由"后端未就绪"的错误分支覆盖，不该在这里重复报错。
#>
function Test-AdminLogin {
    param([string]$Password)

    try {
        $null = Invoke-WebRequest -Uri "$BackendUrl/api/v1/health" -UseBasicParsing -TimeoutSec 3
    } catch {
        return [pscustomobject]@{ Ok = $true; Status = 'skipped(服务未启动)' }
    }

    $body = @{ employee_no = $AdminEmployeeNo; password = $Password } | ConvertTo-Json -Compress
    try {
        $resp = Invoke-WebRequest -Uri "$BackendUrl/api/v1/auth/login" -Method POST `
            -UseBasicParsing -ContentType 'application/json' -Body $body -TimeoutSec 10
        return [pscustomobject]@{ Ok = ($resp.StatusCode -eq 200); Status = $resp.StatusCode }
    } catch {
        $code = $null
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        return [pscustomobject]@{ Ok = $false; Status = $(if ($code) { $code } else { $_.Exception.Message }) }
    }
}

# --------------------------------------------------------------------------- #
# 进程管理
# --------------------------------------------------------------------------- #
function Save-State {
    param([hashtable]$State)
    if (-not (Test-Path $RunDir)) { New-Item -ItemType Directory -Path $RunDir -Force | Out-Null }
    $State | ConvertTo-Json -Depth 5 | Set-Content -Path $StateFile -Encoding utf8
}

function Read-State {
    if (-not (Test-Path $StateFile)) { return $null }
    try { return Get-Content $StateFile -Raw -Encoding utf8 | ConvertFrom-Json } catch { return $null }
}

<#
    杀掉"属于本项目"的进程。

    为什么要按命令行匹配而不是只靠 PID 文件：如果脚本被 Ctrl+C 打断、
    或有人手动起过服务，PID 文件就不可靠了，端口仍然被占着。
    但也不能按进程名乱杀（会误伤别人的 python/node），
    所以同时要求命令行里出现本仓库路径 + 服务特征词。
#>
function Stop-RecordedProcessTrees {
    <#
        按 .run/state.json 里记录的窗口 PID 结束整棵进程树。

        必须用 taskkill /T：后端窗口里挂着 python，前端窗口里挂着 cmd -> npm -> node。
        只结束窗口自身会留下子进程继续占着端口。
    #>
    $state = Read-State
    if (-not $state) { return 0 }

    $killed = 0
    foreach ($field in 'backendPid', 'frontendPid') {
        $procId = $state.$field
        if (-not $procId) { continue }
        if (-not (Get-Process -Id $procId -ErrorAction SilentlyContinue)) { continue }
        try {
            & taskkill.exe /PID $procId /T /F 2>&1 | Out-Null
            Write-Step "已结束 $field 进程树（PID=$procId）"
            $killed++
        } catch {
            Write-Warn "结束 PID=$procId 失败：$($_.Exception.Message)"
        }
    }
    return $killed
}

function Stop-ProjectProcesses {
    param([int]$BackendPort, [int]$FrontendPort)

    $killed = 0
    $selfPid = $PID
    $patterns = @('uvicorn', 'app.main:app', 'vite')
    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue

    foreach ($p in $processes) {
        if (-not $p.CommandLine) { continue }
        if ($p.ProcessId -eq $selfPid) { continue }
        if ($p.Name -notin @('python.exe', 'pythonw.exe', 'node.exe', 'cmd.exe')) { continue }
        if ($p.CommandLine -notlike "*$Root*" -and $p.CommandLine -notlike "*康复过程记录系统*") { continue }

        $hit = $false
        foreach ($pat in $patterns) { if ($p.CommandLine -like "*$pat*") { $hit = $true; break } }
        if (-not $hit) { continue }

        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Step "已结束进程 $($p.Name) PID=$($p.ProcessId)"
            $killed++
        } catch {
            Write-Warn "无法结束 PID=$($p.ProcessId)：$($_.Exception.Message)"
        }
    }

    # 兜底：谁占着端口就杀谁（可能命令行匹配不到，例如被包了一层）
    foreach ($port in @($BackendPort, $FrontendPort)) {
        foreach ($owner in (Get-PortOwner -Port $port)) {
            if ($owner -eq $selfPid) { continue }
            try {
                Stop-Process -Id $owner -Force -ErrorAction Stop
                Write-Step "已结束占用端口 $port 的进程 PID=$owner"
                $killed++
            } catch {
                Write-Warn "无法结束占用端口 $port 的 PID=$owner"
            }
        }
    }
    return $killed
}

function Start-ServiceWindow {
    param(
        [string]$Title,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [hashtable]$ExtraEnv = @{}
    )

    $envPrefix = ''
    foreach ($k in $ExtraEnv.Keys) {
        $v = $ExtraEnv[$k]
        $envPrefix += "`$env:$k='$v'; "
    }
    $quotedArgs = ($ArgumentList | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
    $inner = "$envPrefix& '$FilePath' $quotedArgs"

    $cmd = "`$host.UI.RawUI.WindowTitle='$Title'; $inner"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))

    $p = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoLogo', '-NoExit', '-EncodedCommand', $encoded) `
        -WorkingDirectory $WorkingDirectory -PassThru
    return $p
}

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 90, [string]$Name = '服务')
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch {
            # 连不上/还在启动，继续等
        }
        Start-Sleep -Milliseconds 700
    }
    Write-Warn "$Name 在 $TimeoutSec 秒内未就绪：$Url"
    return $false
}

# --------------------------------------------------------------------------- #
# start
# --------------------------------------------------------------------------- #
function Invoke-Start {
    Write-Head '康复科治疗过程记录系统 — 启动'

    if (-not (Test-Path $BackendDir)) { Write-Err "找不到后端目录：$BackendDir"; return 1 }
    if (-not (Test-Path $AdminDir))   { Write-Err "找不到前端目录：$AdminDir";  return 1 }
    if (-not (Test-Path $LogDir))     { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

    # -- 环境 --
    $python = Resolve-Python
    if (-not $python) {
        Write-Err '找不到可用的 Python 3.12+ 解释器。'
        Write-Host '       请在仓库根目录创建 .python-path 文件，内容为 python.exe 的完整路径，' -ForegroundColor Yellow
        Write-Host '       或设置环境变量 KB_PYTHON。' -ForegroundColor Yellow
        return 1
    }
    Write-Ok "Python: $python"

    $nodeInfo = Resolve-Node
    if (-not $nodeInfo) { Write-Err '找不到 Node.js / npm，请先安装 Node 22+。'; return 1 }
    Write-Ok "Node  : $($nodeInfo.Node)"

    # -- 端口 --
    # 已经被占用时先做一次**完整清理**（按上次记录的进程树 + 按端口 + 按命令行），
    # 而不是只杀占端口的那个进程：npm 会经由 cmd.exe 再拉 node，
    # 只杀 node 会留下一串 cmd/npm 包装进程，反复启动就会越堆越多（实测踩到过）。
    if ((Test-PortBusy -Port $BackendPort) -or (Test-PortBusy -Port $FrontendPort)) {
        Write-Warn '检测到本项目残留服务，先做一次完整清理…'
        Stop-RecordedProcessTrees
        $null = Stop-ProjectProcesses -BackendPort $BackendPort -FrontendPort $FrontendPort
        Start-Sleep -Seconds 2
    }
    foreach ($port in @($BackendPort, $FrontendPort)) {
        if (Test-PortBusy -Port $port) {
            Write-Err "端口 $port 被本项目之外的进程占用。请手动处理或改用其它端口："
            Write-Host "       .\start.ps1 -BackendPort 8010 -FrontendPort 5174" -ForegroundColor Yellow
            return 1
        }
    }
    Write-Ok "端口 $BackendPort / $FrontendPort 可用"

    # -- 数据 --
    Initialize-Data -Python $python

    $password = Get-AdminPassword
    $adminOut = Ensure-Admin -Python $python -Password $password
    if ($adminOut -match '已创建管理员') { Write-Ok '管理员账号已创建' }
    else { Write-Ok '管理员账号已存在（密码已重置为下方展示的值）' }

    # -- 前端依赖 --
    if (-not (Test-Path (Join-Path $AdminDir 'node_modules'))) {
        Write-Step '首次运行：安装前端依赖（npm install，约一两分钟）…'
        $install = Invoke-NativeCommand -FilePath $nodeInfo.Npm -Arguments @('install') `
            -WorkingDirectory $AdminDir
        if ($install.ExitCode -ne 0) {
            $install.Output | Select-Object -Last 15 | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
            throw 'npm install 失败，请查看上方输出'
        }
        Write-Ok '前端依赖安装完成'
    }

    # -- 起后端 --
    Write-Step "启动后端 uvicorn（监听 $BackendHost，端口 $BackendPort）…"
    $backend = Start-ServiceWindow -Title '康复系统 - 后端 API' `
        -FilePath $python `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', $BackendHost, '--port', "$BackendPort") `
        -WorkingDirectory $BackendDir `
        -ExtraEnv @{ PYTHONIOENCODING = 'utf-8'; PYTHONUTF8 = '1' }

    if (-not (Wait-HttpOk -Url "$BackendUrl/api/v1/health" -TimeoutSec 60 -Name '后端')) {
        Write-Err '后端未就绪。请查看弹出的"后端 API"窗口里的报错。'
        return 1
    }
    Write-Ok '后端已就绪'

    # -- 真正的密码自校验（此时服务已在跑，前面那次会因服务未启动而跳过）--
    # 这一步是"窗口里打印的密码一定能登录"的保证：密码来源有多个
    # （-AdminPassword / KB_ADMIN_PASSWORD / 密码文件），只要有一处对不上，
    # 用户就会遇到"照着屏幕输却登不进去"。这里当场验一次并给出修复命令。
    $loginCheck = Test-AdminLogin -Password $password
    if ($loginCheck.Ok) {
        Write-Ok '管理员密码自校验通过'
    } else {
        Write-Warn "管理员密码自校验未通过（登录返回 $($loginCheck.Status)）。"
        Write-Host "        请手动重置一次：" -ForegroundColor Yellow
        Write-Host "          cd backend; `$env:KB_ADMIN_PASSWORD='$password'; python -m app.cli create-admin $AdminEmployeeNo --name $AdminName" -ForegroundColor Yellow
    }

    # -- 起前端 --
    Write-Step "启动管理后台（端口 $FrontendPort）…"
    # ⚠ **不要通过 `npm run dev --` 传 `--port` / `--host`**：
    # npm 会把它们当成自己的参数吞掉（实测报 `Unsupported URL Type` 或
    # `Unused args: 5173`），真正生效的是 `admin/vite.config.ts` 里的 `server.host/port`。
    # 那里已绑 `0.0.0.0`（IPv4 全接口）+ 固定端口，内网与本机都能访问。
    # npm 是 .ps1/.cmd 包装，交给 cmd.exe 起更稳（避免 PowerShell 执行策略干扰）
    $frontend = Start-ServiceWindow -Title '康复系统 - 管理后台' `
        -FilePath 'cmd.exe' `
        -ArgumentList @('/c', 'npm', 'run', 'dev') `
        -WorkingDirectory $AdminDir `
        -ExtraEnv @{
            VITE_API_TARGET = $BackendUrl
            # `KB_LAN=1` 让 `admin/vite.config.ts` 把 Vite 绑到全 IPv4 接口；
            # 否则只绑回环（见那里的说明）。
            KB_LAN = if ($Lan) { '1' } else { '0' }
        }

    if (-not (Wait-HttpOk -Url $FrontendUrl -TimeoutSec 90 -Name '前端')) {
        Write-Warn '前端未在预期时间内就绪，可能仍在编译。稍等片刻后刷新浏览器即可。'
    } else {
        Write-Ok '管理后台已就绪'
    }

    # -- `-Lan`：放行防火墙（否则内网连不上，而"连不上"很难自己排查出来）--
    #
    # 为什么必须显式做：`backend/scripts/run_on_emulator.ps1` 的注释里就记过这个坑 ——
    # 「Windows 防火墙入站默认阻止，而 uvicorn 没有对应的放行规则」，
    # 当时是靠 `adb reverse` 绕过去的。内网客户端绕不过去，只能放行。
    #
    # 只放行**入站 TCP** 的这两个端口，且规则名固定（重复运行会复用，不会越积越多）。
    if ($Lan) {
        $ports = @($FrontendPort, $BackendPort) | Sort-Object -Unique
        foreach ($port in $ports) {
            $ruleName = "康复系统 $port (TCP-In)"
            try {
                $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
                if ($existing) {
                    Write-Ok "防火墙规则已存在：$ruleName"
                } else {
                    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
                        -Protocol TCP -LocalPort $port -Profile Any -ErrorAction Stop | Out-Null
                    Write-Ok "已放行防火墙入站：$ruleName"
                }
            } catch {
                Write-Warn "放行防火墙失败（$ruleName）：$($_.Exception.Message)"
                Write-Host "        需要**管理员** PowerShell 手动执行一次：" -ForegroundColor Yellow
                Write-Host "          New-NetFirewallRule -DisplayName '康复系统 $port (TCP-In)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Any" -ForegroundColor Yellow
            }
        }
    }

    Save-State @{
        startedAt     = (Get-Date).ToString('s')
        backendPid    = $backend.Id
        frontendPid   = $frontend.Id
        backendPort   = $BackendPort
        frontendPort  = $FrontendPort
        python        = $python
        loginUrl      = $LoginUrl
        lan           = [bool]$Lan
        backendHost   = $BackendHost
    }

    # -- 提示账号密码 --
    Write-Head '登录信息'
    Write-Host ''
    Write-Host '        登录地址 : ' -NoNewline -ForegroundColor Gray
    Write-Host $LoginUrl -ForegroundColor White
    Write-Host ''
    Write-Host '        管理员工号 : ' -NoNewline -ForegroundColor Gray
    Write-Host $AdminEmployeeNo -ForegroundColor Yellow
    Write-Host '        管理员密码 : ' -NoNewline -ForegroundColor Gray
    Write-Host $password -ForegroundColor Yellow
    Write-Host ''
    Write-Host "        （密码同时保存在 $(Split-Path $PwdFile -Leaf)，该文件已 gitignore；" -ForegroundColor DarkGray
    Write-Host "          首次登录后建议在右上角菜单里改成自己的密码。）" -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '        后端文档 : ' -NoNewline -ForegroundColor Gray
    Write-Host "$BackendUrl/docs" -ForegroundColor White
    Write-Host '        停止服务 : ' -NoNewline -ForegroundColor Gray
    Write-Host '.\start.ps1 stop' -ForegroundColor White
    Write-Host ''
    if ($Lan) {
        # 把内网地址直接打出来 —— 让用户去 `ipconfig` 里翻是一件很烦的事。
        $lanIps = Get-LanIPv4
        if ($lanIps.Count -gt 0) {
            Write-Host '        内网访问（其它客户端） : ' -NoNewline -ForegroundColor Gray
            Write-Host "http://$($lanIps[0]):$FrontendPort" -ForegroundColor Green
            foreach ($ip in $lanIps | Select-Object -Skip 1) {
                Write-Host "                                   http://${ip}:$FrontendPort" -ForegroundColor DarkGray
            }
        } else {
            Write-Warn '没有找到可用的 IPv4 网卡地址，内网客户端可能连不上（检查网络连接）。'
        }
        Write-Host '        （只监听 IPv4；防火墙入站已放行。改回只绑本机：去掉 -Lan）' -ForegroundColor DarkGray
        Write-Host ''
    } else {
        Write-Host '        只绑本机（127.0.0.1）。要让内网其它客户端访问，用：' -ForegroundColor DarkGray
        Write-Host '          .\start.ps1 -Lan' -ForegroundColor DarkGray
        Write-Host ''
    }
    Write-Host '        后端与管理后台各在一个独立窗口里运行；关闭那些窗口也会停止服务。' -ForegroundColor DarkGray
    Write-Host ''

    if (-not $NoBrowser) {
        Write-Step '正在打开浏览器…'
        Start-Process $LoginUrl | Out-Null
    }
    return 0
}

# --------------------------------------------------------------------------- #
# stop
# --------------------------------------------------------------------------- #
function Invoke-Stop {
    Write-Head '康复科治疗过程记录系统 — 停止'

    if (-not (Test-Path $StateFile)) {
        Write-Step '没有找到上次启动的记录，按端口与命令行查找本项目进程…'
    }
    $killed = Stop-RecordedProcessTrees
    $killed += Stop-ProjectProcesses -BackendPort $BackendPort -FrontendPort $FrontendPort
    Start-Sleep -Seconds 1

    $stillBusy = @()
    foreach ($port in @($BackendPort, $FrontendPort)) {
        if (Test-PortBusy -Port $port) { $stillBusy += $port }
    }
    if ($stillBusy.Count -gt 0) {
        Write-Warn "以下端口仍被占用：$($stillBusy -join ', ')"
        return 1
    }

    if (Test-Path $StateFile) { Remove-Item $StateFile -Force }
    Write-Ok "已停止（清理了 $killed 项）"
    return 0
}

# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
function Invoke-Status {
    Write-Head '康复科治疗过程记录系统 — 状态'

    $backendUp  = Test-PortBusy -Port $BackendPort
    $frontendUp = Test-PortBusy -Port $FrontendPort

    Write-Host "        后端  ($BackendPort)  : " -NoNewline -ForegroundColor Gray
    if ($backendUp) { Write-Host '运行中' -ForegroundColor Green } else { Write-Host '未运行' -ForegroundColor DarkGray }
    Write-Host "        前端  ($FrontendPort)  : " -NoNewline -ForegroundColor Gray
    if ($frontendUp) { Write-Host '运行中' -ForegroundColor Green } else { Write-Host '未运行' -ForegroundColor DarkGray }

    # 健康检查能给出版本、迁移版本与自检结论，比"端口开着"更有信息量
    if ($backendUp) {
        try {
            $h = Invoke-RestMethod -Uri "$BackendUrl/api/v1/health" -TimeoutSec 5
            Write-Host "        数据库迁移版本        : $($h.database.schema_version)" -ForegroundColor Gray
            Write-Host "        健康状态              : $($h.status)" -ForegroundColor Gray
        } catch {
            Write-Warn '后端在监听但健康检查失败，可能仍在启动中'
        }
    }

    $state = Read-State
    if ($state) { Write-Host "        上次启动时间          : $($state.startedAt)" -ForegroundColor DarkGray }
    return 0
}

# --------------------------------------------------------------------------- #
# clean
#
# 清掉运行时产物，把工作区恢复成"可提交"的干净状态。
# 这些都是可再生成的：缓存、浏览器剖析目录、日志、测试临时库。
#
# **默认不动数据库**（`data/kf.db` 里有你录入的数据）。要连库一起删请显式加
# `-IncludeData` —— 那种情况下下次启动会自动重新建库并导种子。
# --------------------------------------------------------------------------- #
function Invoke-Clean {
    param([switch]$IncludeData)

    Write-Head '康复科治疗过程记录系统 — 清理运行时产物'

    # 先停服务：服务运行时文件被占用，删不掉，而且删掉日志也没意义
    $null = Invoke-Stop

    $before = 0
    if (Test-Path $Root) {
        $before = (Get-ChildItem $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
                   Measure-Object Length -Sum).Sum
    }

    $removed = 0

    # 先把所有要删的路径收集成一个列表，再在**同一个作用域**里逐个删除。
    # 之前用了一个嵌套函数来删、在里面写 `$script:removed++`，结果
    # `$script:` 指的是**脚本**作用域而不是本函数的局部变量，抛
    # "The variable '$script:removed' cannot be retrieved"，
    # 还被 catch 当成"删除失败"，把成功误报成失败（踩过一次）。
    # 收集成列表再就地删除，就没有跨作用域写变量的问题。
    $targets = New-Object System.Collections.Generic.List[object]

    # 1) 缓存目录（跑一次测试/构建就会重新生成，删了没风险）
    Get-ChildItem $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\(node_modules|\.npm-cache|\.git)\\' } |
        Where-Object { $_.Name -in @('__pycache__', '.ruff_cache', '.pytest_cache', '.mypy_cache') -or $_.Name -like 'pytest-cache-files-*' } |
        ForEach-Object { $targets.Add([pscustomobject]@{ Path = $_.FullName; Label = $_.FullName.Replace($Root, '') }) }

    # 2) 浏览器剖析目录（验收脚本跑完留下的，每个数百 MB）
    foreach ($profile in '.run\edge', '.run\edge2', 'backend\data\_edgeprofile3') {
        $targets.Add([pscustomobject]@{ Path = (Join-Path $Root $profile); Label = $profile })
    }

    # 3) 日志与一次性输出（.run 下除了 logs 全清）
    foreach ($f in Get-ChildItem (Join-Path $Root '.run') -Force -ErrorAction SilentlyContinue) {
        if ($f.Name -ne 'logs') {
            $targets.Add([pscustomobject]@{ Path = $f.FullName; Label = ".run\$($f.Name)" })
        }
    }
    foreach ($p in @('.run\logs', 'logs', 'backend\data\_be.log', 'backend\data\_be.err',
                     'backend\data\_fe.log', 'backend\data\_fe.err')) {
        $targets.Add([pscustomobject]@{ Path = (Join-Path $Root $p); Label = $p })
    }

    # 4) 测试临时文件、早期 mkdtemp 留下的空目录，以及 backend/data 下的陈旧库副本
    #    （真实库在根 data/kf.db）
    $testDataDir = Join-Path $Root 'backend\data'
    if (Test-Path $testDataDir) {
        Get-ChildItem $testDataDir -Force -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -like 'kf-test-*' -or $_.Name -like 'kf-pdf-*' -or
                $_.Name -like '_*' -or $_.Name -like 'kf.db*'
            } |
            ForEach-Object { $targets.Add([pscustomobject]@{ Path = $_.FullName; Label = "backend\data\$($_.Name)" }) }
    }

    # 5) 可选：连开发数据库一起删（下次启动会重建并导种子）
    if ($IncludeData) {
        Write-Warn '-IncludeData 已指定：将删除开发数据库 data\kf.db（下次启动会重建并导种子）'
        Get-ChildItem (Join-Path $Root 'data') -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'kf.db*' } |
            ForEach-Object { $targets.Add([pscustomobject]@{ Path = $_.FullName; Label = "data\$($_.Name)" }) }
    } else {
        Write-Step '保留开发数据库 data\kf.db（要一起删请加 -IncludeData）'
    }

    foreach ($t in $targets) {
        if (-not (Test-Path $t.Path)) { continue }
        try {
            Remove-Item $t.Path -Recurse -Force -ErrorAction Stop
            Write-Step "已删除 $($t.Label)"
            $removed++
        } catch {
            Write-Warn "无法删除 $($t.Label)（可能仍被占用）：$($_.Exception.Message.Split([char]10)[0])"
        }
    }

    $after = 0
    if (Test-Path $Root) {
        $after = (Get-ChildItem $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
                  Measure-Object Length -Sum).Sum
    }
    $freedMb = [math]::Round(($before - $after) / 1MB, 1)
    Write-Ok "清理完成：处理 $removed 项，释放 $freedMb MB（当前 $([math]::Round($after / 1MB, 1)) MB）"
    return 0
}

# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
try {
    switch ($Action) {
        'stop'    { exit (Invoke-Stop) }
        'status'  { exit (Invoke-Status) }
        'clean'   { exit (Invoke-Clean -IncludeData:$IncludeData) }
        'restart' {
            $null = Invoke-Stop
            Start-Sleep -Seconds 2
            exit (Invoke-Start)
        }
        default   { exit (Invoke-Start) }
    }
} catch {
    Write-Err $_.Exception.Message
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
    exit 1
}
