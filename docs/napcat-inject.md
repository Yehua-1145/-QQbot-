# NapCat 是怎么装进 QQ 的（Linux 半自动方案）

> 这份文档是**兜底资产**：万一 NapCat 上游哪天消失（同类项目 SnowLuma 的主仓库已于 2026-11 变成 404），
> 我们仍然知道自己做了什么、怎么再做一遍。

## 为什么需要这一步

NgCat 的 `NapCat.Shell.zip` 里**没有** `napcat.sh`（那是 Windows 的 `launcher.bat` 分支），
所以在 Linux/容器里不能按 Windows 方式启动。官方给的办法是「手动安装」：
把 NapCat 塞进 QQ 的 `resources/app`，然后改 QQ 的入口，让 QQ 启动时先加载 NapCat。

参考：[NapCat 官方文档 · Linux Shell 手动安装](https://napneko.github.io/guide/boot/Shell-Linux-SemiAuto)

## 三个动作

假设：

```
QQ       /opt/QQ
NapCat   /opt/napcat（NapCat.Shell.zip 解压后的内容）
```

### 1. 把 NapCat 放进 QQ

```bash
cp -a /opt/napcat /opt/QQ/resources/app/napcat
```

### 2. 写加载器

路径：`/opt/QQ/resources/app/loadNapCat.cjs`

```js
const path = require("node:path");
const { pathToFileURL } = require("node:url");
if (process.argv.includes("--no-sandbox")) {
    import(pathToFileURL(path.join(__dirname, "napcat/napcat.mjs")).href);
} else {
    const original = require("./package.napcat-original.json");
    require(path.resolve(__dirname, original.main));
    setTimeout(() => {
        global.launcher.installPathPkgJson.main = original.main;
    }, 0);
}
```

作用：

```
带 --no-sandbox 启动（我们的容器里就是这么起的）→ 直接加载 napcat.mjs
不带 → 先按原入口起 QQ，再把 main 改回去（让 QQ 自己的更新/校验不炸）
```

### 3. 改 QQ 的入口

```bash
QAPP=/opt/QQ/resources/app
# 备份原入口（只备一次）
[ -f $QAPP/package.napcat-original.json ] || cp -a $QAPP/package.json $QAPP/package.napcat-original.json

# 用 jq 把 main 指向加载器
jq '.main = "./loadNapCat.cjs"' $QAPP/package.napcat-original.json > $QAPP/package.json

# 核对
grep -o '"main"[^,]*' $QAPP/package.json
# 期望： "main": "./loadNapCat.cjs"
```

### 4. 启动

```bash
export DISPLAY=:99
pgrep Xvfb >/dev/null || (nohup Xvfb :99 -screen 0 1080x1920x24 >/tmp/xvfb.log 2>&1 &)

cd /opt/QQ
nohup ./qq --no-sandbox > /tmp/napcat.log 2>&1 &
```

容器里还需要 `/dev/shm`（否则 Electron 会 FATAL）：

```bash
mkdir -p /dev/shm && chmod 1777 /dev/shm
# proot 启动时：-b <rootfs>/dev/shm:/dev/shm
```

## 成功的样子

```
$ netstat -tln | grep 6099
tcp6 0 0 :::6099 :::* LISTEN          ← NapCat WebUI

$ grep 二维码 /tmp/napcat.log
请扫描下面的二维码，然后在手Q上授权登录：
二维码解码URL: https://txz.qq.com/p?k=...

$ ls /opt/QQ/resources/app/napcat/cache/qrcode.png
（147×147 的小图，控制台会另行生成大图）
```

登录后：

```
$ netstat -tln | grep 3001
tcp 0 0 127.0.0.1:3001 0.0.0.0:* LISTEN   ← OneBot v11 ws
```

> 3001 不是自动开的：NapCat 首次登录后会生成
> `napcat/config/onebot11_<QQ号>.json`，里面 `websocketServers` 默认是**空数组**。
> 需要写一条 ws server（127.0.0.1:3001）才会监听。详见 `docs/onebot-port.md`。

## 环境变量（App 内的脚本用的是这套）

```
PROOT_TMP_DIR   <app>/cache
PROOT_LOADER    <app>/rt/usr/libexec/proot/loader
LD_LIBRARY_PATH <app>/rt/usr/lib
```

## 版本记录

```
NapCat     4.18.42（NapCat.Shell.zip）
sha256     02e5ff0f79916c1e04c81c1b4590056406fb4293f1f1300c955e71fd08b2829d
许可        Limited Redistribution License（允许随附分发，需附全文 + 来源，非商业）
本仓库位置  apk_src_v2/napcat_assets/NapCat-LICENSE.txt、NOTICE.txt
```

## 万一要换实现

`qq_bot.py` 只依赖 **OneBot v11 WebSocket**（默认 `ws://127.0.0.1:3001`）。换掉 NapCat 只要新实现满足：

```
· 提供正向 WebSocket（我们连它）
· 说 OneBot v11 的 JSON 事件与 API
· 支持 get_status / send_private_msg / send_group_msg（用到的子集见 docs/onebot-port.md）
```

候选：LLOneBot、Lagrange.Core、以及其它 OneBot v11 实现。
