# Botagent v2（单 APK 版）

> **把闲置手机变成会用手机的 AI 助手。**
> 不用电脑、不用 root、全程本机。

它不止会聊天 —— 能真的读屏幕、点按钮、滑页面，帮你查电量、开 App、搜东西、定提醒。

**这是实验分支**（`v2-embedded-runtime`）。想要稳定的、能连 QQ 的版本，请用 [main 分支的 v1.1](https://github.com/Yehua-1145/-QQbot-)。

> ⚠️ **当前版本（2.0.9）明确不稳定**：整条链路只在一台小米 6 / Android 9 上验证过。
> 已知问题见文末「已知限制」。适合折腾，不适合当正式服务。

---

## 它和别的手机 bot 差在哪

|  | 这个项目 | 常见手机 bot |
|---|---|---|
| 要电脑吗 | **不要**，一个 APK | 多数要（协议端跑 PC） |
| 要 root 吗 | **不要** | 部分要 |
| 能操作手机吗 | **能**（无障碍 12 类工具） | 基本不能 |
| 数据去哪 | **全在本机** | 常走第三方中转 |
| 首次部署 | 约 10 分钟，需自备 QQ 安装包 | 5 分钟，但要电脑 |

诚实说明：**首次部署不是「一键」**。因为不能随包分发 QQ 客户端，你得自己准备一个 arm64 的 QQ 安装包。之后开机即用。

---

## 装法

### 方式 A：手机直接装（推荐）

1. 到 [Releases](https://github.com/Yehua-1145/-QQbot-/releases) 下载
   `Botagent-v2.0-beta.apk`（约 52 MB，内含 Python 运行时 + NapCat）
2. 手机上点开安装 → 按 4 步向导走
3. 登录成功后自动进控制台

> `versionName 2.0.9` / `versionCode 114`
> `SHA256 ED2FD889E194DAE14DB7D5BB689A8349ECB5EEFBE3058208BC14ED59770F506E`

> 小米/红米要先开：**设置 → 更多设置 → 开发者选项 → USB 安装**，
> 否则可能提示「安装被拒绝」。装不上的话从手机浏览器直接点开 APK 也行。

### 方式 B：电脑端部署（轻量）

`deploy/pc-lite/` 是**纯脚本**方案，脚本合计 **4 KB**，不要 Python、不要运行时、不联网下载：

```
deploy/pc-lite/
├── deploy.ps1          3.8 KB   找 adb → 装 APK → 启动
├── 一键部署.bat          0.3 KB   双击运行（调上面那个 ps1）
└── Botagent.apk                 把 APK 放这（或 -Apk 指定）
```

用法：

```powershell
# 双击「一键部署.bat」即可；或命令行：
.\deploy.ps1                      # 自动挑设备、装同目录 APK、启动
.\deploy.ps1 -A11y                # 顺手打开无障碍，不用手点
.\deploy.ps1 -Serial 3ed565aa     # 多台手机时指定
.\deploy.ps1 -NoLaunch            # 只装不启动
```

前提：电脑上有 `adb`（手机 platform-tools，约 12 MB）。脚本按顺序找：
本目录 → `platform-tools\` → PATH → 常见 SDK 路径。

> 对比：v1.1 的电脑端是 PyInstaller 打的 exe（11 MB，还带 tesseract 语言包，整个目录 46 MB）。
> 这版只留脚本，**体积降了 99%**，代价是要求电脑上有 adb。

---

## 四步向导

```
① 填账号      QQ 号 + API Key（DeepSeek / OpenAI / 通义 都行）
② 开权限      无障碍（读屏 + 代点按）+ 电池白名单
③ 准备环境    建容器（26 MB）→ 装 NapCat（内置）→ 导入 QQ 安装包 → 启动协议端
④ 启动        启动机器人 → 扫码 → 登录成功自动进控制台
```

控制台 5 个页签：

| 页签 | 能干什么 |
|---|---|
| 对话 | 发指令、流式回复、工具调用可见 |
| 状态 | 服务 / QQ / 协议端 / 端口 / 模型 / 图库 |
| 日志 | 实时跟随、刷新、复制 |
| 任务 | 定时任务列表、手动执行 |
| 设置 | 人设、接入、深度抓图 + 白名单、**群聊**、图库换新、备份恢复、重启协议端 |

---

## 关于 QQ：还需要一个协议端

APK 负责"大脑"（AI、工具、控制台、容器）。**QQ 登录需要协议端**，那个没法随包分发（涉及腾讯客户端）。

v2 的做法：在**手机自己的容器里**装 NapCat，不需要电脑也不需要 AstrBot：

```
App 内置 NapCat（34 MB，官方原包 + 许可证）
  → 装进容器里的 QQ（resources/app/napcat + loadNapCat.cjs）
  → 启动协议端（Xvfb + QQ --no-sandbox）
  → NapCat 出码，扫码登录
  → OneBot ws 监听 127.0.0.1:3001
  → qq_bot 连上 → online=true
```

**你需要做的只有一件**：从官方渠道拿一个 arm64 的 QQ 安装包（`QQ_*_arm64_01.deb`），在向导第 3 步导入。

### 法律边界（请勿越线）

```
✓ 本项目不包含、不下载腾讯 QQ 客户端
✓ NapCat 按许可证原样内置，附全文与来源声明（assets/napcat/）
✓ 非商业，与腾讯、NapCat 官方均无隶属关系
✗ 不要往仓库/Release 里传 QQ 安装包
```

---

## 它里面装了什么

```
Botagent.apk (52.2 MB)
├── assets/runtime.zip      Python 3.14.10 + libssl/libcrypto/sqlite3/zlib（Termux 官方包）
├── assets/napcat/          NapCat.Shell.zip 34 MB + 许可证
├── assets/aibot/*.py       AI 逻辑、工具、控制台
├── assets/setup.html       4 步向导
├── assets/console.html     5 页签控制台
└── 原生层：无障碍服务 + 前台服务 + 容器（proot）+ 原生底部导航
```

启动流程：

```
点「启动机器人」
  → 解压运行时（45 MB，仅首次）
  → python 自检
  → 起 webui.py（控制台，默认 8080，被占自动换端口）
  → 起 qq_bot.py（连 3001）
  → 前台服务常驻，挂了自动重启（最多 5 次）
```

---

## 已知限制

```
· 实验版，接口和行为还可能变
· 二维码约 2 分钟过期，过期点「立即刷新」重拉
· 没有自动拉起：App 重启后要手动点「启动协议端」再「启动机器人」
· 群聊配置改完要点「重启机器人」才生效
· NapCat 偶发启动失败，重点一次通常就好
· MIUI/华为等 ROM 会杀后台 —— 建议给 App 开「无限制」省电策略
· 每次重装 APK，无障碍都会被系统关掉，需要重新开一次
```

---

## 目录结构

```
apk_src_v2/          v2 的 Android 工程（不用 Gradle，走 aapt2 + javac + d8）
aibot/               机器人本体（AI、工具、控制台后端，v1.1/v2 共用）
deploy/pc-lite/      电脑端轻量部署（纯脚本 4 KB）
deploy/pc/           v1.1 的 exe 部署器（历史遗留，46 MB）
build.ps1            一键构建 APK
BUILD.md             构建说明 + 踩过的坑
```
