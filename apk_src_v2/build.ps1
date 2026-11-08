# 构建 Botagent v2 的 APK（不用 Gradle，不用 Android Studio）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File build.ps1
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Out "C:\path\Botagent.apk"
#
# 环境变量（可选，不设就按常见位置找）：
#   ANDROID_SDK_ROOT / ANDROID_HOME   SDK 根目录
#   JAVA_HOME                         JDK 目录（8 或 11）
#   BOTAGENT_API                      构建用的 API 级别，默认 34

param(
    [string]$Out = "",
    [int]$Api = 34
)

$ErrorActionPreference = 'Continue'
if ($env:BOTAGENT_API) { $Api = [int]$env:BOTAGENT_API }

# ---------- 找工具链 ----------
$b = $PSScriptRoot

$sdk = $env:ANDROID_SDK_ROOT
if (-not $sdk) { $sdk = $env:ANDROID_HOME }
if (-not $sdk) {
    foreach ($p in @("$env:LOCALAPPDATA\Android\Sdk", "C:\Android\Sdk", "D:\androidsdk")) {
        if (Test-Path $p) { $sdk = $p; break }
    }
}
if (-not $sdk) { Write-Host '找不到 Android SDK，请设置 ANDROID_SDK_ROOT' -ForegroundColor Red; exit 1 }

$jar = "$sdk\platforms\android-$Api\android.jar"
if (-not (Test-Path $jar)) {
    $cand = Get-ChildItem "$sdk\platforms" -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path "$($_.FullName)\android.jar" } |
            Sort-Object Name -Descending | Select-Object -First 1
    if ($cand) { $jar = "$($cand.FullName)\android.jar" }
}
if (-not (Test-Path $jar)) { Write-Host "找不到 android.jar（需要 platform android-$Api）" -ForegroundColor Red; exit 1 }

$bt = Get-ChildItem "$sdk\build-tools" -Directory -ErrorAction SilentlyContinue |
      Sort-Object Name -Descending | Select-Object -First 1
if (-not $bt) { Write-Host '找不到 build-tools' -ForegroundColor Red; exit 1 }
$bt = $bt.FullName

$kt = "$env:JAVA_HOME\bin\keytool.exe"
if (-not $env:JAVA_HOME -or -not (Test-Path $kt)) {
    $cmd = Get-Command keytool -ErrorAction SilentlyContinue
    if ($cmd) { $kt = $cmd.Source }
}
if (-not $kt -or -not (Test-Path $kt)) {
    Write-Host '找不到 keytool（装 JDK 并设置 JAVA_HOME）' -ForegroundColor Red; exit 1
}

# ---------- JDK 版本校验 ----------
# d8 / apksigner 是 Java 11+ 编译的，用 JDK 8 跑会报 UnsupportedClassVersionError
$javaExe = "$env:JAVA_HOME\bin\java.exe"
if (-not (Test-Path $javaExe)) {
    $c = Get-Command java -ErrorAction SilentlyContinue
    if ($c) { $javaExe = $c.Source }
}
$javaMajor = 0
if ($javaExe -and (Test-Path $javaExe)) {
    $verLine = (& $javaExe -version 2>&1 | Select-Object -First 1) -join ' '
    if ($verLine -match '"(\d+)(\.(\d+))?') {
        $javaMajor = [int]$Matches[1]
        if ($javaMajor -eq 1 -and $Matches[3]) { $javaMajor = [int]$Matches[3] }
    }
}
if ($javaMajor -lt 11) {
    Write-Host "当前 java 是 $javaMajor，但 d8 / apksigner 需要 11 或更高。" -ForegroundColor Red
    Write-Host "装个 JDK 17，然后设置：" -ForegroundColor Yellow
    Write-Host '  $env:JAVA_HOME = "C:\Program Files\Java\jdk-17"' -ForegroundColor DarkGray
    Write-Host '  $env:Path = "$env:JAVA_HOME\bin;" + $env:Path' -ForegroundColor DarkGray
    exit 1
}
Write-Host "java: $javaMajor ($javaExe)"

