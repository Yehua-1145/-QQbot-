# Botagent v1.0.2

修一个 **v1.0.1 引入的回归**：点其它页签时，内容被聊天区顶到下面，必须往下滑才能看到。

> ⚠️ 如果你装的是 v1.0.1，**建议升级到 v1.0.2**。v1.0 没有这个问题。

---

## 📥 下载

| 方式 | 地址 | 说明 |
|---|---|---|
| **蓝奏云**（国内推荐） | <https://wwbxc.lanzoub.com/b011mly7ud> | 密码：**byc6** |
| **GitHub Release** | <https://github.com/Yehua-1145/-QQbot-/releases/latest> | 需要魔法 |

---

## 修了什么

### 页签切换后要往下滑才能看到内容

**现象**：点「状态 / 模型 / 控制台 / 设置」，页面停在聊天区下方，得往下滑一段才能看到对应的卡片。

**原因**：v1.0.1 为了修长对话，给聊天区加了这一段：

```css
#t-chat{display:flex;flex-direction:column;height:calc(100vh - 110px);}
```

`#t-chat` 是 **ID 选择器**，优先级高于 `.tab{display:none}`。
结果聊天区**永远显示**，其它页签的内容被挤到它下面 —— 于是每次切页签都像"页面没刷新"。

**修法**：

```css
#t-chat{display:none;flex-direction:column;height:calc(100vh - 110px)}
#t-chat.active{display:flex}
```

默认不显示，只有带 `.active` 才展开。

### 顺带加固滚动复位

之前只在切页签时调 `window.scrollTo(0,0)`，但 `body` 一旦有 `overflow` 就会自己变成滚动容器，
它的 `scrollTop` 是独立保存的，复位不到。

现在统一处理：

```js
function resetScrollTop(){
  [document.scrollingElement, document.documentElement, document.body]
    .forEach(e => { if(e){ e.scrollTop = 0; } });
  window.scrollTo(0, 0);
}
```

切页签、关闭独立页时都会调用。

同时把 `html{height:100%}` 去掉、`body{overflow-x:hidden}` 去掉（改成加在 `html` 上），
避免 body 意外变成滚动容器。

### 其它

- 设置页的昵称改为 `Botagent`
- 版本号 1.0.2

---

## 升级方式

**方式一（推荐）**

解压新包，进 `Windows一键部署`，重新点「开始部署」。配置和登录状态都保留。

**方式二（只换文件）**

```bash
adb push aibot/webui.py /sdcard/Download/new_aibot/webui.py
adb shell su -c 'sh /data/local/tmp/install_new.sh'
adb shell su -c 'sh /data/local/tmp/rw.sh'
```

---

## 校验

```text
文件      Botagent-v1.0.2.zip
SHA256    090201C7BDDD76F0DF7C72080E66E29B7739D51F2B6CB4B976C48AAFC1877DBC
```

```bash
certutil -hashfile Botagent-v1.0.2.zip SHA256
```

---

## 已知限制（未变）

- 只在小米 6 / LineageOS 18.1 完整验证
- 无 root 只能聊天和发图，**完整 Agent 能力需要 root**
- 语音消息、表情包尚未支持，已列入后续计划
- 没有自动更新，升级要手动

**反馈**：仓库 Issues，或 App 内「设置 → 反馈」。
