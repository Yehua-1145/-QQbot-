# OneBot v11 端口：我们用到的接口子集

> 这是「协议端可替换」的依据。只要新实现满足下面这些，替换 NapCat 不用改 `qq_bot.py`。

## 连接方式

```
正向 WebSocket（我们作为客户端去连）
默认地址  ws://127.0.0.1:3001
鉴权      token 为空（本机回环，不暴露外网）
```

配置落在 NapCat 的 `napcat/config/onebot11_<QQ号>.json`：

```json
{
  "network": {
    "websocketServers": [{
      "name": "ws",
      "enable": true,
      "host": "127.0.0.1",
      "port": 3001,
      "messagePostFormat": "array",
      "token": "",
      "reportSelfMessage": false,
      "enableForcePushEvent": true,
      "heartInterval": 30000
    }]
  }
}
```

## 我们发送的 API

| action | 用途 | 关键参数 |
|---|---|---|
| `get_status` | 健康检查 + 判断 QQ 是否在线 | — |
| `get_login_info` | 拿机器人自己的 QQ 号 | — |
| `send_private_msg` | 私聊回复 | `user_id`, `message` |
| `send_group_msg` | 群聊回复 | `group_id`, `message` |
| `get_msg` | 取原消息（引用/合并转发时用） | `message_id` |
| `send_forward_msg` | 合并转发 | `messages` |
| `set_group_ban` | 群禁言（"重点关照"用） | `group_id`, `user_id`, `duration` |
| `get_group_member_info` | 群成员信息 | `group_id`, `user_id` |
| `get_image` / `get_record` | 下载图片/语音 | `file` |

## 我们接收的事件

```
message.private   私聊消息
message.group     群消息（群里默认要 @机器人，白名单见设置页「群聊」）
meta_event.lifecycle  连接/上线/心跳
meta_event.heartbeat  心跳
notice.*          入群、退群、禁言等（可选）
```

## 返回格式约定

```json
{ "status": "ok", "retcode": 0, "data": { ... } }
```

`qq_bot.py` 对失败的处理：`retcode != 0` 或 `status != "ok"` 视为失败，
连续失败 3 次会记日志、并按需重启协议端。

## 换实现时的自检清单

```
1. 起服务后 netstat 能看到 3001 LISTEN
2. 连上后发 get_status，返回 data.online == true
3. 私聊机器人一句，收到 message.private 事件
4. 回一句话，手机 QQ 那头能看到
5. 群里 @机器人，收到 message.group 且 self_id 正确
```

五项都过，就说明新协议端能直接替掉 NapCat。
