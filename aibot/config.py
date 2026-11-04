#!/usr/bin/env python3
"""PhoneAgent 配置中心 —— 所有敏感信息都在这里（去敏后的模板）。

首次使用：复制本文件为 config_local.py 并填入自己的值，
或者直接设置同名环境变量。
"""
import os


def _env(name, default=""):
    return os.environ.get(name, default)


# ============ 必填 ============
# DeepSeek API Key（https://platform.deepseek.com 申请）
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "")

# 主人 QQ 号（只有这个号能私聊和切换模式）
OWNER_UID = int(_env("PHONEAGENT_OWNER_UID", "0") or 0)

# 机器人自己的 QQ 号（合并转发需要）
BOT_UIN = int(_env("PHONEAGENT_BOT_UIN", "0") or 0)

# ============ 可选 ============
# 允许的群聊（逗号分隔，例如 "123456,789012"）
_groups = _env("PHONEAGENT_ALLOWED_GROUPS", "")
ALLOWED_GROUPS = set(int(g) for g in _groups.split(",") if g.strip().isdigit())

# WebUI/控制面板的访问 token（随意长字符串，建议随机）
TOKEN = _env("PHONEAGENT_TOKEN", "change-me-please")

# 端口
WEBUI_PORT = int(_env("PHONEAGENT_WEBUI_PORT", "8080"))
NAPCAT_WS = _env("PHONEAGENT_NAPCAT_WS", "ws://127.0.0.1:3001")

# 模型
DEEPSEEK_MODEL = _env("PHONEAGENT_MODEL", "deepseek-chat")

# 每两条回复最小间隔（秒，防封号）
REPLY_INTERVAL = float(_env("PHONEAGENT_REPLY_INTERVAL", "4"))

# 最大工具调用步数
MAX_STEPS = int(_env("PHONEAGENT_MAX_STEPS", "16"))

# 下载目录
DOWNLOAD_DIR = _env("PHONEAGENT_DOWNLOAD_DIR", "/sdcard/Download")

# Termux 家目录（一般不用改）
TERMUX_HOME = _env("PHONEAGENT_TERMUX_HOME", "/data/data/com.termux/files/home")
AIBOT_DIR = TERMUX_HOME + "/aibot"
EH_DIR = TERMUX_HOME + "/eh"
MODE_FILE = AIBOT_DIR + "/mode.txt"
AUDIT_LOG = AIBOT_DIR + "/audit.log"
