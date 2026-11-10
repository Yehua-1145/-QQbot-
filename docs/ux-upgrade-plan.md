# 向 SnowLuma 的「体验」看齐：差距与路线

> 先分清：SnowLuma 的「好体验」不是 UI 华丽，而是**开发者体验（DX）+ 文档 + 发布工程**。
> 这些大部分可以抄，而且不需要重写产品。

## SnowLuma 到底好在哪（逐项拆）

| 它的做法 | 带来的感觉 | 我们能抄吗 |
|---|---|---|
| 一句话定位 + 三词能力清单（OneBot v11 · WebUI · SDK · MCP） | 3 秒知道它是什么 | ✅ 立刻 |
| 徽章墙（release / build / sdk / mcp / docker / stars） | 显得在认真维护 | ✅ 立刻 |
| 「核心能力」表格 + 「运行链路」示意图 | 不用读代码就懂架构 | ✅ 1 天（画图） |
| 快速开始就 3 步（下载 → 跑 launcher → 开 localhost:5099） | 上手极快 | ✅ 部分（我们没有 localhost 面板，但有 App） |
| 独立文档站（zh/docs：部署指南 + API 参考） | 有"正经项目"感 | ✅ 2 天 |
| 发布工程：完整包 / Lite 版 / 多平台 / Docker / npm 包 | 各种用户都能装 | ⚠️ 部分（Docker 对我们没意义） |
| SDK + MCP 包 | **接进别人生态**，让第三方愿意用 | ✅ 高价值，1~2 周 |
| EULA / PRIVACY / RoadMap / CONTRIBUTING / CONTEXT | 边界清晰、可持续协作 | ✅ 1 天 |
| 合规警示（第三方、风险自负） | 降低法律暴露 | ✅ 立刻 |

## 我们的差距（按性价比排序）

### Tier 1：一天能做完，感知最强

```
□ README 重构成 SnowLuma 那种骨架
  定位一句话 / 能力表格 / 运行链路图 / 3 步开始 / 文档索引 / 合规警示
□ 加 LICENSE + EULA（简版）+ PRIVACY（写明"数据不出手机"）+ RoadMap.md
□ 徽章：release 版本、stars、构建状态
□ GitHub Actions：打 tag 自动构建 APK 并挂到 Release
  （我们有 build.ps1，windows runner 能跑）
```

这一层做完，仓库第一眼就"像个正经项目"了。

### Tier 2：2~3 天，把「文档」立起来

```
□ docs/ 用 GitHub Pages 发布（已有 docs/index.html，可换成 mkdocs / VitePress）
□ 三份核心文档：
  · 部署指南（手机直装 / 电脑插线 / 四种常见故障）
  · 能力清单（12 个无障碍工具 + 参数 + 示例）
  · 协议端接入（NapCat 怎么装、OneBot 怎么换）
□ 截图/GIF：4 步向导、控制台 5 页签、扫码页
```

### Tier 3：1~2 周，真正拉开差距的地方

```
□ MCP Server（最高价值）
   把我们的 12 个手机控制工具暴露成 MCP tools：
   phone_dump / phone_tap / phone_type / phone_swipe / phone_shot ...
   → Claude / Cursor / 任何 MCP 客户端都能"操作我的手机"
   → 这是 SnowLuma 没有、且有真实差异化的东西

□ Python SDK（半天）
   pip install botagent-sdk → 连本机 8080，发指令、读状态、订阅事件

□ 多账号（成本高，最后做）
   容器里多开 QQ 实例，内存/存储翻倍，手机上很吃紧
```

## 哪些不用抄

| 它有的 | 为什么我们不需要 |
|---|---|
| Docker 镜像 | 我们的卖点是"跑在手机本地"，用 Docker 等于自废武功 |
| 多平台二进制 | 我们只有一个 APK，天生跨厂商 |
| Lite 版（需 Node 24） | 我们故意把运行时打进去，就是为了让用户不装 Node |
| 源码可见非商业许可 | 我们的场景本来就非商业，可以选更宽松的许可，但**必须保留 QQ/NapCat 的合规声明** |

## 一个关键判断

SnowLuma 的体验靠的是**工程规范**（文档、CI、语义化发布、SDK），
这些跟"技术难度"无关，只跟"愿不愿意做"有关。

**Tier 1 + Tier 2 大约 3~4 天，能拿到它 70% 的观感。**
Tier 3 的 MCP 才是真正的差异化 —— 而且它恰好是我们最强的部分（能操作手机）。

## 建议的执行顺序

```
第 1 步  README 骨架 + LICENSE/EULA/PRIVACY/RoadMap    （一天）
第 2 步  GitHub Actions 自动构建 + 徽章                （半天）
第 3 步  文档站 + 三份核心文档 + 截图                  （两天）
第 4 步  MCP Server                                    （一周，看需求）
```

前 3 步做完，再把定位语改成「**能用 MCP 被 AI 调用的手机执行器**」也不违和 ——
那时候它就不只是"手机上的 QQ 机器人"，而是一个能被别的 AI 使用的**手机执行层**。
