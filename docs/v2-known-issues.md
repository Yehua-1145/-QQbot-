# v2（内置运行时）已知问题清单

> 记录时间：2026-11-13
> 分支：`v2-embedded-runtime`
> 状态：**仅记录，不在实机运行**。当前线上跑的是 v1.1（Termux + NapCat），v2 的 BotService 已 `pm disable`。

这份清单是这几天在真机（Mi 6 / Android 11 / Magisk）上折腾 v2 时踩到的全部问题，按「能不能修、值不值得修」分组。给后来的人（也包括我自己）少走弯路。

---

## A. 严重（直接导致不可用）

### A1. proot 容器里的 QQ 启动即崩（SIGTRAP）

- 现象：`proot → Xvfb → qq` 起得来，日志走到 `resourcesPath: /opt/QQ/resources` 后立刻
  `Trace/breakpoint trap`，`== QQ 已退出 ==`
- 原因：NapCat 的注入方式（preload `major.node`）和容器内 QQ 3.2.34 不兼容；
  同一台机器上 AstrBot 的容器用 `LD_PRELOAD=libnapcat_launcher.so` 引导就能起来
- 现阶段的绕法：借用 `launcher.sh` + `libnapcat_launcher.so`（从 AstrBot 容器拷，约 76 KB），
  并且**必须补全 GPU 关闭参数**：
  `--no-sandbox --disable-dev-shm-usage --disable-gpu --disable-gpu-compositing --disable-software-rasterizer --in-process-gpu`
  少一个就会 `GPU process isn't usable. Goodbye.`
- 建议修法：把 `libnapcat_launcher.so` 这一套原生引导内置进 APK，而不是依赖外部容器

### A2. 容器里没有 `/sdcard`，所有本地图片发送失败

- 现象：`发送伪造合并转发消息失败: ENOENT ... /sdcard/Pictures/大肥鱼图库/...`
- 原因：proot 启动参数没有 `-b /storage/emulated/0:/sdcard`
- 已采用的绕法（v1.1 也用了）：**本地图片读成 base64 再发**，完全不依赖容器路径
- 另一种修法：启动参数加 `-b /storage/emulated/0:/sdcard`（需要重启协议端 + 重新扫码，代价高）

### A3. 内置运行时的 App 读不到 `/sdcard`

- 现象：`run-as com.botagent ls /sdcard/Pictures/...` → `Permission denied`
- 原因：Android 11 的 FUSE 存储要求 app 在**安装时**就声明并带入 `sdcard_rw` 组；
  我们是「升级安装」补的权限，组没更新，`pm grant` 也没用
- 已验证的绕法：把图库复制进 `files/gallery`（55 MB），`agent.py` 的 `IMG_CACHE` 优先读私有目录
- 彻底修法：卸载重装（会丢 `/data/data` 下的配置），或者改用 MediaStore 查询

### A4. 迁移到内置运行时，第三方依赖没跟着迁

- 现象：`jm_search` 直接报 `No module named 'jmcomic'`
- 原因：迁移只搬了 `aibot/*.py` 和数据文件，没搬 `site-packages`
- 修法（已做）：从 Termux 的 `python3.14/site-packages` 整包同步，再补 `common`、`_cffi_backend`、`certifi` 等
- 教训：**迁移要带依赖清单**，见 `docs/migration-checklist.md`

---

## B. 中等（能用但会坑人）

### B1. 图库每小时轮换「删得比抓得多」

- 现象：图库从 223 张掉到 48 张
- 原因：`rotate_gallery()` 固定删 50 张，但 EH 不通时抓到的常常是 0
- 修法（已做）：改成「抓到几张删几张」`rotate_gallery(n_safe=s, n_r18=r)`

### B2. 每日配额太小

- 现象：中午就 `今日累计 r18 98/100`，之后每小时只能抓 2 张，还全失败
- 修法（已做）：`DAILY_R18 100 → 300`、`DAILY_SAFE 50 → 150`、批量 `25/13 → 35/15`

### B3. JM 抓图兜底会「静默返回 0」

