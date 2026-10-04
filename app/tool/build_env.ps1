#!/usr/bin/env pwsh
<#
.SYNOPSIS
    为 Flutter 构建准备环境变量（国内镜像 + Android/JDK + 可选 HTTP 代理）。

.DESCRIPTION
    为什么需要这个脚本：Flutter/Android 构建会访问一堆**国内不可达**的地址，
    每个都要单独处理，散在文档里必然漏。集中在一处，一条命令搞定。

    它设置：

      1. 国内镜像
         PUB_HOSTED_URL           = https://pub.flutter-io.cn
         FLUTTER_STORAGE_BASE_URL = https://storage.flutter-io.cn
      2. Android / JDK
         ANDROID_HOME / ANDROID_SDK_ROOT / JAVA_HOME
         （JAVA_HOME 指向 Android Studio 自带的 JDK，因为系统里那个
           `C:\Program Files\Java\jdk-17` 是**空壳目录**，没有 bin/）
      3. **HTTP 代理（关键）**
         `sqlite3` 包通过 native assets 机制从 **GitHub Releases**
         下载预编译库（libsqlite3.*.android.so）。该地址在国内不可达，
         拿不到就会构建失败：
             Target build_hooks failed: Error: Building native assets failed
             ... attempted to download https://github.com/simolus3/sqlite3.dart/releases/...
         所以构建前需要一个能出去的代理。脚本会自动探测常见端口，
         也可以用 -Proxy 显式指定，或 -NoProxy 关闭。

.PARAMETER Proxy
    代理地址，如 `http://127.0.0.1:10808`。不传则自动探测。

.PARAMETER NoProxy
    不设置任何代理（内网直连或已有全局代理时用）。

.PARAMETER FlutterCommand
    环境就绪后要执行的命令（默认 `flutter build apk --debug`）。
    **刻意不叫 `-Command`** —— 那个名字与 `pwsh -Command` 冲突：用
    `pwsh -File build_env.ps1 -Command "flutter analyze"` 调用时，
    PowerShell 自身会先吃掉 `-Command`，脚本里读到的是 "analyze"。

.EXAMPLE
    .\tool\build_env.ps1
    .\tool\build_env.ps1 -FlutterCommand "flutter analyze"
    .\tool\build_env.ps1 -Proxy http://127.0.0.1:10809
    .\tool\build_env.ps1 -NoProxy -FlutterCommand "flutter test"

.NOTES
    用法（在 `app/` 目录下）：

        pwsh -NoLogo -ExecutionPolicy Bypass -Command "& './tool/build_env.ps1'"

    ★ 不要用 `pwsh -File tool\build_env.ps1 -FlutterCommand '...'`：
    `-File` 形式的命名参数绑定不可靠（`-FlutterCommand` 之后的值会被当成
    位置参数，实测代理被误设为 "analyze"）。用 `-Command "& './...' -参数 值"`。

    该脚本只影响当前进程，不会永久改系统环境变量。
#>
[CmdletBinding()]
param(
    [string]$Proxy,
    [switch]$NoProxy,
    [string]$FlutterCommand = 'flutter build apk --debug'
)

$ErrorActionPreference = 'Stop'

# --------------------------------------------------------------------------- #
# 1) 国内镜像
# --------------------------------------------------------------------------- #
$env:PUB_HOSTED_URL = 'https://pub.flutter-io.cn'
$env:FLUTTER_STORAGE_BASE_URL = 'https://storage.flutter-io.cn'

# --------------------------------------------------------------------------- #
# 2) Android SDK 与 JDK
# --------------------------------------------------------------------------- #
$sdkCandidates = @('D:\Android\sdk', "$env:LOCALAPPDATA\Android\Sdk")
$sdk = $sdkCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($sdk) {
    $env:ANDROID_HOME = $sdk
    $env:ANDROID_SDK_ROOT = $sdk
} else {
    Write-Warning "未找到 Android SDK（试过：$($sdkCandidates -join ', ')）"
}

# JAVA_HOME：Gradle 需要真的能用的 JDK。优先 Android Studio 自带的 JBR。
$jdkCandidates = @(
    'D:\Program Files\Android\Android Studio\jbr',
    'C:\Program Files\Android\Android Studio\jbr',
    "$env:LOCALAPPDATA\Programs\Android Studio\jbr"
)
$jdk = $jdkCandidates | Where-Object { Test-Path (Join-Path $_ 'bin\java.exe') } | Select-Object -First 1
if ($jdk) {
    $env:JAVA_HOME = $jdk
} else {
    Write-Warning '未找到可用 JDK（Android Studio 自带的 jbr）'
}

# --------------------------------------------------------------------------- #
# 3) HTTP 代理（sqlite3 的 native assets 必须能访问 GitHub Releases）
# --------------------------------------------------------------------------- #
if (-not $NoProxy) {
    if (-not $Proxy) {
        # 自动探测常见本地代理端口（v2rayN 的混合端口等）。
        foreach ($port in 10808, 10809, 7890, 7897, 1080) {
            $open = Test-NetConnection -ComputerName 127.0.0.1 -Port $port `
                -InformationLevel Quiet -WarningAction SilentlyContinue
            if ($open) { $Proxy = "http://127.0.0.1:$port"; break }
        }
    }

    if ($Proxy) {
        $env:HTTP_PROXY = $Proxy
        $env:HTTPS_PROXY = $Proxy
        # 本机与模拟器宿主机地址不要走代理，否则模拟器连后端会绕远甚至失败。
        $env:NO_PROXY = 'localhost,127.0.0.1,::1,10.0.2.2'
        Write-Host "[env] 代理      : $Proxy" -ForegroundColor Green
    } else {
        Write-Warning @'
未探测到本地代理。若构建报 "Building native assets failed" 且日志里出现
github.com/simolus3/sqlite3.dart，说明 sqlite3 的预编译库下不下来 ——
请启动代理后用 -Proxy http://127.0.0.1:<端口> 重试。
'@
    }
} else {
    Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY -ErrorAction SilentlyContinue
    Write-Host '[env] 代理      : 已禁用（-NoProxy）' -ForegroundColor Yellow
}

# --------------------------------------------------------------------------- #
# 环境摘要 + 执行
# --------------------------------------------------------------------------- #
Write-Host "[env] PUB 镜像  : $env:PUB_HOSTED_URL" -ForegroundColor Green
Write-Host "[env] FLUTTER   : $env:FLUTTER_STORAGE_BASE_URL" -ForegroundColor Green
Write-Host "[env] ANDROID   : $env:ANDROID_HOME" -ForegroundColor Green
Write-Host "[env] JAVA_HOME : $env:JAVA_HOME" -ForegroundColor Green
Write-Host ''
Write-Host "> $FlutterCommand" -ForegroundColor Cyan

# 直接用 Invoke-Expression 执行命令串。
# 不用 `& $exe @args`：flutter.bat 是批处理包装，PowerShell 把数组参数展开成
# 单个字符时会被 bat 重新解析，实测会报 `Could not find a command named "a"`。
# 命令串来自本脚本的调用者（开发者本人），不是外部输入，这里没有注入面。
Invoke-Expression $FlutterCommand
exit $LASTEXITCODE