Write-Host "SDK : $sdk"
Write-Host "jar : $jar"
Write-Host "bt  : $bt"
Write-Host ""

Set-Location $b

# ---------- 0. 资源检查 ----------
if (-not (Test-Path "$b\assets\runtime.zip")) {
    Write-Host '缺 assets\runtime.zip —— 先按 BUILD.md 第一步打运行时包' -ForegroundColor Red
    exit 1
}
$rtMB = [math]::Round((Get-Item "$b\assets\runtime.zip").Length / 1MB, 1)
Write-Host "== 0/6 资源就绪（runtime.zip $rtMB MB）==" -ForegroundColor Cyan

# ---------- 1. 清理 ----------
Write-Host '== 1/6 清理 ==' -ForegroundColor Cyan
Remove-Item -Recurse -Force "$b\classes", "$b\dexout" -ErrorAction SilentlyContinue
Remove-Item -Force "$b\base.apk", "$b\aligned.apk", "$b\Botagent.apk", "$b\classes.zip", "$b\res.zip" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$b\classes", "$b\dexout" | Out-Null

# ---------- 2. javac ----------
Write-Host '== 2/6 javac ==' -ForegroundColor Cyan
$srcs = Get-ChildItem -Recurse "$b\src" -Filter *.java | ForEach-Object { $_.FullName }
if (-not $srcs) { Write-Host 'src 下没有 java 文件' -ForegroundColor Red; exit 1 }
& javac -encoding UTF-8 -source 8 -target 8 -nowarn -bootclasspath $jar -classpath $jar `
    -d "$b\classes" $srcs 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'javac 失败 —— 单独跑一次看报错：' -ForegroundColor Red
    Write-Host "  javac -encoding UTF-8 -source 8 -target 8 -bootclasspath `"$jar`" -classpath `"$jar`" -d `"$b\classes`" <文件>" -ForegroundColor DarkGray
    exit 1
}

# ---------- 3. classes.zip ----------
Write-Host '== 3/6 classes.zip（条目必须用 / 分隔）==' -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open("$b\classes.zip", 'Create')
$root = (Resolve-Path "$b\classes").Path
Get-ChildItem -Recurse "$b\classes" -File | ForEach-Object {
    $rel = $_.FullName.Substring($root.Length + 1).Replace([char]92, [char]47)
    $e = $zip.CreateEntry($rel)
    $s = $e.Open()
    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
    $s.Write($bytes, 0, $bytes.Length)
    $s.Close()
}
$zip.Dispose()

# ---------- 4. d8 ----------
Write-Host '== 4/6 d8 -> classes.dex ==' -ForegroundColor Cyan
& "$bt\d8.bat" --lib $jar --min-api 23 --output "$b\dexout" "$b\classes.zip" 2>&1 | Out-Null
if (-not (Test-Path "$b\dexout\classes.dex")) {
    Write-Host 'd8 失败（看上面输出：JDK 太旧 / 有匿名内部类 / classes.zip 为空）' -ForegroundColor Red
    exit 1
}

# ---------- 5. aapt2 ----------
Write-Host '== 5/6 aapt2 link + 塞 dex ==' -ForegroundColor Cyan
& "$bt\aapt2.exe" compile --dir "$b\res" -o "$b\res.zip" 2>&1 | Out-Null
& "$bt\aapt2.exe" link -o "$b\base.apk" -I $jar --manifest "$b\AndroidManifest.xml" `
    -R "$b\res.zip" -A "$b\assets" --auto-add-overlay `
    --min-sdk-version 23 --target-sdk-version 23 2>&1 | Out-Null
if (-not (Test-Path "$b\base.apk")) { Write-Host 'aapt2 失败' -ForegroundColor Red; exit 1 }

$zip = [System.IO.Compression.ZipFile]::Open("$b\base.apk", 'Update')
$e = $zip.CreateEntry('classes.dex')
$st = $e.Open()
$bytes = [System.IO.File]::ReadAllBytes("$b\dexout\classes.dex")
$st.Write($bytes, 0, $bytes.Length)
$st.Close()
$zip.Dispose()

# ---------- 5.5 native lib（可选） ----------
Write-Host '== 5.5/6 注入 native lib ==' -ForegroundColor Cyan
if (Test-Path "$b\libpayload\arm64-v8a") {
    $root = (Resolve-Path "$b\libpayload").Path
    $zip = [System.IO.Compression.ZipFile]::Open("$b\base.apk", 'Update')
    $n = 0
    Get-ChildItem -Recurse "$b\libpayload" -File | ForEach-Object {
        $rel = $_.FullName.Substring($root.Length + 1).Replace([char]92, [char]47)
        $e = $zip.CreateEntry("lib/" + $rel, [System.IO.Compression.CompressionLevel]::NoCompression)
        $st = $e.Open()
        $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
        $st.Write($bytes, 0, $bytes.Length)
        $st.Close()
        $n = $n + 1
    }
    $zip.Dispose()
    Write-Host ("  lib 注入 " + $n + " 个")
} else {
    Write-Host '  （没有 libpayload，跳过）'
}

# ---------- 5.6 assets/aibot ----------
# 注意：aapt2 在 Windows 上会把嵌套目录写成反斜杠，所以这里自己注入
Write-Host '== 5.6/6 注入 assets/aibot ==' -ForegroundColor Cyan
if (Test-Path "$b\aibot_assets") {
    $root2 = (Resolve-Path "$b\aibot_assets").Path
    $zip2 = [System.IO.Compression.ZipFile]::Open("$b\base.apk", 'Update')
    $m = 0
    Get-ChildItem -Recurse "$b\aibot_assets" -File | ForEach-Object {
        $rel2 = $_.FullName.Substring($root2.Length + 1).Replace([char]92, [char]47)
        $e2 = $zip2.CreateEntry("assets/aibot/" + $rel2, [System.IO.Compression.CompressionLevel]::Optimal)
        $st2 = $e2.Open()
        $bytes2 = [System.IO.File]::ReadAllBytes($_.FullName)
        $st2.Write($bytes2, 0, $bytes2.Length)
        $st2.Close()
        $m = $m + 1
    }
    $zip2.Dispose()
    Write-Host ("  aibot 注入 " + $m + " 个")
} else {
    Write-Host '  缺 aibot_assets\*.py' -ForegroundColor Red
    exit 1
}

# ---------- 6. zipalign + 签名 ----------
Write-Host '== 6/6 zipalign + 签名 ==' -ForegroundColor Cyan
if (-not (Test-Path "$b\debug.keystore")) {
    & $kt -genkeypair -keystore "$b\debug.keystore" -alias androiddebugkey -storepass android `
        -keypass android -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=Botagent,O=Local,C=CN" 2>&1 | Out-Null
}
& "$bt\zipalign.exe" -f 4 "$b\base.apk" "$b\aligned.apk" 2>&1 | Out-Null
& "$bt\apksigner.bat" sign --ks "$b\debug.keystore" --ks-pass pass:android --key-pass pass:android `
    --ks-key-alias androiddebugkey --out "$b\Botagent.apk" "$b\aligned.apk" 2>&1 | Out-Null

if (Test-Path "$b\Botagent.apk") {
    $final = "$b\Botagent.apk"
    if ($Out) { Copy-Item "$b\Botagent.apk" $Out -Force; $final = $Out }
    $mb = [math]::Round((Get-Item $final).Length / 1MB, 1)
    Write-Host "OK -> $final ($mb MB)" -ForegroundColor Green
} else {
    Write-Host '签名失败' -ForegroundColor Red
    exit 1
}
