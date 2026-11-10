# 自己构建 Botagent v2 的 APK

这个分支的 APK 比 v1.1 多了 **内置 Python 运行时**，所以构建分两步：

```
① 打运行时包   runtime.zip       （从 Termux 官方仓库拉 Python + 依赖）
② 打 APK       Botagent.apk      （aapt2 + javac + d8 + zipalign + apksigner）
```

全程**不需要 Gradle，也不需要 Android Studio**。

---

## 需要装什么

| 东西 | 版本 | 说明 |
|---|---|---|
| JDK | **8**（推荐）或 11 | `javac` 用来编译，`keytool` 用来生成签名 |
| Android SDK | platform **android-34** | 提供 `android.jar` |
| Android build-tools | **34.x** | 提供 `aapt2` / `d8` / `zipalign` / `apksigner` |
| Python | 3.8+ | 只用来打运行时包和改源码，不参与 APK 构建 |

设置三个环境变量（脚本会自动读）：

```powershell
$env:ANDROID_SDK_ROOT = 'D:\androidsdk'      # SDK 根目录
$env:JAVA_HOME        = 'C:\Program Files\Java\jdk1.8.0_xxx'
```

SDK 里需要这些路径：

```
$ANDROID_SDK_ROOT\platforms\android-34\android.jar
$ANDROID_SDK_ROOT\build-tools\34.0.0\aapt2.exe
                                     \d8.bat
                                     \zipalign.exe
                                     \apksigner.bat
```

> 目录名不一定是 `34.0.0`，脚本会用 `Get-ChildItem` 自己找最新的 build-tools。

---

## 第一步：打运行时包

```powershell
cd apk_src_v2

# 1. 从 Termux 仓库拉 python + 依赖，解到 runtime_build\files\
python ..\..\scripts\fetch_termux_python.py --out ..\..\build\runtime_build

# 2. 加一个第三方依赖（websocket-client，纯 python）
python ..\..\scripts\add_websocket_client.py --runtime ..\..\build\runtime_build

# 3. 打包成 runtime.zip（保留符号链接和权限位）
python ..\..\scripts\pack_runtime_zip.py `
    --files ..\..\build\runtime_build\files `
    --out   ..\..\build\runtime.zip
```

产物：`build\runtime.zip`，约 **16.6 MB**，里面 3141 个文件。

> 为什么要自己拉：Termux 的包是给 Termux 用的，路径前缀写死在
> `/data/data/com.termux/files/usr`，所以 App 里靠 `PYTHONHOME` 指过去。

---

## 第二步：准备要打进 APK 的资源

```
apk_src_v2\
  assets\setup.html          ← 首屏控制台（HTML）
  assets\runtime.zip         ← 第一步的产物，拷进来
  aibot_assets\*.py          ← 机器人的 python 代码（从源码\aibot 拷）
  res\                       ← 图标、无障碍配置
  src\com\botagent\*.java    ← 原生层
```

```powershell
mkdir apk_src_v2\aibot_assets -Force
copy ..\..\源码\aibot\*.py apk_src_v2\aibot_assets\
copy ..\..\build\runtime.zip apk_src_v2\assets\runtime.zip
```

---

## 第三步：打 APK

```powershell
cd apk_src_v2
powershell -ExecutionPolicy Bypass -File build.ps1
```

输出：

```
OK -> apk_src_v2\Botagent.apk (34.6 MB)
```

脚本做的事：

```
1  清理 classes / dexout / 中间 apk
2  javac          所有 src\**\*.java → classes\        （-source 8 -target 8）
3  zip            classes\ → classes.zip               （条目必须用 / 分隔）
4  d8             classes.zip → classes.dex            （--min-api 23）
5  aapt2 compile  res\ → res.zip
   aapt2 link     → base.apk（--min-sdk 23 --target-sdk 23）
   + 塞 classes.dex
5.5  注入 lib/arm64-v8a/*              （可选，见下）
5.6  注入 assets/aibot/*               （用 / 分隔，避开 aapt2 在 Windows 的坑）
6  zipalign → apksigner（自动生成 debug.keystore）
```

---

## 几个必须知道的坑

这些都是踩过的，写在这里省你时间。

### 1. `targetSdk` 必须是 23

Android 从 targetSdk ≥ 24 开始**无视 `LD_LIBRARY_PATH`**，应用命名空间里也
不允许从私有目录 `execve` 二进制。内置的 Python 需要 `LD_LIBRARY_PATH`
找到 `libssl.so.3` 这类版本化库，所以：

```xml
android:minSdkVersion="23"
android:targetSdkVersion="23"
```

代价：Android 14+ 安装时会提示「该应用针对旧版 Android」。可以继续装。

### 2. aapt2 在 Windows 会把嵌套 assets 写成反斜杠

如果直接把 `aibot/*.py` 放在 `-A` 的 assets 目录里，打出来的 APK 里条目名是
`assets/aibot\webui.py`，App 里 `getAssets().open("aibot/webui.py")` 会
`FileNotFoundException`。

