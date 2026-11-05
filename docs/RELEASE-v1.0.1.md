# Botagent v1.0.1

修复版，两个高频问题：**二维码出不来**、**长对话时界面错乱**。

---

## 📥 下载

| 方式 | 地址 | 说明 |
|---|---|---|
| **蓝奏云**（国内推荐） | <https://wwbxc.lanzoub.com/b011mly7ud> | 密码：**byc6** |
| **GitHub Release** | <https://github.com/Yehua-1145/-QQbot-/releases/latest> | 需要魔法 |

> 用 v1.0 的不用重装，只替换 `aibot/webui.py` 然后重启 webui 即可；
> 嫌麻烦就整个包重装，配置不会丢。

---

## 修了什么

### 1. 二维码出不来的 bug

三个原因叠在一起：

| 问题 | 说明 |
|---|---|
| 在线判定不可靠 | 只读状态文件，bot 挂了也显示「已登录」，于是界面一直隐藏二维码 |
| 重启会杀掉正常会话 | 点「重新生成二维码」时 NapCat 明明在线，也被强制重启 |
| 请求阻塞 | 重启要 60 秒，整个请求同步卡住，页面看起来像死机 |

修法：

- 在线判定改成**真实检测**：状态文件 3 分钟内更新过 + 3001 端口在监听
- 已经在线时**拒绝**重新出码，并提示「要重新登录请先点重启 NapCat」
- 重启改为**后台执行**，页面立刻返回，前端显示进度：

```
正在重启协议端并生成二维码… 已等待 25 秒（约需 40~70 秒，别离开这一页）
```

- 12 秒后服务端确认容器是否真的起来，失败会把日志尾部带回来
- 二维码刷新从 4 秒改成 2 秒，生成期间更快看到码

### 2. 长对话时 UI 错乱

现象：消息一多，新消息跑到屏幕外，输入框盖住最后几条。

原因：消息区没有固定高度，整页跟着变长；而输入框是固定的，滚动到底的代码滚的是一个不是滚动容器的元素 —— 所以永远滚不到最新。

修法：

```css
#t-chat{height:calc(100vh - 110px);overflow:hidden}
#msgs{flex:1;min-height:0;overflow-y:auto;
      padding-bottom:calc(84px + env(safe-area-inset-bottom))}
#inp{flex:1 1 auto;min-width:0}
```

顺带修掉：

- 输入框会把「发送」按钮挤出屏幕（小屏可见）
- 长英文/链接会把气泡撑破（加了 `overflow-wrap:anywhere`）
- 切回「对话」页自动滚到最新一条

### 3. 其它小改

- 页面禁止横向溢出（`body{overflow-x:hidden}`），不再出现整页可左右拖动
- 版本号显示为 1.0.1

---

## 校验

```
文件      Botagent-v1.0.1.zip
大小      16.84 MB
SHA256    33BEE9EF7DEA764FEA1B33771374F85962D386DC116ABF83E2325FF6F1B15ED7
```

```bash
certutil -hashfile Botagent-v1.0.1.zip SHA256
```

---

## 怎么升级

**方式一（推荐，最省事）**

解压新包，进 `Windows一键部署`，重新点一次「开始部署」。配置和登录状态都保留。

**方式二（只换文件）**

把新包里的 `aibot/webui.py` 推到手机：

```bash
adb push aibot/webui.py /sdcard/Download/new_aibot/webui.py
adb shell su -c 'sh /data/local/tmp/install_new.sh'
adb shell su -c 'sh /data/local/tmp/rw.sh'
```

---

## 已知限制（未变）

完整清单见仓库 README 的「已知限制与反馈」。要点：

- 只在小米 6 / LineageOS 18.1 完整验证
- 无 root 只能聊天和发图，**完整 Agent 能力需要 root**
- 语音消息、表情包**尚未支持，已列入后续计划**
- 没有自动更新，升级要手动

---

**问题反馈**：仓库 Issues，或 App 内「设置 → 反馈」。
