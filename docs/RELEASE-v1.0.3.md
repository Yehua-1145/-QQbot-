# Botagent v1.0.3

两个改动：**成人图源改成三层开关**（默认全局关闭，连主人也不开），以及修掉一个「关了开关还能出成人图」的漏洞。

---

## 📥 下载

| 方式 | 地址 | 说明 |
|---|---|---|
| **蓝奏云**（国内推荐） | <https://wwbxc.lanzoub.com/b011mly7ud> | 密码：**byc6** |
| **GitHub Release** | <https://github.com/Yehua-1145/-QQbot-/releases/latest> | 需要魔法 |

---

## 补丁：关闭深度抓图后仍可能出成人图（已修）

发布前测出来的漏洞，本包已修。

**现象**：深度抓图关着，发「来张图」仍然从 R18 图库取图。

**原因**：发图时读的是本地图库（`/sdcard/Pictures/大肥鱼图库/`）。
旧代码只看 `mode.txt` 决定要不要读 `r18/` 子目录，**完全没问总开关**；
更糟的是它「读不到状态就往宽处理」，等于默认放行。

```python
# 旧逻辑（有问题）
dirs = [safe]
try:
    if mode != "normal": dirs.append(r18)   # 不检查总开关
except Exception:
    dirs.append(r18)                        # fail-open，最危险
```

**修法**：

```python
def _img_cache_pool(allow_r18=None):
    if allow_r18 is None:
        allow_r18 = turn_r18_ok()       # 本轮会话是否被授权
    if allow_r18 and not _r18_master_on():
        allow_r18 = False               # 总开关永远最高优先级
    dirs = [safe]
    if allow_r18: ...                   # 只有这时才考虑 r18
    # 读不到 mode.txt -> 只给 safe，不再 fail-open
```

每轮对话开始时由 qq_bot 设置本轮授权，回合结束复位：

```python
agent.set_turn_r18(mode == "r18" and has_adult)   # run_agent 之前
```

**真机实测**：

```
总开关关  ->  图库池 88 张，其中 r18 0 张      ✅
总开关开  ->  图库池 448 张，其中 r18 360 张    （能正常切换）
```

---

## 这次改了什么

### 1. 成人图源默认全局关闭（含主人）

以前 `adult_uids` 默认带主人，主人一上来就能用。现在不行：

| 场景 | 以前 | 现在 |
|---|---|---|
| 主人发 r18 图 | 直接能用 | 拒绝，提示去开深度抓图 |
| 主人发「切换r18」 | 切成功 | 拒绝：「R18 模式默认全局关闭（连主人也不开）」 |
| 模型工具 eh_search / jm_search | 可用 | 直接返回拒绝信息 |
| 抓图任务 | 按配置抓 | r18 抓 0 张，只抓 safe |

### 2. 新增两套白名单

「设置 → 更多设置 → 深度抓图白名单」：

```
允许的 QQ 号   1000001, 1000002
允许的群号     123456789   （群里仍需 @机器人）
```

规则：

- **留空 = 谁都不能用**
- 私聊白名单和群聊白名单独立
- 白名单只在总开关打开后生效

三层关系是「与」：

```
总开关 off             → 谁都不行
总开关 on + 不在白名单  → 不行
总开关 on + 在白名单    → 可以
```

### 3. 「看权限」命令升级

主人在 QQ 里发「看权限」：

```
🔑 成人图源（r18）
深度抓图总开关: 已关闭（所有人都用不了）
白名单账号: 1000001, 1000002
白名单群聊: 无
临时授权: 无
```

### 4. 状态页新增一行

```
深度抓图    已关闭
            或 已开启  白名单 3 项
            或 已开启  白名单为空（红字提醒）
```

### 5. 关闭时自动降级

关掉深度抓图时自动把模式写回 `normal`，界面不再显示 R18 但其实用不了。

---

## 配置项

```jsonc
// config.json
{
  "r18_prefetch": false,          // 总开关，默认 false
  "r18_allowed_uids": [],         // 白名单 QQ 号
  "r18_allowed_groups": []        // 白名单群号
}
```

旧字段 `adult_uids` 仍然兼容，但**受总开关约束**——关着时无效。

---

## 升级方式

**方式一（推荐）**

解压新包 → 进 `Windows一键部署` → 重新点「开始部署」。配置和登录状态都保留。

**方式二（只换文件）**

```bash
adb push aibot/webui.py aibot/qq_bot.py aibot/agent.py /sdcard/Download/new_aibot/
adb shell su -c 'sh /data/local/tmp/install_new.sh'
adb shell su -c 'sh /data/local/tmp/rw.sh'
```

⚠️ 这次改了三个文件，**不能只换 webui.py**。

---

## 校验

```text
文件      Botagent-v1.0.3.zip
SHA256    860849A1B9E6AF75A5C09E25604A756FAEAD6A7D964965D4F31FC3D7B6DCC742
```

```bash
certutil -hashfile Botagent-v1.0.3.zip SHA256
```

---

## 已知限制（未变）

- 只在小米 6 / LineageOS 18.1 完整验证
- 无 root 只能聊天和发图，**完整 Agent 能力需要 root**
- 语音消息、表情包尚未支持，已列入后续计划
- 没有自动更新，升级要手动

**反馈**：仓库 Issues，或 App 内「设置 → 反馈」。
