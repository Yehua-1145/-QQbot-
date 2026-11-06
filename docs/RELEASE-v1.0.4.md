# Botagent v1.0.4

让 AI 真的能“看着界面操作手机”：新增 12 个界面工具、OCR 兜底、图标模板、视觉模型接口。

---

## 📥 下载

| 方式 | 地址 | 说明 |
|---|---|---|
| **蓝奏云**（国内推荐） | <https://wwbxc.lanzoub.com/b011mly7ud> | 密码：**byc6** |
| **GitHub Release** | <https://github.com/Yehua-1145/-QQbot-/releases/latest> | 需要魔法 |

> 从 v1.0.3 升级：解压新包 → 进 `Windows一键部署` → 重新点「开始部署」。
> 部署流程会顺手把 OCR 依赖也装好，配置和登录状态都保留。

---

## 新增能力

### 1. 界面自动化（有 root）

| 工具 | 作用 |
|---|---|
| `ui_dump` | 读当前界面的文字控件和坐标 |
| `ui_tap` | 按文字点按钮，找不到会返回候选 |
| `ui_type` | 往输入框填字 |
| `ui_swipe` | 滑动/翻页 |
| `ui_key` | 返回、Home、删除 |
| `ui_wait` | 等某个文字出现再继续 |

工作方式是「看清再点」：

```text
ui_dump → 看到「网络和互联网 @(360,1112)」
ui_tap  → 点它
ui_wait → 等「互联网」出现，确认进去了
```

**实测**：让它"点进设置里的网络和互联网"，前台真的切到了 `Settings$SubSettings`。

### 2. OCR 兜底（WebView / 游戏 / 图片界面）

`ui_dump` 读不到控件时自动改用 OCR（tesseract + 中文包，离线）：

| 工具 | 作用 |
|---|---|
| `ocr_screen` | 截图识别，返回文字+坐标 |
| `ocr_tap` | 在 OCR 结果里按文字点（词级定位） |
| `ocr_wait` | 等文字出现（游戏加载、动画结束） |
| `ocr_find` | 找不到就自动一屏屏滑着找 |

**实测**：

```text
ocr_wait("Botagent", 6s) → 「Botagent」已出现   耗时 2.9 秒
ocr_find("模型", 不滑动)  → 找到「模型」@(138,351)
```

### 3. 图标模板（纯图标按钮）

| 工具 | 作用 |
|---|---|
| `icon_save` | 把屏幕某位置裁成模板存下来（一次存、长期用） |
| `icon_tap` | 按模板找位置再点 |

匹配用「灰度归一化互相关（多尺度）+ 边缘兜底」：

```text
同界面   0.72 ~ 0.98 命中
换界面   0.46       会被拒
耗时     2.5 秒
```

**注意**：用程序画的几何图标不可靠（实测只有 0.5~0.66 分，会误点），
必须用 `icon_save` 从真实屏幕裁剪。

### 4. 视觉模型接口（纯图形界面）

`see(question)` 把截图发给视觉模型，让它描述界面或指出按钮位置。

需要在 `config.json` 里加：

```jsonc
{
  "vision_model": "qwen-vl-plus",        // 或 gpt-4o / glm-4v
  "vision_base_url": "https://...",      // 可省，默认用 base_url
  "vision_api_key": "sk-..."             // 可省，默认用 api_key
}
```

没配时会返回配置说明，不会报错崩掉。

---

## 安装变化

- 部署工具新增 **「装OCR依赖」** 按钮
- 部署流程末尾会**自动**装 tesseract + 中文包 + python-numpy（失败不影响聊天）
- 安装包里已附带 `chi_sim.traineddata`（2.4 MB），不用联网下载
- 包体积从 16.85 MB 涨到 **18.52 MB**

---

## 边界（照样说清）

- 这 12 个工具**只有主人能用**，访客拿不到
- 需要 **root**（`uiautomator` 要 root）
- WebView / 游戏靠 OCR，文字拆空格的问题已处理（匹配前统一去空白）
- 纯图形无文字的界面只能靠视觉模型，且要额外配 key
- 涉及付款、删除、给别人发消息，提示词要求它先问确认

---

## 校验

```text
文件      Botagent-v1.0.4.zip
大小      18.52 MB
SHA256    E0075A6E1F4A2A478B984647F5EA3544231C597FEC390F89D6E7D92FB73077D2
```

```bash
certutil -hashfile Botagent-v1.0.4.zip SHA256
```

---

## 已知限制（未变）

- 只在小米 6 / LineageOS 18.1 完整验证
- 无 root 只能聊天和发图
- 语音、表情包未支持
- 没有自动更新

**反馈**：仓库 Issues，或 App 内「设置 → 反馈」。
