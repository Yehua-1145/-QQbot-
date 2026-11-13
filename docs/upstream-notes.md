# 同类项目调研笔记（2026-11-13）

调研目的：我们 v2 卡在「proot 里 QQ 起不来 / 必须借 AstrBot 容器」和「系统通道不稳」，
看看同类项目怎么解的。下面按可借鉴程度排序，**只记录读到的代码事实，不含推测**。

---

## 一、JunWan666/astrbot-for-android（★375，最值得参考）

单 APK 内置 PRoot Ubuntu + AstrBot + NapCat + Linux QQ，ARM64、Android 8+、**无需 Root**。
技术栈：Kotlin + Jetpack Compose + PRoot + 原生 runner。

### 1.1 PRoot 的确切启动方式（`app/.../runtime/BootstrapRuntime.kt`）

```kotlin
ProcessBuilder(listOf(
    File(nativeDir, "libprocess-runner.so").path,   // 原生 runner：先 exec 它，再 exec proot
    File(nativeDir, "libproot.so").path,
    "--kill-on-exit", "--link2symlink", "-0", "-r", guestRoot.path,
    "-b", "/dev", "-b", "/proc", "-b", "/sys",
    "-b", "${sharedMemory.path}:/dev/shm",          // cache/guest-shm → /dev/shm
    "-b", "${persistent.path}:/persistent",
    "-b", "${manager.path}:/manager",
    "-b", "${sharedFiles.path}:/android-share",
) + hostPathBindings + listOf(                      // 每项同时绑 /data/data 与 /data/user/0 两种拼写
    "-w", "/root",
    "/usr/bin/env", "-i", "HOME=/root", "USER=root", "TMPDIR=/tmp",
    "PATH=/manager/bin:/usr/local/sbin:...:/bin", "ANDROID_SHARED_DIR=/android-share",
    "LANG=C.UTF-8", "TERM=xterm-256color", "SHELL=/bin/bash",
) + command)
```

进程环境（**关键**）：

```kotlin
environment().apply {
    remove("LD_PRELOAD")                    // 必须清掉，否则 Android 的 linker 会炸
    put("LD_LIBRARY_PATH", nativeDir.path)  // 指向 APK 的 jniLibs，而不是 guest 的 lib
    put("PROOT_LOADER", File(nativeDir, "libproot-loader.so").path)
    put("PROOT_LOADER_32", File(nativeDir, "libproot-loader32.so").path)
    put("PROOT_TMP_DIR", tmp.path)          // cache/proot-tmp
    put("TMPDIR", "/tmp"); put("HOME", "/root")
}
```

要点：
- **proot 本身以 jniLibs 里的 `libproot.so` 形式分发**，由 `libprocess-runner.so` 间接 exec，
  避开 Android 10+ 对 app 私有目录 `exec` 的限制（我们踩过 `inaccessible or not found`）
- `/dev/shm` 必须**自建目录再 bind**（Android 没有可写的 /dev/shm）
- 同一路径要同时绑 `/data/data/...` 和 `/data/user/0/...` 两种写法，因为 procfs 里会暴露另一种

### 1.2 QQ 的启动方式（`assets/runtime/desktop/qq.sh`）

```bash
export DISPLAY=:20
export XAUTHORITY="$desktop_root/Xauthority"
xdpyinfo -display "$DISPLAY" >/dev/null
cd "$desktop_root/qq/opt/QQ"
exec env HOME=... XDG_CONFIG_HOME=... XDG_DATA_HOME=... XDG_CACHE_HOME=... \
    XDG_RUNTIME_DIR="$desktop_root/qq-runtime" \
    dbus-run-session -- "$desktop_root/guest-compat" --profile "$qq_binary" \
    --no-sandbox --disable-gpu --disable-dev-shm-usage --in-process-gpu \
    --disable-gpu-compositing --disable-features=Vulkan
```

和我们的差异：
| 他们 | 我们 |
|---|---|
| `dbus-run-session` 包一层 | 没有（日志里满是 dbus 连接失败，虽不致命） |
| `guest-compat` 预加载 `libguest-compat.so` | 我们用 AstrBot 的 `libnapcat_launcher.so` |
| `--disable-features=Vulkan` | 没有 |
| 独立 `HOME`/`XDG_*` 到桌面目录 | 用 `/root` |
| `DISPLAY=:20` + `XAUTHORITY` 文件 | `Xvfb :101`，无 XAUTHORITY |

`guest-compat` 是个 Python 包装器，作用是注入 `libguest-compat.so` 并设置
`ASTRBOT_COMPAT_MEMFD=1`、`ASTRBOT_COMPAT_PROC_LOCKS=1`、`ASTRBOT_COMPAT_LOCK_HELPER=proc_locks.py`
——即在 proot 下补偿 memfd / 文件锁的行为。

### 1.3 NapCat 崩溃的官方级绕法（`NapCatStartupCompatibility.kt`）★最有价值

他们**只在特定组合**上做处理：
`arm64-v8a` + QQ `3.2.34-53644` + NapCat `4.18.41`。

处理方式是改 `config/napcat.json` 的 `bypass`：

```json
"bypass": { "hook": false, "window": false, "module": false, "process": false,
            "container": false, "js": false }
```