- 现象：`写真: E站只拿到 0/x，改用 JM tag 兜底` 之后一张都没有，且不报错
- 原因：tag 搜索的相册全部进过 `seen` 名单后被跳过；`_grab_jm_photos` 里也没有二次兜底
- 修法（已做）：新增 `_grab_jm_by_search()`，用 `agent.t_jm_search()` 拿新相册，
  再用 `jmcomic` 的 `JmOption.default().download_album(id)` 直接下载（这条路径实测稳定）

### B4. 控制台的「抓图模式」开关写错文件

- 现象：开关点了没反应，模式永远是 normal
- 原因：控制台写的是 `com.botagent/files/aibot/mode.txt`，而实际在跑的机器人读
  `com.termux/files/home/aibot/mode.txt`
- 修法（已做）：`webui.py` 里按「当前真正在跑的机器人」解析 `MODE_FILE` / `CFG_PATH`

### B5. 模式映射 bug：`r18` 被当成 `normal` 写回

- 原因：`"r18" if m in ("j", "e", "auto") else "normal"` —— `r18` 不在列表里
- 修法（已做）：列表补上 `"r18"`

### B6. 群聊第一次点输入框点不中

- 现象：`输入失败: no focused input`
- 原因：群会话刚打开还没渲染完就点
- 修法（已做）：打开后等 3.2 秒；点输入框失败重试 3 次

### B7. 回复完 QQ 停在聊天页，导致后续消息不再产生通知

- 现象：系统通道只能收到第一条消息
- 原因：QQ 在前台时不出通知
- 修法（已做）：发完消息按 HOME 回主屏

### B8. 无障碍「设置了但没绑定」

- 现象：`settings get secure enabled_accessibility_services` 显示已设置，但 8081 不监听
- 修法：`settings put` 关掉再打开（toggle），服务才会真正 bind

---

## C. 结构性（修起来不划算）

### C1. NapCat 注入官方客户端本身就是被踢的根源

- 腾讯对「非人类操作节奏」和「异常客户端」都敏感，社区结论：Linux QQ 注入相对最不易被检测，
  但仍会掉线
- 抗掉线的正确做法（已实现在 v1.1）：退避重连 5→300 秒、协议端恢复立即重连、掉线计数、单实例

### C2. 系统通道（通知 + 无障碍）会被风控

- 现象：连续 UI 自动化后账号被踢，QQ 安全中心出现「登录设备风险提醒」
- 结论：这条路适合**低频兜底**，不适合高频聊天；发图尤其容易被拦

### C3. 纯协议方案（Lagrange）卡在签名服务

- 现象：`Signer server returned a NotFound`
- 探测结果：`sign.lagrangecore.org` 全站 404，公共签名服务已下线
- 要用得自建签名服务（qsign / unidbg），依赖特定 QQ 版本的原生库，维护成本高

### C4. 双容器抢同一个 QQ 号

- 现象：`com.astrbot.astrbot_android` 和 `com.botagent` 各有一个 ubuntu 容器，
  都装了 NapCat、都配了 3997864440 → 互相踢
- 处理：`pm disable-user com.astrbot.astrbot_android`，只保留一个
- 教训：**一个号只能有一个客户端在收消息**

---

## D. 待办（还没做）

- [ ] 依赖清单化：`requirements.txt` + 一键同步脚本（从 Termux 拷或 pip 装）
- [ ] 图库改用 MediaStore 查询，彻底摆脱 `/sdcard` 权限问题
- [ ] 把 `libnapcat_launcher.so` 那套原生引导内置进 APK
- [ ] 系统通道加「低频模式」：只处理 @我 / 私聊，且每小时最多 N 条
- [ ] 签名服务自建方案调研（Lagrange / qsign）
- [ ] v2 的 BotService 恢复开关做成控制台里的显式按钮（避免来回 `pm`）

---

## E. 当前真机状态（供对照）

```
线上跑的是 v1.1：Termux python3.14 + NapCat（容器）
v2 的机器人：BotService 已 disable，不会自启
看门狗：/data/local/tmp/bot_watch.sh（机器人 + 控制台 + 每小时图库轮换）
开机自启：/data/adb/service.d/99_botagent_boot.sh
备份：/sdcard/bot_backup_20261113_0257.tar.gz
```
