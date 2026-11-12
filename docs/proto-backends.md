# 协议端后端（可插拔）

## 为什么做成可插拔

NapCat 只是「一种」协议端实现。它和别的实现说 **同一种协议（OneBot v11）**，
所以我们的机器人代码**不需要改**，只换后端启动方式即可。

```
qq_bot.py  ──ws──>  任意 OneBot v11 实现
                     ├── NapCat（注入官方 QQ，默认）
                     ├── LLOneBot（同类注入实现）
                     └── Lagrange.Core（独立协议实现，带设备指纹与 keystore）
```

## 配置

`config.json` 里两个键：

```json
{
  "proto_backend": "napcat",          // napcat | lagrange | remote
  "proto_ws": "ws://127.0.0.1:3001"   // 任意 OneBot ws 地址
}
```

| backend | 含义 |
|---|---|
| `napcat` | 由 App 负责拉起 NapCat（默认，走 Extension 里的脚本） |
| `lagrange` | 由 App 拉起本地 Lagrange.OneBot 可执行文件（需自己放进去） |
| `remote` | 协议端在别处，只连 `proto_ws`（家里服务器/NAS 上的 NapCat 都行） |

## 各后端说明

### NapCat（默认）

- 注入官方 Linux QQ，速度快、功能全
- 缺点：会被腾讯注入检测，可能掉线；上游不稳定
- 本项目已做：登录节流、账号锁定、重连退避、掉线计数

### LLOneBot

- 同为注入实现，协议一致
- 若要切换：把 `proto_backend` 改成 `napcat`，但启动脚本换成 LLOneBot 的启动命令即可
  （它是 Windows 生态为主，Linux 下需要 Wine，不推荐）

### Lagrange.Core

- **独立实现**，不注入官方客户端
- 优势：设备指纹（Guid / MAC / 设备名 / 内核版本）与 keystore 可持久化，
  快速登录更稳；不受「官方客户端版本」影响
- 代价：需要 .NET 运行时；签名服务可能需要自备
- 接入方式：`proto_backend = "lagrange"`，把 `Lagrange.OneBot` 及其依赖放到
  `/data/data/<包名>/files/lagrange/`，用 `--config` 指定配置

### remote（最推荐给多设备用户）

把协议端放在**一台固定设备**上（例如家里常开的小主机/NAS），手机只做「大脑」：

```
固定主机：NapCat / Lagrange  ← 一号只在这里登录
手机：     Botagent            ← 只连 ws，不登录 QQ
```

这样手机重启、换网络都不影响 QQ 登录态，被踢概率最低。

## 切换步骤

1. 停掉当前协议端
2. 改 `config.json` 的 `proto_backend` 与 `proto_ws`
3. 重启机器人服务（控制台 → 设置 → 重启协议端 / 或重启 App）

机器人会自动重连，控制台状态页会显示新的端口与掉线次数。

## 状态观察

`/api/qq` 里新增两个字段：

```json
{"drops": 3, "last_drop": {"ts": 1794478918, "code": 1008, "msg": "..."}}
```

- `drops`：本次运行累计掉线次数
- `last_drop.code`：WebSocket 关闭码，用来区分「被顶号」和「网络断开」

控制台「状态」页会显示「掉线 N 次（码 XXXX）」。
