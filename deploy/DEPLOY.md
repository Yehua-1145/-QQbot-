## 部署方式（有 root / 无 root）

这套东西的核心是 **Termux + proot-distro 里的 Linux QQ + NapCat**，
`proot` 本身**不需要 root**。root 只是让下面几件事更省心，不是必须。

### 一句话对比

| 能力 | 有 root（Magisk） | 无 root（纯 Termux） |
|---|---|---|
| 跑 bot / WebUI / 抓图 | ✅ | ✅ |
| Linux QQ + NapCat 登录 | ✅ | ✅ |
| 掉线自动重启（watchdog） | ✅ 可直接 `am force-stop` 重启 | ⚠️ 只能重启容器内进程 |
| 锁屏后台保活 | ✅ 加白名单 + root 改 oom 值 | ⚠️ 靠系统白名单 + 前台通知 |
| 绑核 / 调频（性能优化） | ✅ | ❌ 没有权限 |
| 截图 / 模拟点击 | ✅ | ❌ |
| 静默装 APK | ✅ | ❌ 需手动点确认 |
| 崩溃后自启动 | ✅ 开机脚本 | ⚠️ Termux:Boot 插件 |

**结论**：给别人用的话，**无 root 也能跑**，只是掉线后可能得手动拉一次，
而且少了绑核优化（低端机上会慢一点）。

### 有 root 的部署

```bash
# 1) Termux 里
pkg update && pkg install proot-distro python
proot-distro install ubuntu

# 2) 装机器人代码
mkdir -p ~/aibot && cd ~/aibot
# 把 aibot/*.py 拷进来

# 3) 配置
cp config.example.json config.json
chmod 600 config.json
vi config.json        # 填 api_key / owner_uid / allowed_groups

# 4) 启动
python webui.py &     # 控制台 8080
python qq_bot.py &    # QQ 机器人
```

root 相关脚本在 `root_scripts/`（watchdog、绑核、NapCat 重启），
按需 `su -c` 调用即可，**不放也不会影响核心功能**。

### 无 root 的部署（推荐给其他人）

```bash
pkg install proot-distro python
proot-distro install ubuntu
proot-distro login ubuntu -- bash -c "
  apt update && apt install -y curl wget libgtk-3-0 libnss3
  # 装 Linux QQ + NapCat（略，见 aux_phone/ 里的步骤）
"
```

关键差异只有三处：

