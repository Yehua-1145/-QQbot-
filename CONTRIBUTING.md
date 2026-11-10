# 参与贡献（CONTRIBUTING）

欢迎提 issue、提 PR。为了少走弯路，先说清楚这个项目的边界。

## 项目边界

```
✓ 手机本地运行（APK + 内置运行时 + proot 容器）
✓ 无障碍控制手机（读屏、点击、输入、截图）
✓ 接入 OneBot v11（内置 NapCat，可换实现）
✗ 不做：逆向 QQ 协议、hook 客户端、云端中转、绕过风控
```

**提交 PR 前请确认不触碰最后一条。** 涉及绕过登录/风控/批量号的改动会被直接关闭。

## 开发环境

```
Android 侧    JDK 11+（推荐 21）、Android SDK build-tools 34、platform android-34
             不用 Gradle，构建走 aapt2 → javac → d8 → zipalign → apksigner
机器人侧      Python 3.10+（本机调试用，和手机里的 3.14 兼容）
```

构建：

```powershell
$env:ANDROID_SDK_ROOT = "D:\sdkshim"        # 或你的 SDK 路径
$env:JAVA_HOME = "C:\Program Files\Java\latest\jdk-21"
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -Out .\Botagent.apk
```

构建细节与踩过的坑见 [BUILD.md](BUILD.md)。

## 代码结构

```
apk_src_v2/src/com/botagent/
├── MainActivity.java     页面宿主 + JS 桥 + 各种一次性任务（偏大，正在拆）
├── Container.java        proot 容器：创建 / 跑命令 / 推文件 / 装 deb
├── Extension.java        扩展包脚本（NapCat 安装 / 启动 / 状态）
├── RuntimeManager.java   Python 运行时解压、起 webui / qq_bot、守护重启
├── A11yService.java      无障碍服务（12 个工具的后端）
├── A11yServer.java       a11y 的本地 HTTP 接口
└── BotService.java       前台服务 + 开机自启

aibot/
├── agent.py              AI 主循环、工具定义（54 个）
├── qq_bot.py             OneBot 客户端、消息路由、健康检查
├── webui.py              控制台后端（HTTP + SSE）
└── config.py             配置项
```

## 改动约定

```
· Java 里不要用匿名内部类 —— d8 会崩，必须用顶部具名类（见 BUILD.md）
· Python 侧路径一律走环境变量（HOME_ROOT / PREFIX_ROOT），别写死
· 前端只用原生 HTML/CSS/JS，不引框架（WebView 版本老）
· 字符串里的中文要 UTF-8；.ps1 必须带 BOM
```

## 提交信息

```
feat:     新功能
fix:      修 bug
docs:     文档
style:    只动样式
refactor: 重构（不改行为）
perf:     性能
chore:    杂项
```

一句话说清"改了什么、为什么"即可，不用写长。

## PR 检查清单

```
□ 能构建通过（build.ps1 无报错）
□ 真机验证过（写清机型 + 安卓版本 + 验证了哪几步）
□ 没引入新的网络依赖（我们坚持全本地）
□ 没把 QQ 安装包 / 个人配置 / 日志提交上来
```

## 报告问题时请带

```
机型 + 安卓版本 + APP 版本（设置页「关于」能看到）
复现步骤
控制台「日志」页里相关的几行
```

## 许可

贡献的代码按 [MIT](LICENSE) 合并。注意：分发包内含 NapCat（非商业许可），
所以**整个分发包必须保持非商业**，见 [NOTICE.md](NOTICE.md)。
