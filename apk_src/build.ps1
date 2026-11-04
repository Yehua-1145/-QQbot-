# 一键构建 PhoneAgent.apk（不用 Gradle，直接 aapt2 + javac + d8 + zipalign + apksigner）
$ErrorActionPreference = 'Continue'
$sdk = 'D:\androidsdk'
$bt  = "$sdk\bt\android-14"
$jar = "$sdk\pf\android-34\android.jar"
$b   = 'D:\apkbuild'
$kt  = 'C:\Program Files\Java\jre1.8.0_491\bin\keytool.exe'

Set-Location $b

Write-Host '== 1/6 清理 ==' -ForegroundColor Cyan
Remove-Item -Recurse -Force "$b\classes", "$b\dexout" -ErrorAction SilentlyContinue
Remove-Item -Force "$b\base.apk", "$b\aligned.apk", "$b\PhoneAgent.apk", "$b\classes.zip" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$b\classes", "$b\dexout" | Out-Null

Write-Host '== 2/6 javac ==' -ForegroundColor Cyan
& javac -encoding UTF-8 -source 8 -target 8 -bootclasspath $jar -classpath $jar `
    -d "$b\classes" "$b\src\com\phoneagent\MainActivity.java" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host 'javac 失败' -ForegroundColor Red; exit 1 }

Write-Host '== 3/6 classes.zip（条目必须用 / 分隔）==' -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open("$b\classes.zip", 'Create')
$root = (Resolve-Path "$b\classes").Path
Get-ChildItem -Recurse "$b\classes" -File | ForEach-Object {
    $rel = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
    $e = $zip.CreateEntry($rel)
    $s = $e.Open()
    $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
    $s.Write($bytes, 0, $bytes.Length)
    $s.Close()
}
$zip.Dispose()

Write-Host '== 4/6 d8 -> classes.dex ==' -ForegroundColor Cyan
& "$bt\d8.bat" --lib $jar --min-api 23 --output "$b\dexout" "$b\classes.zip" 2>&1 | Out-Null
if (-not (Test-Path "$b\dexout\classes.dex")) { Write-Host 'd8 失败' -ForegroundColor Red; exit 1 }

Write-Host '== 5/6 aapt2 link + 塞 dex ==' -ForegroundColor Cyan
& "$bt\aapt2.exe" compile --dir "$b\res" -o "$b\res.zip" 2>&1 | Out-Null
& "$bt\aapt2.exe" link -o "$b\base.apk" -I $jar --manifest "$b\AndroidManifest.xml" `
    -R "$b\res.zip" --auto-add-overlay --min-sdk-version 23 --target-sdk-version 34 2>&1 | Out-Null
if (-not (Test-Path "$b\base.apk")) { Write-Host 'aapt2 失败' -ForegroundColor Red; exit 1 }
$zip = [System.IO.Compression.ZipFile]::Open("$b\base.apk", 'Update')
$e = $zip.CreateEntry('classes.dex')
$st = $e.Open()
$bytes = [System.IO.File]::ReadAllBytes("$b\dexout\classes.dex")
$st.Write($bytes, 0, $bytes.Length)
$st.Close()
$zip.Dispose()

Write-Host '== 6/6 zipalign + 签名 ==' -ForegroundColor Cyan
if (-not (Test-Path "$b\debug.keystore")) {
    & $kt -genkeypair -keystore "$b\debug.keystore" -alias androiddebugkey -storepass android `
        -keypass android -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=PhoneAgent,O=Local,C=CN" 2>&1 | Out-Null
}
& "$bt\zipalign.exe" -f 4 "$b\base.apk" "$b\aligned.apk" 2>&1 | Out-Null
& "$bt\apksigner.bat" sign --ks "$b\debug.keystore" --ks-pass pass:android --key-pass pass:android `
    --ks-key-alias androiddebugkey --out "$b\PhoneAgent.apk" "$b\aligned.apk" 2>&1 | Out-Null

if (Test-Path "$b\PhoneAgent.apk") {
    $kb = [math]::Round((Get-Item "$b\PhoneAgent.apk").Length / 1KB, 1)
    Write-Host "OK -> $b\PhoneAgent.apk ($kb KB)" -ForegroundColor Green
} else {
    Write-Host '签名失败' -ForegroundColor Red
    exit 1
}
