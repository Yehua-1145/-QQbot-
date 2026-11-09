<#
大肥鱼（Fatfish）· 电脑端轻量部署脚本
--------------------------------------------------
只做三件事：找到 adb → 把 APK 装到手机 → 启动 App
不需要 Python、不需要运行时、不需要联网下载。

用法（PowerShell）：
  .\deploy.ps1                       # 用同目录的 Botagent.apk，自动挑设备
  .\deploy.ps1 -Apk D:\x.apk        # 指定 APK
  .\deploy.ps1 -Serial 3ed565aa     # 多台手机时指定
  .\deploy.ps1 -A11y                # 顺手打开无障碍（免手点）
  .\deploy.ps1 -NoLaunch            # 只装不启动

找不到 adb 时，按提示装 platform-tools，或把 platform-tools 放进本目录。
#>

param(
    [string]$Apk = "",
    [string]$Serial = "",
    [switch]$A11y,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$pkg = "com.botagent"
$act = "$pkg/.MainActivity"

function Say($m, $c = "Gray") { Write-Host $m -ForegroundColor $c }

Say "== 大肥鱼 · 电脑端部署 ==" "Cyan"

# ---------- 1) 找 APK ----------
if (-not $Apk) {
    $cands = @("$PSScriptRoot\Botagent.apk", "$PSScriptRoot\Botagent-v2.0-beta.apk")
    $cands += (Get-ChildItem $PSScriptRoot -Filter "*.apk" -ErrorAction SilentlyContinue |
               Sort-Object Length -Descending | ForEach-Object { $_.FullName })
    $Apk = $cands | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $Apk -or -not (Test-Path $Apk)) {
    Say "找不到 APK。把 APK 放到本目录，或用 -Apk 指定。" "Red"
    exit 1
}
$mb = [math]::Round((Get-Item $Apk).Length / 1MB, 1)
Say ("APK : {0} ({1} MB)" -f (Split-Path $Apk -Leaf), $mb)

# ---------- 2) 找 adb ----------
$adb = $null
foreach ($p in @("$PSScriptRoot\adb.exe", "$PSScriptRoot\platform-tools\adb.exe")) {
    if (Test-Path $p) { $adb = $p; break }
}
if (-not $adb) {
    $c = Get-Command adb -ErrorAction SilentlyContinue
    if ($c) { $adb = $c.Source }
}
if (-not $adb) {
    foreach ($p in @("$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
                     "D:\platform-tools\adb.exe", "C:\platform-tools\adb.exe")) {
        if (Test-Path $p) { $adb = $p; break }
    }
}
if (-not $adb) {
    Say "找不到 adb。" "Red"
    Say "  1) 下载 platform-tools 解压到本目录（约 12 MB）" "Yellow"
    Say "  2) 或把 platform-tools 目录加到 PATH" "Yellow"
    exit 1
}
Say ("adb : {0}" -f $adb)

# ---------- 3) 找设备 ----------
$lines = & $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" }
$devs = @()
foreach ($l in $lines) { $devs += ($l -split "\t")[0] }
if (-not $Serial) {
    if ($devs.Count -eq 0) {
        Say "没有连上手机。检查：USB 线、开发者选项、USB 调试授权。" "Red"
        exit 1
    }
    if ($devs.Count -gt 1) {
        Say ("检测到多台：{0}" -f ($devs -join ", ")) "Yellow"
        Say "用 -Serial 指定一台。" "Yellow"
        exit 1
    }
    $Serial = $devs[0]
}
Say ("设备: {0}" -f $Serial)

# ---------- 4) 装 ----------
Say "`n== 安装 ==" "Cyan"
& $adb -s $Serial install -r $Apk
if ($LASTEXITCODE -ne 0) {
    Say "安装失败。小米/红米常见原因：开发者选项里的「USB 安装」没开。" "Red"
    exit 1
}
Say "装好了" "Green"

# ---------- 5) 可选：开无障碍 ----------
if ($A11y) {
    Say "`n== 打开无障碍 ==" "Cyan"
    & $adb -s $Serial shell "settings put secure enabled_accessibility_services $pkg/$pkg.A11yService"
    & $adb -s $Serial shell "settings put secure accessibility_enabled 1"
    Say "已写入无障碍设置（个别系统需手动确认一次）" "Green"
}

# ---------- 6) 启动 ----------
if (-not $NoLaunch) {
    Say "`n== 启动 ==" "Cyan"
    & $adb -s $Serial shell "monkey -p $pkg -c android.intent.category.LAUNCHER 1" | Out-Null
    Say "已启动，去手机上按向导走" "Green"
}

Say "`n完成。手机上：① 填账号 → ② 开权限 → ③ 环境 → ④ 启动" "Cyan"
