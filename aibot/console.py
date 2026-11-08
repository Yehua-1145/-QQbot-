#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PhoneAgent 本地控制台（手机离线终端，不依赖 QQ / 电脑）

用法：
    python3 console.py                 # 交互式控制台
    python3 console.py --once "你好"    # 只问一句就退出（脚本/自测用）
    python3 console.py --mode j        # 以 j 模式启动（e / j / normal）

斜杠命令见 /help。
界面完全在手机本地运行；只有向 DeepSeek 请求时才需要联网。
"""
# ---- 路径根（内置运行时用环境变量指过来，Termux 下保持默认）----
import os as _os_paths
_HOME_ROOT = _os_paths.environ.get("BOTAGENT_HOME_ROOT") or "/data/data/com.termux/files/home"
_PREFIX_ROOT = _os_paths.environ.get("BOTAGENT_PREFIX") or "/data/data/com.termux/files/usr"

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import time

AIBOT = _HOME_ROOT + "/aibot"
MODE_FILE = AIBOT + "/mode.txt"
QR_SRC = ("/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/"
          "installed-rootfs/ubuntu/root/napcat/cache/qrcode.png")
QR_DST = "/sdcard/Download/qq_qr.png"

# ---------------- 颜色 ----------------
class C:
    R = "\033[0m"
    B = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GRN = "\033[92m"
    YEL = "\033[93m"
    BLU = "\033[94m"
    MAG = "\033[95m"
    CYN = "\033[96m"
    GRY = "\033[90m"


ENABLE_COLOR = sys.stdout.isatty()


def c(text, color):
    if not ENABLE_COLOR:
        return text
    return color + text + C.R


# ---------------- 模式 ----------------
def get_mode():
    try:
        with open(MODE_FILE, encoding="utf-8") as f:
            m = f.read().strip().lower()
        return m if m in ("normal", "e", "j") else "normal"
    except Exception:
        return "normal"


def set_mode(m):
    try:
        with open(MODE_FILE, "w", encoding="utf-8") as f:
            f.write(m)
        return True
    except Exception:
        return False


MODE_DESC = {"r18": "R18（E站+禁漫双源）", "normal": "正常（Bing 安全图）",
             "auto": "R18（E站+禁漫双源）", "e": "R18（E站）", "j": "R18（禁漫）"}


# ---------------- shell 帮助 ----------------
def sh(cmd, timeout=25):
    try:
        p = subprocess.run(["su", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip()
    except Exception as e:
        return "ERR: %s" % e


def count(pattern, exact=False):
    """Count processes. exact=True uses pgrep -x (safer, no self-match)."""
    try:
        if exact:
            cmd = "pgrep -x %s | wc -l" % pattern
        else:
            cmd = "pgrep -f '%s' | wc -l" % pattern
        return int(sh(cmd) or 0)
    except Exception:
        return -1


def mem_available_mb():
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return -1


def port_open(port):
    return (":%d" % port) in sh("netstat -tln 2>/dev/null | grep -E ':%d'" % port)


def status_block():
    mode = get_mode()
    lines = []
    lines.append(c("模式    ", C.GRY) + c(MODE_DESC.get(mode, mode), C.CYN))
    rows = [
        ("NapCat 3001", port_open(3001)),
        ("WebUI 8080", port_open(8080)),
        ("NapCat UI 6099", port_open(6099)),
    ]
    for name, ok in rows:
        lines.append(c("%-14s" % name, C.GRY) + (c("在线", C.GRN) if ok else c("离线", C.RED)))
    n_proot = count("proot", exact=True)
    n_bot = count("qq_bot[.]py")
    n_wd = count("watchdog[.]sh")
    lines.append(c("%-14s" % "proot", C.GRY) + ("%d 个" % n_proot) +
                 (c("  (应只有 1 个)", C.YEL) if n_proot > 1 else ""))
    lines.append(c("%-14s" % "qq_bot", C.GRY) + ("%d 个" % n_bot))
    lines.append(c("%-14s" % "watchdog", C.GRY) + ("%d 个" % n_wd))
    ma = mem_available_mb()
    lines.append(c("%-14s" % "可用内存", C.GRY) + ("%d MB" % ma if ma > 0 else "?"))
    return "\n".join(lines)


def restart(what):
    if what in ("bot", "all"):
        sh("sh /data/local/tmp/start_bot.sh")
    if what in ("webui", "all"):
        sh("sh /data/local/tmp/start_webui.sh")
    if what in ("napcat", "all"):
        if os.path.exists("/data/local/tmp/restart_napcat.sh"):
            sh("sh /data/local/tmp/restart_napcat.sh")
        else:
            sh("pkill -9 -x proot; pkill -9 -x Xvfb; sleep 3; "
               "setsid sh /data/local/tmp/napcat_noscreen.sh </dev/null >/dev/null 2>&1 &")
    return "已请求重启: %s" % what


HELP = """命令（中文优先，英文/斜杠写法也都认）：
  帮助 (help, ?)        显示这份帮助
  状态 (status)         查看手机服务状态
  模式 (mode)           查看当前图源模式
  切正常 / 切r18       切换模式（正常=只用 Bing 安全图；r18=E站+禁漫双源）
  二维码 (qr)           导出 QQ 登录二维码到 /sdcard/Download/qq_qr.png
  重启 机器人|webui|qq|全部   重启对应服务
  截图 (shot)           截一张手机屏幕到 /sdcard/Download/console_shot.png
  命令 <内容> (sh)      以 root 执行一条命令，例如：命令 ls /sdcard
  日志 [行数] (log)     查看 qq_bot 日志（默认 20 行）
  清屏 (clear)          清空屏幕
  退出 (quit)           退出（Ctrl+D 也行）