**解法**：把 `aibot` 目录挪出 assets，构建后用 `ZipFile` 以
`assets/aibot/xxx` 的形式自己注入（build.ps1 的 5.6 步就是这么干的）。

### 3. zip 里的符号链接会变成「内容为目标名的小文件」

Termux 的 `usr/bin/python3` 是个软链、`usr/lib/libcrypto.so` 也是软链。
用 Python 的 `zipfile` 打包时会保留 `S_IFLNK` 标记，但 Android 的
`ZipInputStream` 读不到这个标记，解出来就是 14 字节的小文件。

**解法**：`RuntimeManager.restoreSymlinks()` 在解压后扫描 `usr/lib`、`usr/bin`、
`usr/libexec`，把「小于 256 字节、内容像路径、且目标存在」的文件删掉，
用 `Os.symlink()` 重建。真机上恢复 87 个。

### 4. 不要用 proot

一开始想把 `/data/data/com.termux/files/usr` 映射过去（Termux 的 python 前缀
写死的），所以带了 proot。后来发现：

```
proot 需要 libtalloc.so.2，而 Android 安装器只解压 lib*.so（单个 .so 后缀）
→ 版本化文件名的库会被静默丢弃
→ proot 起不来
```

**解法**：不用 proot，直接 `PYTHONHOME` + `LD_LIBRARY_PATH` 跑，一样能用，
还少一层转发。

### 5. d8 8.x 处理匿名内部类会崩

`A11yService$1.class` 这种匿名内部类会让 d8 抛
`NullPointerException: Cannot invoke "String.length()"`。

**解法**：所有回调都写成**顶层命名类**（`A11yServer`、`ShotCallback`、`LogPump`、
`PageClient`…），不用匿名类也不用内部类。

### 6. d8 的 `--lib` 是双横线

```
d8 --lib android.jar ...     ← 正确
d8 -lib android.jar ...      ← 被当成输入文件，报错
```

---

## 构建产物核对

```powershell
# 版本信息
aapt2 dump badging Botagent.apk | Select-String "package|sdkVersion"

# 里面有什么
python -c "import zipfile;z=zipfile.ZipFile('Botagent.apk');print([n for n in z.namelist() if n.startswith(('assets/','lib/'))])"
```

应该看到：

```
assets/runtime.zip            16.6 MB
assets/setup.html
assets/aibot/agent.py
assets/aibot/webui.py
assets/aibot/qq_bot.py
...
lib/arm64-v8a/libpython3.14.so
lib/arm64-v8a/libssl.so
...
```

---

## 装到手机上测

```powershell
adb install -r Botagent.apk

# 小米/红米可能报 INSTALL_FAILED_USER_RESTRICTED，换个法：
adb push Botagent.apk /sdcard/Download/Botagent-test.apk
adb shell am start -a android.intent.action.VIEW `
    -d file:///sdcard/Download/Botagent-test.apk `
    -t application/vnd.android.package-archive
```

> MIUI 有缓存：**必须用新文件名**，并且先
> `adb shell am force-stop com.miui.packageinstaller`，否则会装上旧包。

打开 App → 填 QQ 号 → 开无障碍 → 点「启动机器人」。
日志在 `/data/data/com.botagent/files/rt.log`（有 root 才能看）。

---

## 只想改 python 部分

不用重打运行时，只改 `aibot_assets/*.py` 然后重跑 `build.ps1` 即可（APK 里
的 `assets/aibot/` 会被替换），首次启动时 App 会把它们复制到
`files/aibot/`。

**注意**：`copyAibot` 是覆盖式复制，但如果 App 已经解压过运行时，改完 python
再装新 APK 时旧文件会被覆盖——想彻底干净就
`adb shell pm clear com.botagent`。

---

## 签名密钥（重要）

pk_src_v2/debug.keystore **提交在仓库里**（2.6 KB，密码 ndroid）。

为什么要提交：

`
CI（GitHub Actions）每次都是全新检出。仓库里没有 keystore 时，
build.ps1 会现场生成一把新的 → 产物签名与历史版本不一致
  · 装不到已有手机上（INSTALL_FAILED_UPDATE_INCOMPATIBLE）
  · 每次 CI 之间也互相覆盖不了
`

所以这把密钥的作用是让 **CI 与本地构建产出同一个签名**。
指纹（SHA-256）：886674ee71b265062a53175f3d33c3fa3435c65b6e12257776cc45751d16216

验证方式：

`powershell
apksigner verify --print-certs .\Botagent.apk
# 期望 SHA-256 digest: a886674e...
`

底线：

`
· 密钥公开 = 任何人都能签一个升级包覆盖安装
· 本项目非商业、不上架商店，接受这个取舍
· 若将来上架商店或正式发布 → 换新密钥，且绝不能进仓库
  （改用 CI Secret，或本地签名后手动上传）
`
