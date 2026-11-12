# 上游风险与快照策略

## 为什么要写这个

这个项目依赖两个**第三方**组件：

| 组件 | 作用 | 风险 |
|---|---|---|
| NapCat | 把 OneBot 协议注入官方 QQ 客户端 | 上游仓库可能消失；腾讯可检测注入 |
| QQ 客户端（arm64 deb） | 协议载体 | 用户自备；版本升级会改变检测面 |

已经发生过的事：

- `SnowLuma/SnowLuma`（NapCat 相关仓库）→ **404**
- NapCat 仓库里「频繁掉线」的 issue → **410 Gone**（被删）

所以**不能假设上游永远在**，必须自己留快照。

## 快照清单

构建 APK 需要两个二进制，它们不进 git（体积大），校验和记在
`vendor/manifests.json` 与 `vendor/SHA256SUMS.md`：

- `NapCat.Shell.zip`（约 34 MB）
- `runtime.zip`（约 16.6 MB，Python 运行时）

本地备份目录：`D:\backup\napcat-snapshot\`

校验方式（PowerShell）：

```powershell
Get-FileHash .\NapCat.Shell.zip -Algorithm SHA256
Get-FileHash .\runtime.zip -Algorithm SHA256
```

和 `vendor/manifests.json` 里的值比对，一致才能用于发版。

## 掉线与风控：社区共识

从公开讨论里整理出来的几条（都有一线用户实测）：

1. **Linux / Docker 版客户端检测最轻**
   Linux QQ + NapCat 属于这一类，是本项目的天然优势，不要换成 Windows 方案。

2. **同一个号多处同时在线必然被踢**
   手机 QQ 客户端 + 协议端同时登同一个号，腾讯会轮番踢下线。
   要稳定就「一号一处」。

3. **设备指纹频繁变化会被风控**
   反复重建容器、换目录、改配置，对腾讯来说就是「同一账号不停换设备」。

4. **登录频率过高会触发风控**
   固定 5 秒重连、一分钟内多次重登，都是异常特征。

5. **新版本 QQ 的注入检测更严**
   社区经验是较老的 NTQQ 版本更稳；因此本项目**不自动升级 QQ**，版本由用户自备并锁定。

6. **换号/养号是最有效的止损**
   被盯上的号继续折腾只会更糟；干净的老号能稳几个月。

## 本项目采取的对应措施

| 措施 | 落点 |
|---|---|
| 重连指数退避（5→15→30→60→120→300 秒） | `aibot/qq_bot.py` |
| 掉线计数 + 关闭码落盘（区分被顶号/风控） | `aibot/qq_bot.py` → `/api/qq` → 控制台状态页 |
| 容器已存在则不重建 | `apk_src_v2/.../Container.java` |
| 启动节流：5 分钟内且协议端在跑则跳过重启 | `apk_src_v2/.../Extension.java` |
| 账号锁定：只允许同一个 uin，防误切号 | `apk_src_v2/.../Extension.java` |
| 不自动升级 QQ / NapCat | 构建时锁定 deb 与 zip |
| 快照 + 校验和 | `vendor/` + 本地备份 |

## 如果 NapCat 彻底不可用

两条退路：

1. **换成其它注入实现**（LLOneBot 等），OneBot v11 协议一致，只需换启动方式
2. **换成独立协议实现**（Lagrange.Core），它有固定设备指纹与 keystore 快速登录

两条退路都通过「可插拔协议端」接入，详见 `docs/proto-backends.md`。
