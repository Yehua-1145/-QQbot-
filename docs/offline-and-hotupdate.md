# 离线部署与热更新

## 一、离线依赖包（解决 apt 装不上）

### 为什么需要

容器里装 QQ 要拉 300 个 apt 依赖。网络稍差就会遇到：

```
Temporary failure resolving 'mirrors.aliyun.com'
Release file ... is not valid yet        ← 手机时间不准
SSLHandshakeException                    ← VPN 拦了 TLS
```

### 怎么用

1. 下载 `Botagent-离线依赖包.zip`（约 205 MB）
2. 解压到手机根目录，得到：

```
/sdcard/botagent-deps/*.deb     250 个依赖
/sdcard/rootfs.tar.gz           26 MB，容器根文件系统
```

3. App 第 3 步：

```
① 创建容器        ← 自动用 /sdcard/rootfs.tar.gz，不再联网下载
装进容器          ← 装你自备的 QQ.deb
离线装依赖        ← 新增按钮，把 botagent-deps 全 dpkg 掉，完全不联网
② 安装 NapCat
② 启动协议端
```

整个部署不再依赖 apt 与网络。

### 包里有什么 / 没有什么

```
✓ Ubuntu 22.04 rootfs
✓ QQ 需要的全部 arm64 依赖（GTK3 / Xvfb / libnss3 / 字体 / jq / curl …）
✗ 不含腾讯 QQ 客户端（请自行从官方渠道获取 arm64 deb）
```

---

## 二、热更新（不重装 APK 换代码）

### 能更新什么

```
aibot/*.py      机器人本体（AI、QQ、控制台后端）
*.html          界面（console.html / setup.html）
```

不能更新：Java 层（要让用户装 APK）。

### 包格式

一个 zip，两种放法都行：

```
hot.zip
├── aibot/agent.py          → 写到 files/aibot/
├── aibot/qq_bot.py
└── console.html            → 写到 files/web/
```

也可以把 .py 直接平铺在 zip 根目录。

### 怎么用

设置 → 关于 → 「热更新」：

```
输入 zip 地址（http(s):// 或 file:///sdcard/hot.zip）
点「应用热更新」
→ 解包、备份旧文件到 files/aibot/backup-<时间>/
→ 重启机器人后生效
```

### 生效顺序

```
界面   files/web/console.html 优先，没有才用 APK 内置的
代码   files/aibot/*.py 直接覆盖；旧版备份在 backup-*/ 里
```

回滚：把 backup 目录里的文件拷回去，重开 App。

### 安全考虑

```
· 只接受 .py 与 .html，不会执行 shell
· 可选 sha256 校验（接口参数 sha256）
· 每次覆盖前先备份，出错可回滚
· 默认不开启自动更新，必须手动填地址
```

---

## 三、这套方案的价值

| 场景 | 以前 | 现在 |
|---|---|---|
| 首次部署 | 40 分钟，全靠网络，VPN 一拦就卡死 | 约 5 分钟，全离线 |
| 改几行 Python | 重新打包 51 MB APK 再装 | 一个 100 KB zip 热更新 |
| 改界面文案 | 同上 | 同上 |
