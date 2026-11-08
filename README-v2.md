# Botagent v2（单 APK 版）

> **一个 APK，装完就能用。** 不需要 Termux、不需要电脑、不需要 root。
> Python 运行时直接打进了 APK 里，手机上点一下就在本地跑起来。

**这是实验分支**（`v2-embedded-runtime`）。想要稳定的、能连 QQ 的版本，请用 [main 分支的 v1.1](https://github.com/Yehua-1145/-QQbot-)。

---

## 装法（四步，五分钟）

### 1. 下载 APK

到 [Releases](https://github.com/Yehua-1145/-QQbot-/releases) 找 **v2.0.0-beta**，下载
`Botagent-v2.0-beta.apk`（约 34 MB）。

> 小米/红米要先开：**设置 → 更多设置 → 开发者选项 → USB 安装**，
> 否则可能提示「安装被拒绝」。装不上的话从手机浏览器直接点开 APK 也行。

### 2. 打开 App，填两个空

```
你的 QQ 号   ← 填你当机器人用的那个号（建议小号）
API Key      ← DeepSeek / OpenAI / 通义 都行，可以先空着，之后在控制台填
```

点「保存」，右上角「配置」卡片会变绿。

### 3. 开无障碍（可选，但推荐）

点「打开无障碍设置」→ 在「已下载的服务」里找到 **Botagent** → 打开 → 按返回键回来。

状态自动变绿。开了之后 AI 才能读屏幕、替你点按、截图。

> Android 的规矩：**每次重装 APK，无障碍都会被系统关掉**，重新开一次即可。

### 4. 点「启动机器人」

首次会解压运行时（约 45 MB，30~60 秒，有进度条）。

看到「已启动」后点「进入控制台」，或者手机浏览器打开：

```
http://127.0.0.1:8080/app
```

---

## 关于 QQ：还需要一个协议端

APK 负责"大脑"（AI、工具、控制台）。**QQ 登录需要协议端**，那个没法塞进来（涉及腾讯客户端分发）。

推荐做法：装 **AstrBot 安卓版**（自带 Ubuntu + Linux QQ + NapCat）：

```
轻量版 95 MB  https://github.com/MuFengDR/AstrBot-Bubble-Android-App/releases
完整版 1 GB   https://github.com/JunWan666/astrbot-for-android/releases
```

装完在里面扫码登录 QQ，把 **WebSocket 端口设成 3001**，这边的「QQ 协议端」卡片就会变绿，机器人就能在 QQ 里说话了。

> 只用手机控制台聊天（不走 QQ）的话，这一步可以跳过。

---

## 它里面装了什么

```
Botagent.apk (34 MB)
├── Python 3.14.10          ← 从 Termux 官方仓库打的包，跑在 App 私有目录
├── libssl / libcrypto      ← HTTPS 能用，pip 也能用
├── libsqlite3 / zlib / ...
├── websocket-client        ← 唯一的第三方依赖
├── aibot/*.py              ← AI 逻辑、工具、控制台（跟 v1.1 同一套代码）
└── 原生层：无障碍服务 + 前台服务 + 后台保活
```

启动流程：

```
点「启动机器人」
  → 解压 runtime.zip（3141 个文件）
  → 还原符号链接
  → python -c "print('PY_OK')" 自检
  → 起 webui.py（控制台，默认 8080）
  → 起 qq_bot.py（连 NapCat）
  → 前台服务常驻，挂了自动重启（最多 5 次）
```

几个细节：

| 机制 | 说明 |
|---|---|
| **端口自动避让** | 8080 被占了自动换 8081/8082，App 里显示的是实际端口 |
| **前台服务** | 通知栏常驻，切后台不会被杀 |
| **开机自启** | 监听 `BOOT_COMPLETED`，重启后自动拉起 |
| **崩溃重启** | 守护线程每 8 秒检查，任一进程挂了就重启 |
| **路径解耦** | 所有路径走环境变量，所以 v1.1（Termux）和 v2（内置）同一套代码 |

---

## 已知限制

```
· 实验版，接口和行为还可能变
· MMUI/华为等 ROM 会杀后台 —— 建议在系统设置里给 Botagent 开「无限制后台」+ 关电池优化
· targetSdk 是 23（为了能用 LD_LIBRARY_PATH 跑内置 Python），
  后果是部分 Android 14+ 机型安装时会提示「应用针对旧版 Android」
· 无 root 时不能执行 shell 命令、不能静默装应用（这是 Android 的限制，不是 bug）
· 没有自动更新，要手动下新 APK
```

---

## 和 v1.1（稳定版）的区别

| | v1.1（main） | v2（本分支） |
|---|---|---|
| 需要 Termux | 要 | **不要** |
| 需要电脑 | 首次要 | **不要** |
| 安装步骤 | 4 步（含开 USB 调试） | 填两个空 + 点启动 |
| APK 体积 | 137 KB（纯控制台） | 34 MB（含运行时） |
| 稳定性 | 验证过 | 实验性 |
| QQ 协议端 | 同样要 AstrBot | 同样要 AstrBot |

---

## 反馈

实验分支的问题欢迎直接开 Issue，标题带 `[v2]` 前缀，方便区分。

```
手机型号 + Android 版本：
哪一步卡的：
App 里显示的日志（设置 → 启动机器人 → 下面那块日志区）：
```