1. **启动脚本**：不用 `su -c`，直接 `nohup python qq_bot.py &`
2. **保活**：装 [Termux:Boot](https://f-droid.org/packages/com.termux.boot/)，
   把启动命令写进 `~/.termux/boot/start.sh`
3. **省电设置**：手机设置里给 Termux / QQ 开「无限制后台」+ 关电池优化

### 一条命令安装（推荐）

```bash
# 有网、有 Termux 就能跑
curl -fsSL https://raw.githubusercontent.com/<你>/<repo>/main/deploy/install.sh -o install.sh
bash install.sh
```

脚本会做的事（全部实测通过）：

```text
1. 检查 Termux / python，缺就 pkg install
2. 把 aibot/*.py 复制到 ~/aibot（或从仓库 clone）
3. 交互式问 5 个问题 → 写 config.json（chmod 600）
     · DeepSeek API Key
     · 你的 QQ 号（主人）
     · 要响应的群号
     · 机器人 QQ 号
     · 反馈邮箱
4. 随机生成 webui_token.txt（600）
5. 生成 start.sh / stop.sh / status.sh
6. 写 ~/.termux/boot/start-botagent.sh（配 Termux:Boot 插件即开机自启）
7. 打印控制台地址 + token
```

可选参数：

```bash
bash install.sh --with-napcat     # 顺带装 proot Ubuntu（Linux QQ 环境）
bash install.sh --dir ~/mybot     # 换安装目录
BOTAGENT_REPO=<git地址> bash install.sh   # 从仓库拉代码
```

装完只需要：

```bash
bash ~/aibot/start.sh     # 启动
bash ~/aibot/status.sh    # 看状态
bash ~/aibot/stop.sh      # 停止
```

### 卸载

```bash
bash uninstall.sh              # 停止 + 删程序，配置备份到 ~/botagent-config-backup.json
bash uninstall.sh --purge      # 连配置、token、备份一起删
bash uninstall.sh --purge --proot   # 再删掉 proot Ubuntu（500MB，含 Linux QQ）
bash uninstall.sh -y           # 不问，直接执行
```

**只杀安装目录下的进程**（按 `/proc/<pid>/cmdline` 匹配），
不会误杀同机其它实例 —— 这点实测过：卸载测试目录后生产实例仍在跑。

### 脚本实测记录（2026-11 手机真机）

```
安装：19 个文件 + config.json(600) + token + 3 个控制脚本 + 开机自启
卸载（默认）：程序目录已删，配置备份保留，自启已移除
卸载（--purge）：备份同时删除
```

过程中修掉的两个坑：

| 坑 | 现象 | 修法 |
|---|---|---|
| `GROUPS` 是 bash 内置变量 | 群号写成 `[0]` | 变量改名 `BOT_GROUPS` |
| `pkill -f qq_bot.py` 太宽 | 卸载测试目录把生产实例杀了 | 改成扫 `/proc/*/cmdline`，只杀 cmdline 含安装目录的 |

`install.sh` 要做的事：

```text
1. 检查 Termux / python3 / proot-distro
2. 缺啥装啥（pkg install -y ...）
3. 拉代码到 ~/aibot
4. 第一次运行：交互式问 api_key / owner_uid，写 config.json（chmod 600）
5. 生成 webui_token.txt（随机 12 位）
6. 注册 Termux:Boot 自启
7. 打印控制台地址和 token
```

核心代码里有几个**必须配置**才能跑起来的项，缺了会在启动时打印提示而不是崩溃：

```
api_key        —— 没填时 WebUI 照常开，但对话会报「未配置 Key」
owner_uid      —— 没填时没有任何人有管理权（安全默认）
allowed_groups —— 空 = 任何群都不响应
```

### 首次运行会问什么

```text
DeepSeek API Key: sk-...
你的 QQ 号（主人）: 10001
要响应的群号（逗号分隔，可空）: 20001,20002
要不要开成人图源（仅主人可用）[y/N]:
```

### 安全默认值

| 项 | 默认 | 说明 |
|---|---|---|
| `allow_remote` | `false` | 危险接口只允许本机，局域网带 token 也拦 |
| `owner_uid` | `0` | 没配 = 没人有管理权 |
| WebUI token | 首次随机生成 | 存 `webui_token.txt`（600），不写死在代码里 |
| `config.json` | 600 | 含 API Key / SMTP 授权码，别提交到 git |

### 无 root 全自动 —— 真机验证记录（2026-11-04）

测试机：**MI 6 / Android 9 / 无 root**（序列号 <设备序列号>）

#### 环境检测

```
adb: D:\platform-tools\adb.EXE
设备: [('<设备序列号>', 'device')]
root: False          ← 确认无 root
Termux 已装: True
8080 监听: False     ← 还没装 bot，判断正确
```

#### 自动化执行

```
推送 go.sh: 0                       成功
Termux 前台: True                   am start 成功切前台
input text 'bash%s/sdcard/...'      命令敲进终端
input keyevent 66                   回车
```

Termux 内实际执行结果（从设备读回）：

```
FLOW_START Wed Nov 4 15:18:53 CST 2026
pwd=/data/data/com.termux/files/home
uname=aarch64
python=none
FLOW_END
```

`python=none` 是预期的 —— 新装的 Termux 没有 python，
真实部署时 `go.sh` 第一步就是 `pkg install -y python`。

#### 逐环节结论

| 环节 | 无 root 可行性 | 实测 |
|---|---|---|
| 检测设备 / 判断 root | ✅ | 通过 |
| 推送文件到 `/sdcard` | ✅ | 通过 |
| 唤醒屏幕 / 解除锁屏 | ✅ | 通过 |
| 打开 Termux 并确认前台 | ✅ | 通过 |
| 输入命令并回车 | ✅ | 通过 |
| 脚本在 Termux 内执行 | ✅ | 通过 |
| 判断服务是否启动 | ✅ 读 `/proc/net/tcp` | 通过 |

#### 测试中发现的三个必做前置

**1) Termux 安装包必须用官方新版**