直接输入文字 = 和 AI 对话（AI 会自己调用手机工具）。Ctrl+C 可中断当前请求。"""


# ---------------- 中文命令解析 ----------------
MODE_WORDS = {
    "r18": "r18", "成人": "r18", "绅士": "r18", "r18模式": "r18",
    "自动": "r18", "auto": "r18", "双源": "r18", "自动模式": "r18",
    "正常": "normal", "normal": "normal", "普通": "normal", "正常模式": "normal",
    "e": "r18", "e站": "r18", "e模式": "r18", "里站": "r18",
    "j": "r18", "jm": "r18", "禁漫": "r18", "j站": "r18", "禁漫天堂": "r18", "禁漫模式": "r18",
}
RESTART_WORDS = {
    "机器人": "bot", "bot": "bot", "ai": "bot", "后台": "bot",
    "webui": "webui", "界面": "webui", "网页": "webui",
    "qq": "napcat", "napcat": "napcat", "协议": "napcat",
    "全部": "all", "all": "all", "所有": "all",
}
EXACT_WORDS = {
    "quit": ("quit", ""), "exit": ("quit", ""), "q": ("quit", ""),
    "退出": ("quit", ""), "再见": ("quit", ""), "拜拜": ("quit", ""),
    "help": ("help", ""), "?": ("help", ""), "？": ("help", ""),
    "帮助": ("help", ""), "命令列表": ("help", ""),
    "status": ("status", ""), "状态": ("status", ""), "看看状态": ("status", ""),
    "什么状态": ("status", ""), "机器状态": ("status", ""),
    "mode": ("mode", ""), "模式": ("mode", ""), "什么模式": ("mode", ""),
    "当前模式": ("mode", ""),
    "qr": ("qr", ""), "二维码": ("qr", ""), "扫码": ("qr", ""), "登录二维码": ("qr", ""),
    "shot": ("shot", ""), "screenshot": ("shot", ""), "截图": ("shot", ""),
    "截屏": ("shot", ""), "看看屏幕": ("shot", ""), "拍个屏": ("shot", ""),
    "log": ("log", ""), "日志": ("log", ""), "看看日志": ("log", ""),
    "clear": ("clear", ""), "清屏": ("clear", ""), "cls": ("clear", ""),
}


def parse_local(line):
    """把一行输入解析成本地命令 -> (cmd, rest)；不是命令就返回 (None, None)。

    中文、英文、带不带斜杠都认，省得在手机上敲英文。
    """
    raw = (line or "").strip()
    if not raw:
        return None, None
    head = raw[1:].strip() if raw.startswith("/") else raw
    low = head.lower()
    if low in EXACT_WORDS:
        return EXACT_WORDS[low]
    # 英文写法：mode j / restart bot
    if low.startswith("mode ") or low.startswith("模式 "):
        tgt = head.split(None, 1)[1].strip().lower()
        if tgt in MODE_WORDS:
            return "mode_set", MODE_WORDS[tgt]
        return None, None
    if low.startswith("restart ") or low.startswith("重启 "):
        tgt = head.split(None, 1)[1].strip().lower()
        if tgt in RESTART_WORDS:
            return "restart", RESTART_WORDS[tgt]
        return None, None
    # 切模式：切/切换/换 + 目标
    for prefix in ("切换到", "切换", "切到", "切", "换到", "换"):
        if head.startswith(prefix):
            tgt = head[len(prefix):].strip().lower()
            if tgt in MODE_WORDS:
                return "mode_set", MODE_WORDS[tgt]
            return None, None
    # 重启：重启 [目标]
    if head.startswith("重启") or head.startswith("重开"):
        tgt = head[2:].strip().lower()
        if not tgt:
            return "restart", "all"
        if tgt in RESTART_WORDS:
            return "restart", RESTART_WORDS[tgt]
        return None, None
    # 执行命令：命令 xxx / sh xxx
    if head.startswith("命令"):
        return "sh", head[2:].strip()
    if low.startswith("sh ") or low == "sh":
        return "sh", head.split(None, 1)[1].strip() if " " in head else ""
    # 日志行数：日志 50 / log 50
    if low.startswith("日志 ") or low.startswith("log "):
        return "log", head.split(None, 1)[1].strip()
    if low.startswith("命令 "):
        return "sh", head[3:].strip()
    return None, None


# ---------------- 工具调用显示 ----------------
class ToolView(io.TextIOBase):
    """把 agent 的 verbose 输出（[tool] / [result]）美化成一行行提示。

    注意：必须把真实 stdout 存下来再往它上面写，否则 print 会写回自己（递归）。
    """

    def __init__(self, real):
        self.real = real
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._show(line)
        return len(s)

    def _show(self, line):
        line = line.rstrip()
        if not line:
            return
        if line.startswith("[tool]"):
            body = line[6:].strip()
            m = re.match(r"(\S+)\s*(.*)", body, re.S)
            name, arg = (m.group(1), m.group(2)) if m else (body, "")
            arg = arg.replace("\n", " ")
            if len(arg) > 110:
                arg = arg[:110] + "…"
            print(c("  ⚙ ", C.MAG) + c(name, C.YEL) + c("  " + arg, C.GRY),
                  file=self.real, flush=True)
        elif line.startswith("[result]"):
            body = line[8:].strip().replace("\n", " ")
            if len(body) > 110:
                body = body[:110] + "…"
            print(c("    ↳ ", C.GRY) + c(body, C.GRY), file=self.real, flush=True)
        else:
            print(c("  " + line[:160], C.GRY), file=self.real, flush=True)

    def flush(self):
        if self.buf:
            self._show(self.buf)
            self.buf = ""


def ask(agent, text):
    """向 agent 提问，实时显示工具调用 + 流式显示回答，返回最终文本。"""
    import agent as A
    real = sys.stdout
    view = ToolView(real)
    print(c("  ● 思考中…", C.GRY), flush=True)
    state = {"first": True, "n": 0}

    def on_text(piece):
        if not piece:
            return
        if state["first"]:
            state["first"] = False
            real.write(c("  AI › ", C.B + C.CYN))
        state["n"] += 1
        real.write(piece)
        real.flush()

    try:
        sys.stdout = view
        reply = A.run_agent(text, verbose=True, mode=get_mode(), on_text=on_text)
    except KeyboardInterrupt:
        sys.stdout = real
        return c("（已中断）", C.YEL)
    except Exception as e:
        sys.stdout = real
        return c("（出错: %s）" % e, C.RED)
    finally:
        sys.stdout = real
        view.flush()
        if not state["first"]:
            real.write("\n")
            real.flush()
    return reply


# ---------------- 横幅 ----------------
def banner():
    print()
    print(c("  PhoneAgent 本地控制台", C.B + C.CYN))
    print(c("  手机本地运行 · 不依赖 QQ · 输入「帮助」查看命令", C.GRY))
    print()
    print(status_block())
    print()


# ---------------- 主循环 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", help="只执行一句话然后退出")
    ap.add_argument("--mode", help="启动时切换到 auto / e / j / normal")
    args = ap.parse_args()

    if args.mode in ("r18", "normal"):
        set_mode(args.mode)

    sys.path.insert(0, AIBOT)
    try:
        import agent  # noqa: F401
    except Exception as e:
        print(c("无法加载 agent: %s" % e, C.RED))
        print(c("请确认 %s/agent.py 存在，且用 Termux 的 python3 运行" % AIBOT, C.GRY))
        return 1

    if args.once:
        ask(agent, args.once)
        return 0

    banner()
    hist = os.path.expanduser("~/.phoneagent_history")
    try:
        import readline
        if os.path.exists(hist):
            readline.read_history_file(hist)
        readline.set_history_length(500)
    except Exception:
        readline = None

    while True:
        try:
            prompt = c("[%s] " % get_mode(), C.MAG) + c("你 › ", C.GRN)
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue

        # ---- 本地命令（中文/英文、带不带斜杠都认）----
        cmd, rest = parse_local(line)
        if cmd:
            if cmd == "quit":
                break
            elif cmd == "help":
                print(HELP)
            elif cmd == "status":
                print(status_block())
            elif cmd == "mode":
                print(c("当前: %s" % MODE_DESC.get(get_mode(), get_mode()), C.CYN))
                print(c("切换: 切正常 / 切r18", C.GRY))
            elif cmd == "mode_set":
                if set_mode(rest):
                    print(c("✔ 已切换到 %s" % MODE_DESC.get(rest, rest), C.GRN))
                else:
                    print(c("切换失败（mode.txt 写不进去）", C.RED))
            elif cmd == "qr":
                # 用 su 复制：二维码在 AstrBot 的私有目录里，Termux 用户读不到
                sh("test -f %s && cp %s %s && chmod 666 %s" % (QR_SRC, QR_SRC, QR_DST, QR_DST))
                ok = sh("test -f %s && echo YES" % QR_DST).endswith("YES")
                if ok:
                    print(c("✔ 二维码已导出: %s" % QR_DST, C.GRN))
                    print(c("  用手机相册/文件管理器打开它扫码；扫码后 NapCat 会自动登录。", C.GRY))
                else:
                    print(c("没找到二维码，NapCat 可能还没启动。", C.YEL))
                    print(c("试试: 重启 qq", C.GRY))
            elif cmd == "restart":
                print(restart(rest))
            elif cmd == "shot":
                out = "/sdcard/Download/console_shot.png"
                sh("screencap -p %s && chmod 666 %s" % (out, out))
                if sh("test -f %s && echo YES" % out).endswith("YES"):
                    print(c("✔ 截图已保存: %s" % out, C.GRN))
                else:
                    print(c("截图失败（可能没有 root 权限）", C.RED))
            elif cmd == "sh":
                if not rest:
                    print(c("用法: 命令 <要执行的命令>，例如：命令 ls /sdcard", C.GRY))
                else:
                    out = sh(rest, timeout=40)
                    print(out[:4000] if out else c("(无输出)", C.GRY))
            elif cmd == "log":
                n = rest if rest.isdigit() else "20"
                print(sh("tail -n %s %s/qq_bot.log" % (n, AIBOT))[:4000])
            elif cmd == "clear":
                print("\033[2J\033[H", end="")
                banner()
            continue

        # ---- 对话 ----
        t0 = time.time()
        ask(agent, line)
        dt = time.time() - t0
        print()
        print(c("  (%.1fs)" % dt, C.GRY))
        print()

    try:
        if readline:
            readline.write_history_file(hist)
    except Exception:
        pass
    print(c("再见。", C.GRY))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