代码注释写得很明确：

> Module/Container crash at startup; the remaining four together also crashed
> after login (SIGSEGV, Worker 256). Upstream recommends not enabling these bypasses.
> 参考 NapCat issue #1813 的评论。

**这几乎就是我们 SIGTRAP 的答案**：容器里 `hook/window/module/process/container/js`
只要开着就会在启动或登录后崩。

### 1.4 NapCat 安装布局

```
/opt/qq/resources/app/app_launcher/napcat/          ← NapCat 解压在这
/opt/qq/resources/app/loadNapCat.js                 ← 新建
/opt/qq/resources/app/package.json                  ← 改 main
```

`loadNapCat.js` 内容（ESM 动态 import）：

```js
const path = require('node:path');
const { pathToFileURL } = require('node:url');
import(pathToFileURL(path.join(__dirname, 'app_launcher/napcat/napcat.mjs')).href);
```

我们用的是 `resources/app/napcat/` + `loadNapCat.cjs`，路径和模块形态都不同。
如果照他们来，好处是**不覆盖 `major.node`**，升级 NapCat 只换目录。

### 1.5 运维细节（值得抄）

- 「进程起来了」不算运行中：**后台探测确认就绪**才计入运行数
- 单实例锁：启动前查配置里的实际端口（含默认 6185/6199），已有实例响应就保留原进程
- 「确认是自家环境 + 超过启动宽限期 + 连续无响应」才允许结束，**从不按端口/进程名批量 kill**
- 不依赖读 `/proc/net/tcp`（Android 限制）
- 一键备份/恢复、凭据页（重置后台口令）、日志页、局域网访问开关
- 完整包带 SHA256SUMS；初始化前校验 APK 内镜像摘要

---

## 二、pinganbbOvO/ai-companion-kit（★568）

拆成三个独立包：`companion`（人设/记忆/拟人化发送/唤醒策略）、`phone-mcp`、`qzone`。

### phone-mcp（对我们系统通道最有用）

- **不用无障碍打字**：走 adb，可选装 **ADBKeyboard** 做中文输入（广播发文本）
- 34 个工具：点按、滑动、输入、截图、录屏**抽关键帧**、连招（宏）、返回
- 「连招」= 把「打开 App → 点几个位置 → 输入 → 提交」打包成一个原子操作，减少中间态
- 手机侧**不需要装东西**（除 ADBKeyboard 可选），只要无线调试/USB

启示：我们现在系统通道最大的失败点是「点输入框拿不到焦点 → setText 失败」。
改成 **ADBKeyboard 广播** 或 **input text / clipboard 粘贴** 会稳得多。

### qzone

发说说/看动态/点赞/评论都做了 **限额**，这和我们「防风控」是同一类思路。

---

## 三、Futureppo/napcat-login-status-monitor（★9，小而准）

Kotlin + Compose + WorkManager + MVVM 的原生 App：

- 每个监控项可配：API 地址、Token、QQ 号、查询间隔（秒）、开关
- **用 NapCat 的 WebUI/API 判断在线状态**，不是看进程
- 前台服务 + 每个监控独立间隔 + **15 分钟兜底周期任务**
- 掉线发通知（声音/震动）

启示：我们的看门狗现在只探「进程在不在」，探不到「在线但被踢」。
应该加一层：定期打 OneBot `get_login_info`，失败才算掉线。

---

## 四、其他

- **Gsjsjzhznsz/BandQQ**（★18）：手环快应用 + 安卓同步器，OneBot v11 转发 QQ 消息。
  思路是「安卓端只做桥接，业务放别处」，和我们「协议端 + 业务 bot」分层一致。
- **Kevinwu901113/dsh-dot**（★13）：给 AI 一部自己的安卓手机 + QQ + 记忆，和本项目定位最接近，
  可作为产品形态参考（未细读代码）。

---

## 五、落到我们身上的修正清单

按「能不能立刻降低故障率」排序：

1. **NapCat `bypass` 全关**（hook/window/module/process/container/js）
   期望直接解决容器里 QQ 的 SIGTRAP。需要重启协议端 + 重新扫码，风险可控、可回滚。
2. **proot 启动参数补齐**：`--kill-on-exit`、`PROOT_LOADER`/`PROOT_LOADER_32`、
   `PROOT_TMP_DIR`、`-b <cache>/guest-shm:/dev/shm`、同时绑 /data/data 与 /data/user/0 两种写法
3. **QQ 启动包 `dbus-run-session` + `--disable-features=Vulkan` + 独立 XDG 目录**
4. **NapCat 布局改成 `app_launcher/napcat` + `loadNapCat.js`（ESM）**，不覆盖 `major.node`
5. **掉线检测改成 API 探测**（`get_login_info`），而不是只看进程
6. **系统通道打字换 ADBKeyboard**（广播发中文），不再赌无障碍焦点
7. 服务「就绪」判定：端口/接口探测通过才算运行中
8. 禁止按进程名批量 kill；只结束自己启动的 PID

> 备注：以上都是读源码得出的事实，未在本机验证。v2 目前不在真机运行，
> 任何一条要落地都需要一次「重启协议端 + 扫码」，不要一次全改。
