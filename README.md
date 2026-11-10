# 手机 Botagent

[![Release](https://img.shields.io/github/v/release/Yehua-1145/phone-botagent?style=flat-square&label=release&color=2ea043)](https://github.com/Yehua-1145/phone-botagent/releases)
[![Platform](https://img.shields.io/badge/Android-7.0%2B-3DDC84?style=flat-square&logo=android&logoColor=white)](https://github.com/Yehua-1145/phone-botagent)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/Yehua-1145/phone-botagent/build-apk.yml?style=flat-square&label=build)](https://github.com/Yehua-1145/phone-botagent/actions)

**把闲置安卓手机变成会用手机的 AI 助手。**

不用电脑 · 不用 root · 全程本机 · 可接入 QQ

它不止会聊天 —— 能读屏幕、点按钮、滑页面、打字。查电量、开 App、搜东西、定提醒，都是真的在操作手机。

> ⚠️ **当前为实验版（v2.0.x），明确不稳定**：整条链路只在小米 6 / Android 9 上验证过。
> 已知限制见 Release 说明。想稳的请用 [v1.1](https://github.com/Yehua-1145/phone-botagent/releases)。

---

## 它和别的手机 bot 差在哪

|  | 这个项目 | 常见手机 bot |
|---|---|---|
| 要电脑吗 | **不要**，一个 APK | 多数要（协议端跑 PC） |
| 要 root 吗 | **不要** | 部分要 |
| 能操作手机吗 | **能**，无障碍 12 类工具 | 基本不能 |
| 数据去哪 | **全在本机** | 常走第三方中转 |
| 首次部署 | 约 10 分钟，需自备 QQ 安装包 | 5 分钟，但要电脑 |

诚实说明：**首次部署不是「一键」** —— 不能随包分发 QQ 客户端，你得自己准备一个 arm64 的 QQ 安装包。之后开机即用。

---

## 核心能力

| 场景 | 能力 |
|---|---|
| 手机控制 | 读屏、点击、滑动、输入、长按、找元素、剪贴板、通知、截图、启动 App |
| AI 对话 | 流式回复、工具调用可见、多轮上下文、可选任意 OpenAI 兼容模型 |
| 聊天接入 | OneBot v11 正向 WebSocket，内置 NapCat，可换任意兼容实现 |
| 定时任务 | 自然语言建任务、执行、结果回报 |
| 完全本地 | Python 运行时 + Ubuntu 容器 + 协议端，全在手机里；无公网依赖 |
| 控制台 | 5 页签：对话 / 状态 / 日志 / 任务 / 设置 |

---

## 运行链路

```
┌──────────────────────── 手机 ────────────────────────┐
│  QQ 客户端 (Electron)                                │
│      ▲ loadNapCat.cjs 注入                           │
│  NapCat (napcat.mjs) ──► OneBot v11 ws :3001         │
│      ▲                        │                      │
│  proot Ubuntu 容器            ▼                      │
│  (Xvfb + QQ + NapCat)    qq_bot.py ──► agent.py      │
│                                │        │            │
│  无障碍服务 ◄──────────────────┘        │            │
│  (读屏/点击/输入)                        ▼            │
│                                    webui.py :8080    │
│                                         │            │
└─────────────────────────────────────────┼────────────┘
                                          ▼
                                  App 内置控制台 (WebView)
```

---

## 快速开始

1. 到 [Releases](https://github.com/Yehua-1145/phone-botagent/releases) 下载 `Botagent-v2.0-beta.apk`
2. 手机上装好，按 4 步向导走：填账号 → 开权限 → 准备环境 → 启动
3. 扫码登录后自动进控制台

细则与四种常见故障见 [README-v2.md](README-v2.md)。

---

## 文档

| 想看什么 | 去哪 |
|---|---|
| v2 详细说明（装法、结构、限制） | [README-v2.md](README-v2.md) |
| NapCat 怎么装进 QQ（兜底方案） | [docs/napcat-inject.md](docs/napcat-inject.md) |
| 协议端口 / 接口子集（换实现用） | [docs/onebot-port.md](docs/onebot-port.md) |
| 微信能接吗 | [docs/wechat.md](docs/wechat.md) |
| 体验升级路线 | [docs/ux-upgrade-plan.md](docs/ux-upgrade-plan.md) |
| 路线图与计划 | [RoadMap.md](RoadMap.md) |
| 参与贡献 | [CONTRIBUTING.md](CONTRIBUTING.md) |

---

## 使用边界

> [!IMPORTANT]
> 本项目是**非官方**第三方项目，与腾讯、NapCat 官方均无隶属或授权关系。
> 使用第三方协议端**可能违反服务条款**并导致账号受限。风险自负，详见 [DISCLAIMER.md](DISCLAIMER.md)。

```
✓ 不包含、不下载腾讯 QQ 客户端（需你自备）
✓ NapCat 按许可证原样内置，附全文与来源（assets/napcat/）
✓ 非商业用途
✗ 不要把 QQ 安装包传进仓库或 Release
```

许可：[MIT](LICENSE)（源码）· 内置的 NapCat 另受其非商业许可约束，详见 [NOTICE.md](NOTICE.md)。
隐私：[PRIVACY.md](PRIVACY.md) —— 聊天内容只发给你自己配置的模型服务商，不经过我们。

---

## 仓库结构

```
apk_src_v2/          Android 工程（不用 Gradle：aapt2 + javac + d8）
aibot/               机器人本体（AI、工具、控制台后端，v1.1/v2 共用）
deploy/              部署相关（napcat 加载器、v1.1 的 exe 部署器）
docs/                文档
scripts/             构建与打包脚本
build.ps1            一键构建 APK（见 BUILD.md）
```
