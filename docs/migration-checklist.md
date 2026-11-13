# 迁移检查清单（Termux → 内置运行时）

> 起因：v2 迁移时只搬了 `aibot/*.py` 和数据文件，没搬第三方依赖、没处理存储权限，
> 结果 JM 直接报 `No module named 'jmcomic'`、图库全空。

## 1. Python 依赖（最容易漏）

```bash
# 旧环境（Termux）
/data/data/com.termux/files/usr/lib/python3.14/site-packages

# 新环境（内置运行时）
/data/data/com.botagent/files/rt/usr/lib/python3.14/site-packages
```

必须确认这些包在（jmcomic 全家桶）：

| 包 | 用途 |
|---|---|
| `jmcomic` | JM 客户端 |
| `common`（由 `commonx` 提供） | jmcomic 的底层模块 |
| `curl_cffi` + `cffi` + `_cffi_backend.cpython-3xx-aarch64-*.so` | HTTP（含 TLS 指纹伪装） |
| `certifi` | CA 证书 |
| `pillow`（`PIL`） | 图片处理 |
| `pycryptodome`（`Crypto`） | 解密 |
| `pyyaml`（`yaml`、`_yaml`） | 配置解析 |
| `websocket-client` | OneBot ws |

> 两个环境的 CPython 版本必须一致（都是 3.14），否则编译型扩展（`_cffi_backend`、`_yaml`）会加载失败。

## 2. 数据文件

- `config.json`（合并：`napcat_ws`、`rotate_enabled`、`system_channel` 等新键）
- `perms.json`、`mode.txt`、`memory.md`
- `sent_albums.json`（JM 去重）、`audit.log`、`jm_login.txt`
- `assets/`、`icons/`

## 3. 存储权限

Android 11 的 `/sdcard` 是 FUSE，**升级安装补权限拿不到 `sdcard_rw` 组**。
两条路：

1. 卸载重装（丢 `/data/data`，需先备份）
2. 把图库复制进 `files/gallery`，代码里 `IMG_CACHE` 优先读私有目录（推荐，无需权限）

## 4. 容器 / 协议端

- proot 需要 `-b /storage/emulated/0:/sdcard`，否则容器里看不到图库
- Android 11 必须彻底关 GPU：`--disable-gpu --disable-gpu-compositing --disable-software-rasterizer --in-process-gpu`
- 登录状态在容器里，重建容器 = 重新扫码

## 5. 跑起来之后的自检

```bash
# 依赖
rt/usr/bin/python3 -c "import jmcomic, PIL, Crypto, yaml, curl_cffi; print('deps ok')"

# 图库可读
run-as com.botagent ls files/gallery/safe | wc -l     # 应 > 0

# 发图路径（本地图 → base64）
grep -c "local->base64" aibot/qq_bot.py               # 应为 1

# 协议端
ss -tln | grep -E "3001|6099"

# 模式开关写对了文件
grep -n "OLD_AIBOT" aibot/webui.py
```