本地那个 3.58 MB 的 `termux.apk` 是坏的：

```
INSTALL_PARSE_FAILED_NOT_APK
找不到中央目录结尾记录
```

换成 GitHub 官方构建（31.6 MB）后安装成功：

```
https://github.com/termux/termux-app/releases/download/v0.118.1/termux-app_v0.118.1+github-debug_arm64-v8a.apk
```

**2) 必须先授予存储权限**

否则 Termux 读不到 `/sdcard`，脚本取不到：

```bash
adb shell pm grant com.termux android.permission.READ_EXTERNAL_STORAGE
adb shell pm grant com.termux android.permission.WRITE_EXTERNAL_STORAGE
```

部署工具里已自动执行这两条。

**3) 首次启动要等 bootstrap 完成**

Termux 第一次打开会下载基础组件，界面显示欢迎信息。
**必须等到出现 `~ $` 提示符**，否则 `input text` 打进去的命令会丢。
实测约 40 秒。

#### 测试后的状态

测试只跑了标记脚本（**没有真的装 bot**），结束后已恢复：

```
Termux 已卸载
/sdcard/Download/botagent 已删除
设备回到测试前状态
```

---

## 新增：让 AI 动手操作手机（v1.0.4）

有 root 时，机器人在 QQ 里收到一句人话，就能真的去点屏幕：

```
你：打开哔哩哔哩，搜 安卓
它：① 读界面 → ② 按文字点搜索框 → ③ 填「安卓」→ ④ 点搜索 → ⑤ 回报结果
```

### 用到的工具（模型自动调用，你不用管）

| 工具 | 作用 |
|---|---|
| `ui_dump` | 读当前界面的按钮文字和坐标 |
| `ui_tap` | 按文字点按钮，找不到会返回候选 |
| `ui_type` | 往输入框填字 |
| `ui_swipe` | 滑动 / 翻页 |
| `ui_key` | 返回、Home、删除 |
| `ui_wait` | 等某段文字出现再继续 |
| `ocr_screen` / `ocr_tap` | 控件读不到时走 OCR（网页 / 游戏 / 图片界面） |
| `ocr_wait` / `ocr_find` | 等文字出现 / 自动滑屏找 |
| `icon_save` / `icon_tap` | 纯图标按钮：存一次模板，以后按图标点 |
| `see` | 纯图形界面：截图交给视觉模型（需配 vision_model） |

### 部署时会多一步

v1.0.4 起，点「开始部署」后**末尾会自动装 OCR 依赖**：

```
tesseract 5.5.4 + 中文语言包 chi_sim + python-numpy
```

耗时 1~3 分钟，**期间不要锁屏、不要拔线**。装失败了不影响聊天，
可以点界面上的 **「装OCR依赖」** 按钮重试，或在 Termux 里手动执行：

```bash
pkg install -y tesseract python-numpy
```

中文语言包已随安装包附带（`chi_sim.traineddata`，2.4 MB），不用联网下载。

### 边界

- 需要 root，无 root 只能用聊天和发图
- 网页 / 游戏界面靠 OCR，约 2~5 秒一屏
- 纯图标按钮要先用 `icon_save` 裁一次模板
- 纯图形界面（游戏画面）要配视觉模型（`config.json` 里的 `vision_model`）
- 涉及付款、删除、给别人发消息，它会先问你确认
- 这组工具只有主人能用，访客拿不到

