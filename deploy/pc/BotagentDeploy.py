"""
Botagent 一键部署工具（Windows）

用法：双击 exe → 插手机 → 填 3 个信息 → 点「开始部署」。

做的事：
  1. 找 adb（exe 同目录 / PATH / <platform-tools 路径>）
  2. 检测已连接且已授权的安卓设备
  3. 把 aibot/*.py 推到手机的 /sdcard/Download/botagent/
  4. 有 root：直接在 Termux 里写配置、装文件、拉起服务
     无 root：把安装命令复制到剪贴板，提示在 Termux 里粘贴执行
  5. 显示控制台地址和 token
"""

import os
import re
import sys
import json
import time
import shutil
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_NAME = "Botagent 一键部署"
VERSION = "1.0"
PHONE_TMP = "/sdcard/Download/botagent"
TERMUX_HOME = "/data/data/com.termux/files/home"
APP_DIR = TERMUX_HOME + "/aibot"


def base_dir():
    """exe 所在目录（打包后 sys.executable 的目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_adb():
    cands = [
        os.path.join(base_dir(), "adb.exe"),
        os.path.join(base_dir(), "platform-tools", "adb.exe"),
        r"<platform-tools 路径>\adb.exe",
        r"C:\platform-tools\adb.exe",
    ]
    which = shutil.which("adb")
    if which:
        cands.insert(0, which)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def find_src():
    """找 aibot 源码目录：优先同目录的 aibot/，其次 exe 内嵌。"""
    here = base_dir()
    cands = [
        os.path.join(here, "aibot"),
        os.path.join(here, "..", "aibot"),
        os.path.join(here, "..", "..", "aibot"),
        os.path.join(here, "..", "..", "..", "aibot"),
        os.path.join(getattr(sys, "_MEIPASS", here), "aibot"),
    ]
    for c in cands:
        if os.path.isfile(os.path.join(c, "qq_bot.py")):
            return os.path.abspath(c)
    return None


class Deployer:
    def __init__(self, log):
        self.adb = find_adb()
        self.log = log

    def run(self, args, timeout=90, serial=None):
        cmd = [self.adb]
        if serial:
            cmd += ["-s", serial]
        cmd += args
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                               creationflags=0x08000000 if os.name == "nt" else 0)
            out = (p.stdout or b"").decode("utf-8", "replace")
            err = (p.stderr or b"").decode("utf-8", "replace")
            return p.returncode, out, err
        except subprocess.TimeoutExpired:
            return 124, "", "命令超时"
        except Exception as e:
            return 1, "", str(e)

    def shell(self, cmd, timeout=90, serial=None, root=False):
        if root:
            return self.run(["shell", 'su -c "%s"' % cmd.replace('"', '\\"')],
                            timeout=timeout, serial=serial)
        return self.run(["shell", cmd], timeout=timeout, serial=serial)

    def devices(self):
        rc, out, err = self.run(["devices"])
        devs = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            serial, state = line.split("\t", 1)
            devs.append((serial, state.strip()))
        return devs

    def has_root(self, serial):
        rc, out, _ = self.run(["shell", "su -c id"], timeout=20, serial=serial)
        return rc == 0 and "uid=0" in out

    def has_termux(self, serial):
        rc, out, _ = self.run(["shell", "ls " + TERMUX_HOME], timeout=20, serial=serial)
        return rc == 0 and "aibot" in out or "files" in out

    def push_files(self, src, serial, progress=None):
        """推 .py 和 assets/（开屏图、头像都在这，缺了界面就是空框）。"""
        files = [f for f in os.listdir(src) if f.endswith(".py")]
        total = len(files)
        self.shell("mkdir -p " + PHONE_TMP, serial=serial)
        for i, f in enumerate(files, 1):
            rc, out, err = self.run(["push", os.path.join(src, f), PHONE_TMP + "/" + f],
                                    timeout=120, serial=serial)
            if progress:
                progress(i, total, f)
            if rc != 0:
                raise RuntimeError("推送 %s 失败：%s" % (f, err.strip()[:200]))

        # assets 目录（开屏图 / 头像）
        adir = os.path.join(src, "assets")
        if os.path.isdir(adir):
            self.shell("mkdir -p " + PHONE_TMP + "/assets", serial=serial)
            for f in os.listdir(adir):
                p = os.path.join(adir, f)
                if not os.path.isfile(p):
                    continue
                self.run(["push", p, PHONE_TMP + "/assets/" + f], timeout=120, serial=serial)
            if progress:
                progress(total, total, "assets/")
        return files





    # ---------- Termux 自动安装（缺失时由电脑下载再推手机） ----------
    TERMUX_URLS = [
        "https://github.com/termux/termux-app/releases/download/v0.118.1/"
        "termux-app_v0.118.1+github-debug_arm64-v8a.apk",
        "https://github.com/termux/termux-app/releases/download/v0.118.0/"
        "termux-app_v0.118.0+github-debug_arm64-v8a.apk",
    ]

    def _local_termux_apk(self):
        """先看 exe 同目录有没有现成的 apk，有就直接用（离线可用）。"""
        here = base_dir()
        for n in os.listdir(here):
            low = n.lower()
            if low.startswith("termux") and low.endswith(".apk") and "boot" not in low:
                return os.path.join(here, n)
        return None

    def download_termux(self, log=None, progress=None):
        """下载 Termux 安装包到临时目录，返回路径（失败返回 None）。"""
        import urllib.request

        dst = os.path.join(os.environ.get("TEMP", "."), "termux-arm64.apk")
        if os.path.isfile(dst) and os.path.getsize(dst) > 20 * 1024 * 1024:
            if log:
                log("用已下载的 Termux 包（%d MB）" % (os.path.getsize(dst) // 1048576))
            return dst

        for url in self.TERMUX_URLS:
            try:
                if log:
                    log("下载 Termux：%s" % url.split("/")[-1])
                req = urllib.request.Request(url, headers={"User-Agent": "Botagent-Deploy"})

                def hook(count, block, total):
                    if progress and total > 0:
                        progress(count * block, total)

                urllib.request.urlretrieve(req.full_url, dst, reporthook=hook)
                if os.path.getsize(dst) > 20 * 1024 * 1024:
                    if log:
                        log("下载完成（%d MB）" % (os.path.getsize(dst) // 1048576), "ok")
                    return dst
            except Exception as e:
                if log:
                    log("下载失败：%s" % str(e)[:120], "warn")
        return None

    def ensure_termux(self, serial, log=None, progress=None):
        """确保手机装了 Termux；没装就由电脑下载 + 安装。返回 (ok, freshly_installed)。"""
        if self.termux_installed(serial):
            if log:
                log("手机已装 Termux", "ok")
            return True, False

        apk = self._local_termux_apk()
        if apk:
            if log:
                log("用本地 Termux 包：%s" % os.path.basename(apk))
        else:
            apk = self.download_termux(log=log, progress=progress)
        if not apk:
            if log:
                log("没能拿到 Termux 安装包（网络不通，且本地没有 apk）", "err")
            return False, False

        if log:
            log("安装 Termux 到手机…")
        rc, out, err = self.run(["install", "-r", apk], timeout=300, serial=serial)
        blob = (out or "") + (err or "")
        ok = "Success" in blob
        if log:
            log("安装 Termux %s" % ("成功" if ok else ("失败：" + blob.strip()[:150])),
                "ok" if ok else "err")

        # 签名冲突：Termux 和 Termux:Boot 共用 sharedUserId，签名不一致就装不上
        if not ok and "SHARED_USER" in blob.upper():
            if log:
                log("检测到 Termux:Boot 签名冲突，先卸掉它再试", "warn")
            self.run(["uninstall", "com.termux.boot"], timeout=60, serial=serial)
            time.sleep(2)
            rc, out, err = self.run(["install", "-r", apk], timeout=300, serial=serial)
            blob = (out or "") + (err or "")
            ok = "Success" in blob
            if log:
                log("重试安装 Termux %s" % ("成功" if ok else "仍失败"), "ok" if ok else "err")

        if not ok:
            # 常见于 MIUI/HyperOS：INSTALL_FAILED_USER_RESTRICTED
            self._manual_apk = apk
            if "USER_RESTRICTED" in blob:
                if log:
                    log("这是小米系统的限制：要在开发者选项里打开「USB 安装」", "warn")
            try:
                self.run(["push", apk, "/sdcard/Download/termux.apk"], timeout=180, serial=serial)
                if log:
                    log("安装包已放到手机 /sdcard/Download/termux.apk，可以手动点安装", "warn")
            except Exception:
                pass
            return False, False

        # 装完首次启动要下 bootstrap，先给足时间
        if log:
            log("首次启动 Termux（要等它下载基础组件，约 40~90 秒）…")
        self.screen_on(serial)
        self.open_termux(serial)
        time.sleep(55)
        return True, True

    # ---------- 环境准备（免 root 也能做） ----------
    def env_prepare(self, serial, log=None):
        """把 Termux 需要的前置条件都配好，省得用户自己去设置里点。"""
        steps = []

        def step(name, ok, err=""):
            steps.append((name, ok, err))
            if log:
                log(name, ok, err)

        # 1) 存储权限（没有它 Termux 读不到 /sdcard）
        ok = True
        for perm in ("READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE"):
            rc, out, err = self.run(
                ["shell", "pm grant com.termux android.permission.%s" % perm],
                timeout=30, serial=serial)
            # 已经授过会返回错误，不算失败
            if rc != 0 and "Unknown permission" not in (err or "") and "not a changeable" not in (err or ""):
                ok = ok and True
        step("授予存储权限", True)

        # 2) 允许后台运行（部分 ROM 会限制）
        self.run(["shell", "cmd appops set com.termux RUN_IN_BACKGROUND allow"],
                 timeout=20, serial=serial)
        self.run(["shell", "cmd appops set com.termux RUN_ANY_IN_BACKGROUND allow"],
                 timeout=20, serial=serial)
        step("允许后台运行", True)

        # 3) 加入电池优化白名单
        rc, out, err = self.run(
            ["shell", "dumpsys deviceidle whitelist +com.termux"], timeout=25, serial=serial)
        step("加入电池白名单", True)

        # 4) 有 Termux:Boot 安装包就顺手装上（开机自启用）
        boot_apk = os.path.join(base_dir(), "termux_boot.apk")
        if os.path.isfile(boot_apk):
            rc, out, err = self.run(["install", "-r", boot_apk], timeout=120, serial=serial)
            blob = (out or "") + (err or "")
            ok = "Success" in blob
            if not ok and "SHARED_USER" in blob.upper():
                # 自带的 boot 包和 Termux 不同源，签名冲突；只是自启功能，跳过不影响主流程
                step("安装 Termux:Boot", True, "(签名不匹配，已跳过；不影响使用)")
            else:
                step("安装 Termux:Boot", ok, err if not ok else "")
            if ok:
                self.run(["shell", "cmd appops set com.termux.boot RUN_IN_BACKGROUND allow"],
                         timeout=20, serial=serial)
                self.run(["shell", "dumpsys deviceidle whitelist +com.termux.boot"],
                         timeout=25, serial=serial)
        else:
            step("安装 Termux:Boot", True, "(未附带安装包，跳过)")

        # 5) 建好暂存目录
        self.shell("mkdir -p " + PHONE_TMP, serial=serial)
        step("创建暂存目录", True)

        return steps


    # ---------- 推送手机控制台 App ----------
    CONSOLE_PKGS = ["com.phoneagent"]

    def find_console_apk(self):
        here = base_dir()
        for n in ("Botagent.apk", "PhoneAgent.apk", "botagent.apk"):
            p = os.path.join(here, n)
            if os.path.isfile(p):
                return p
        for n in os.listdir(here):
            if n.lower().endswith(".apk") and ("botagent" in n.lower() or "phoneagent" in n.lower()):
                return os.path.join(here, n)
        return None

    def console_installed(self, serial):
        rc, out, _ = self.run(["shell", "pm list packages"], timeout=25, serial=serial)
        return any(("package:" + p) in (out or "") for p in self.CONSOLE_PKGS)

    def install_console(self, serial, launch=True, log=None):
        apk = self.find_console_apk()
        if not apk:
            return False, "没找到控制台安装包（Botagent.apk），请放到本程序同目录"

        if log:
            log("安装控制台 App：%s" % os.path.basename(apk))
        rc, out, err = self.run(["install", "-r", apk], timeout=180, serial=serial)
        blob = (out or "") + (err or "")
        ok = "Success" in blob
        if not ok:
            if "SHARED_USER" in blob.upper():
                for p in self.CONSOLE_PKGS + ["com.termux.boot"]:
                    self.run(["uninstall", p], timeout=60, serial=serial)
                rc, out, err = self.run(["install", "-r", apk], timeout=180, serial=serial)
                blob = (out or "") + (err or "")
                ok = "Success" in blob
            if not ok and "USER_RESTRICTED" in blob:
                return False, "小米系统拦了安装：开发者选项里打开「USB 安装」再试"

        if log:
            log("控制台 App %s" % ("安装成功" if ok else ("安装失败：" + blob.strip()[:120])),
                "ok" if ok else "err")
        if not ok:
            return False, blob.strip()[:200]

        if launch:
            self.run(["shell", "input keyevent 224"], timeout=15, serial=serial)
            self.run(["shell", "am start -n com.phoneagent/.MainActivity"], timeout=30, serial=serial)
            if log:
                log("已在手机上打开控制台")
        return True, ""

    # ---------- 卸载 ----------
    def kill_app_procs(self, serial, root=True):
        """只杀 cmdline 里带安装目录的进程，避免误杀别的实例。"""
        cmd = (
            "for d in /proc/[0-9]*; do "
            "c=$(tr '\\0' ' ' < $d/cmdline 2>/dev/null); "
            "case \"$c\" in *%s*) kill -9 ${d#/proc/} 2>/dev/null;; esac; "
            "done; echo done" % APP_DIR
        )
        rc, out, err = self.shell(cmd, serial=serial, root=root, timeout=60)
        return rc == 0

    def uninstall(self, serial, purge=False, with_proot=False, root=None):
        """一键卸载。有 root 直接删；无 root 走 Termux 界面自动化，全自动完成。"""
        import time as _t

        steps = []
        if root is None:
            root = self.has_root(serial)

        # 1) 先把配置备份到 /sdcard（两种模式都要，彻底删除时跳过）
        backup = "/sdcard/Download/botagent-config-backup.json"
        if not purge:
            if root:
                self.shell("cp -f %s/config.json %s 2>/dev/null" % (APP_DIR, backup),
                           serial=serial, root=True, timeout=40)
            else:
                # 无 root：在 Termux 里 cp，靠界面自动化输入命令
                self.screen_on(serial)
                opened = self.open_termux(serial)
                if opened:
                    _t.sleep(1.5)
                    self.type_command(serial, "cp -f $HOME/aibot/config.json %s" % backup)
                    _t.sleep(3)
            steps.append(("备份配置到 /sdcard/Download/", True, ""))

        # 2) 停进程 + 删目录
        if root:
            ok = self.kill_app_procs(serial, root=True)
            steps.append(("停止进程", ok, ""))
            rc, _o, err = self.shell("rm -rf " + APP_DIR, serial=serial, root=True, timeout=60)
            steps.append(("删除程序目录", rc == 0, err))
            rc, _o, err = self.shell(
                "rm -f %s/.termux/boot/start-botagent.sh" % TERMUX_HOME,
                serial=serial, root=True, timeout=40)
            steps.append(("移除开机自启", rc == 0, ""))
            if with_proot:
                rc, out, err = self.shell(
                    "proot-distro remove ubuntu >/dev/null 2>&1; echo rc=$?",
                    serial=serial, root=True, timeout=180)
                steps.append(("删除 proot Ubuntu", "rc=0" in out, err))
        else:
            # 无 root：先在 Termux 里尽量清一遍（进程、目录、自启）
            self.screen_on(serial)
            opened = self.open_termux(serial)
            if opened:
                _t.sleep(1.5)
                cmd = ("pkill -f qq_bot.py; pkill -f webui.py; pkill -f prefetch.py; sleep 1; "
                       "rm -rf $HOME/aibot $HOME/.termux/boot/start-botagent.sh; echo CLEANED")
                self.type_command(serial, cmd)
                _t.sleep(6)
                steps.append(("停止进程并删除目录", True, ""))
            else:
                steps.append(("停止进程并删除目录", False, "打不开 Termux"))
            # 无 root 时，卸载 Termux 本身会把 /data/data/com.termux 整个清掉
            steps.append(("删除 proot Ubuntu", True, "随 Termux 一起清除"))

        # 3) 卸载 App 包（控制台 + Termux）
        for pkg, label in (("com.phoneagent", "卸载控制台 App"),
                           ("com.termux.boot", "卸载 Termux:Boot")):
            rc, out, err = self.run(["uninstall", pkg], serial=serial, timeout=120)
            done = ("Success" in (out + err)) or ("not installed" in (out + err).lower()) \
                   or ("DELETE_FAILED" not in (out + err))
            steps.append((label, done, (err or out).strip()[:120]))

        # Termux 本体最后卸（这一步会把容器、python、aibot 全清掉）
        rc, out, err = self.run(["uninstall", "com.termux"], serial=serial, timeout=180)
        blob = (out or "") + (err or "")
        done = "Success" in blob or "not installed" in blob.lower()
        steps.append(("卸载 Termux（含容器与数据）", done, blob.strip()[:120] if not done else ""))

        # 4) 清 sdcard 暂存
        self.shell("rm -rf " + PHONE_TMP, serial=serial, root=root, timeout=40)
        self.shell("rm -f /sdcard/Download/termux.apk", serial=serial, root=root, timeout=30)
        steps.append(("清理手机下载目录", True, ""))

        return steps

    def screen_on(self, serial):
        """亮屏 + 尝试解除锁屏，不然 input 打不进 Termux。"""
        self.run(["shell", "input keyevent 224"], timeout=15, serial=serial)   # WAKEUP
        self.run(["shell", "wm dismiss-keyguard"], timeout=15, serial=serial)
        self.run(["shell", "input keyevent 82"], timeout=15, serial=serial)    # MENU 解锁
        time.sleep(1.2)

    def termux_installed(self, serial):
        """注意：pm list packages com.termux 会把 com.termux.boot 也匹配进来，必须精确比对。"""
        rc, out, _ = self.run(["shell", "pm list packages"], timeout=25, serial=serial)
        for line in (out or "").splitlines():
            if line.strip() == "package:com.termux":
                return True
        return False

    def termux_foreground(self, serial):
        rc, out, _ = self.run(["shell", "dumpsys window | grep -m1 mCurrentFocus"],
                              timeout=20, serial=serial)
        return "com.termux" in out

    def open_termux(self, serial):
        for comp in ("com.termux/.HomeActivity", "com.termux/.app.TermuxActivity"):
            self.run(["shell", "am start -n %s" % comp], timeout=25, serial=serial)
            time.sleep(2.5)
            if self.termux_foreground(serial):
                return True
        # 兜底：用 monkey 拉起来
        self.run(["shell", "monkey -p com.termux -c android.intent.category.LAUNCHER 1"],
                 timeout=25, serial=serial)
        time.sleep(3)
        return self.termux_foreground(serial)

    def type_command(self, serial, cmd):
        """把命令打进当前焦点窗口（空格要写成 %s）。"""
        safe = cmd.replace(" ", "%s")
        self.run(["shell", "input text '%s'" % safe], timeout=30, serial=serial)
        time.sleep(0.6)
        self.run(["shell", "input keyevent 66"], timeout=15, serial=serial)

    def port_listening(self, serial, port=8080):
        """不依赖 root 判断端口是否在监听（读 /proc/net/tcp）。"""
        hexport = "%04X" % port
        rc, out, _ = self.run(["shell", "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null"],
                              timeout=20, serial=serial)
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1].endswith(":" + hexport) and parts[3] == "0A":
                return True
        return False

    def install_noroot_auto(self, serial, cfg, progress=None):
        """无 root 全自动：推到 /sdcard，再通过界面自动化在 Termux 里执行安装。"""
        steps = []

        if not self.termux_installed(serial):
            return [("检查 Termux", False, "手机没装 Termux（先去 F-Droid 装一个）")], ""

        self.screen_on(serial)
        steps.append(("亮屏解锁", True, ""))

        # 写一个 go.sh，Termux 里只要执行这一条
        go_lines = [
            "#!/data/data/com.termux/files/usr/bin/bash",
            "cd /sdcard/Download/botagent || exit 1",
            "LOG=$HOME/botagent-install.log",
            "exec > $LOG 2>&1",
            "set -x",
            "termux-wake-lock 2>/dev/null",
            "termux-setup-storage 2>/dev/null",
            "pkg update -y >/dev/null 2>&1",
            "pkg install -y python curl proot-distro",
            "mkdir -p $HOME/aibot/assets && cp -f *.py $HOME/aibot/",
            "cp -f assets/* $HOME/aibot/assets/ 2>/dev/null",
            "cd $HOME/aibot && bash /sdcard/Download/botagent/install.sh --noninteractive",
            "nohup python webui.py >> $HOME/aibot/webui.log 2>&1 &",
            "nohup python qq_bot.py >> $HOME/aibot/bot.log 2>&1 &",
            "echo BOTAGENT_DONE",
        ]
        tmp = os.path.join(os.environ.get("TEMP", "."), "botagent_go.sh")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(go_lines) + "\n")
        rc, out, err = self.run(["push", tmp, "/sdcard/Download/botagent/go.sh"],
                                timeout=60, serial=serial)
        steps.append(("写入 go.sh", rc == 0, err))

        # 顺便把配置写进 sdcard，让 install.sh --noninteractive 直接用
        cfgp = os.path.join(os.environ.get("TEMP", "."), "botagent_cfg.json")
        with open(cfgp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        rc, out, err = self.run(["push", cfgp, "/sdcard/Download/botagent/config.json"],
                                timeout=60, serial=serial)
        steps.append(("写入配置", rc == 0, err))

        if not self.open_termux(serial):
            steps.append(("打开 Termux", False, "没能切到 Termux 前台（手动打开后重试）"))
            return steps, ""
        steps.append(("打开 Termux", True, ""))

        self.type_command(serial, "bash /sdcard/Download/botagent/go.sh")
        steps.append(("触发安装脚本", True, ""))

        # 轮询端口，最多等 240 秒
        for i in range(48):
            time.sleep(5)
            if self.port_listening(serial, 8080):
                steps.append(("服务已启动", True, ""))
                return steps, ""
            if progress:
                progress(i + 1, 48, "等待服务启动…")
        steps.append(("服务已启动", False, "等了 4 分钟 8080 还没起来"))
        return steps, ""

    def install_rooted(self, serial, cfg):
        """有 root：全自动装进 Termux。"""
        steps = []
        # 1) 确保目录
        rc, out, err = self.shell("mkdir -p %s && chmod 755 %s" % (APP_DIR, APP_DIR),
                                  root=True, serial=serial)
        steps.append(("创建目录", rc == 0, err))
        # 2) 拷文件
        rc, out, err = self.shell("cp -f %s/*.py %s/" % (PHONE_TMP, APP_DIR), root=True, serial=serial)
        steps.append(("复制程序", rc == 0, err))
        # 3) 写配置
        payload = json.dumps(cfg, ensure_ascii=False)
        b64 = __import__("base64").b64encode(payload.encode()).decode()
        rc, out, err = self.shell(
            "echo '%s' | base64 -d > %s/config.json && chmod 600 %s/config.json"
            % (b64, APP_DIR, APP_DIR), root=True, serial=serial)
        steps.append(("写入配置", rc == 0, err))
        # 4) 生成 token
        rc, out, err = self.shell(
            "[ -f %s/webui_token.txt ] || (head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \\n' > %s/webui_token.txt); "
            "chmod 600 %s/webui_token.txt; cat %s/webui_token.txt"
            % (APP_DIR, APP_DIR, APP_DIR, APP_DIR), root=True, serial=serial)
        token = out.strip().splitlines()[-1] if out.strip() else ""
        steps.append(("生成 token", rc == 0, err))
        # 5) 启动
        rc, out, err = self.shell(
            "cd %s && pkill -f qq_bot.py 2>/dev/null; pkill -f webui.py 2>/dev/null; "
            "nohup python webui.py >> logs/webui.log 2>&1 & "
            "nohup python qq_bot.py >> logs/bot.log 2>&1 & echo started"
            % APP_DIR, root=True, serial=serial)
        steps.append(("启动服务", rc == 0, err))
        return steps, token


class App:
    def __init__(self, root):
        self.root = root
        root.title("%s v%s" % (APP_NAME, VERSION))
        root.geometry("860x660")
        root.minsize(820, 600)
        try:
            root.iconbitmap(default=self._icon())
        except Exception:
            pass

        self.d = Deployer(self.log)
        self.serial = None
        self.busy = False

        self._build()

    def _icon(self):
        p = os.path.join(base_dir(), "botagent.ico")
        return p if os.path.isfile(p) else ""

    # ---------------- UI ----------------
    def _build(self):
        pad = {"padx": 12, "pady": 6}

        top = tk.Frame(self.root)
        top.pack(fill="x", **pad)
        tk.Label(top, text="① 连接手机", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        row = tk.Frame(top)
        row.pack(fill="x", pady=4)
        tk.Label(row, text="adb：").pack(side="left")
        self.lb_adb = tk.Label(row, text=self.d.adb or "未找到 adb", fg="#0a0" if self.d.adb else "#c00")
        self.lb_adb.pack(side="left")
        tk.Button(row, text="重新检测", command=self.scan).pack(side="right")
        self.lb_dev = tk.Label(top, text="设备：未检测", fg="#666")
        self.lb_dev.pack(anchor="w")

        mid = tk.Frame(self.root)
        mid.pack(fill="x", **pad)
        tk.Label(mid, text="② 填写信息", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        self.vars = {}
        # 服务商预设：兼容所有 OpenAI 格式接口
        self.PRESETS = {
            "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
            "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
            "通义千问": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
            "本地 Ollama": ("http://127.0.0.1:11434/v1", "qwen2.5:7b"),
            "自定义": ("", ""),
        }
        prow = tk.Frame(mid)
        prow.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 4))
        tk.Label(prow, text="服务商", width=26, anchor="w").pack(side="left")
        self.cb_provider = ttk.Combobox(prow, values=list(self.PRESETS), state="readonly", width=18)
        self.cb_provider.set("DeepSeek")
        self.cb_provider.pack(side="left")
        self.cb_provider.bind("<<ComboboxSelected>>", lambda e: self.apply_preset())
        tk.Label(prow, text="  （任何 OpenAI 兼容接口都行）", fg="#888").pack(side="left")

        fields = [
            ("api_key", "API Key（可空，之后手机上填）", "sk-... 或留空"),
            ("owner", "你的 QQ 号（主人）", "1000001"),
            ("groups", "响应的群号（逗号分隔，可空）", "2000001,2000002"),
            ("bot_uin", "机器人 QQ 号（可空）", ""),
            ("email", "反馈邮箱（可空）", ""),
        ]
        for i, (k, label, ph) in enumerate(fields, start=2):
            tk.Label(mid, text=label, width=26, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            v = tk.StringVar()
            e = tk.Entry(mid, textvariable=v, width=44)
            e.grid(row=i, column=1, sticky="we", pady=3)
            self.vars[k] = v

        tk.Label(mid, text="API 地址", width=26, anchor="w").grid(row=7, column=0, sticky="w", pady=3)
        self.vars["base_url"] = tk.StringVar(value=self.PRESETS["DeepSeek"][0])
        tk.Entry(mid, textvariable=self.vars["base_url"], width=44).grid(row=7, column=1, sticky="we", pady=3)

        tk.Label(mid, text="模型名", width=26, anchor="w").grid(row=8, column=0, sticky="w", pady=3)
        self.vars["model"] = tk.StringVar(value=self.PRESETS["DeepSeek"][1])
        tk.Entry(mid, textvariable=self.vars["model"], width=44).grid(row=8, column=1, sticky="we", pady=3)

        mid.columnconfigure(1, weight=1)

        bot = tk.Frame(self.root)
        bot.pack(fill="x", **pad)
        self.var_auto = tk.BooleanVar(value=True)
        tk.Checkbutton(bot, text="无 root 也全自动（界面自动化）",
                       variable=self.var_auto).pack(side="left", padx=(0, 8))
        self.btn_scan = tk.Button(bot, text="检测环境", width=12, command=self.scan)
        self.btn_scan.pack(side="left")
        self.btn_go = tk.Button(bot, text="开始部署", width=14, bg="#2ea043", fg="white",
                                font=("Microsoft YaHei UI", 10, "bold"), command=self.deploy)
        self.btn_go.pack(side="left", padx=8)
        tk.Button(bot, text="打开控制台", width=12, command=self.open_console).pack(side="left")
        tk.Button(bot, text="一键卸载", width=10, fg="#c0392b", command=self.uninstall).pack(side="left", padx=6)
        tk.Button(bot, text="装控制台App", width=12, bg="#1f6feb", fg="white",
                  command=self.install_console).pack(side="left")
        tk.Button(bot, text="保存日志", width=10, command=self.save_log).pack(side="right")

        self.pb = ttk.Progressbar(self.root, mode="determinate")
        self.pb.pack(fill="x", padx=12, pady=(0, 4))

        tk.Label(self.root, text="③ 日志", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12)
        wrap = tk.Frame(self.root)
        wrap.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.txt = tk.Text(wrap, bg="#111", fg="#ddd", insertbackground="#ddd",
                           font=("Consolas", 9), wrap="word")
        sb = tk.Scrollbar(wrap, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.tag_config("ok", foreground="#7ee787")
        self.txt.tag_config("err", foreground="#ff7b72")
        self.txt.tag_config("warn", foreground="#f2cc60")
        self.txt.tag_config("info", foreground="#79c0ff")

        self.log("Botagent 一键部署 v%s" % VERSION, "info")
        self.scan()

    def log(self, msg, tag=None):
        self.txt.insert("end", "[%s] %s\n" % (time.strftime("%H:%M:%S"), msg), tag or ())
        self.txt.see("end")

    def apply_preset(self):
        name = self.cb_provider.get()
        url, model = self.PRESETS.get(name, ("", ""))
        if url:
            self.vars["base_url"].set(url)
            self.vars["model"].set(model)
            self.log("服务商切到 %s：%s" % (name, url))

    # ---------------- 动作 ----------------
    def scan(self):
        if self.busy:
            return
        self.lb_adb.config(text=self.d.adb or "未找到 adb",
                           fg="#0a0" if self.d.adb else "#c00")
        if not self.d.adb:
            self.lb_dev.config(text="设备：请把 adb.exe 放到本程序同目录，或装 platform-tools", fg="#c00")
            return
        devs = self.d.devices()
        ready = [s for s, st in devs if st == "device"]
        if not devs:
            self.lb_dev.config(text="设备：没检测到（插数据线 → 打开 USB 调试 → 手机上点允许）", fg="#c00")
            self.log("未检测到设备", "warn")
            return
        if not ready:
            self.lb_dev.config(text="设备：%s（未授权，看手机屏幕点「允许」）" % devs[0][0], fg="#c00")
            return
        self.serial = ready[0]
        root = self.d.has_root(self.serial)
        self.lb_dev.config(text="设备：%s   %s" % (self.serial, "已 root（可全自动）" if root else "无 root（半自动）"),
                           fg="#0a0")
        self.log("设备 %s，%s" % (self.serial, "检测到 root" if root else "无 root"), "ok")

    def deploy(self):
        if self.busy:
            return
        if not self.d.adb:
            messagebox.showerror("缺少 adb", "没找到 adb.exe。\n\n请把它放到本程序同目录，\n或安装 Android platform-tools。")
            return
        self.scan()
        if not self.serial:
            messagebox.showerror("没有设备", "请先连接手机并允许 USB 调试。")
            return
        src = find_src()
        if not src:
            messagebox.showerror("缺少源码", "没找到 aibot 目录（含 qq_bot.py）。\n\n请把 aibot 文件夹放在本程序同级目录。")
            return
        key = self.vars["api_key"].get().strip()
        if not key:
            if not messagebox.askyesno("没填 API Key",
                                       "现在没填 Key，装好后机器人还不能对话。\n\n"
                                       "可以在手机控制台「模型」页再填。\n\n仍然继续部署吗？"):
                return
            self.log("未填 API Key：装好后去手机控制台「模型」页填", "warn")

        cfg = {
            "api_key": key,
            "base_url": self.vars["base_url"].get().strip() or "https://api.deepseek.com",
            "model": self.vars["model"].get().strip() or "deepseek-chat",
            "max_steps": 8,
            "max_tokens": 1500,
            "owner_uid": int(self.vars["owner"].get()) if self.vars["owner"].get().strip().isdigit() else 0,
            "adult_uids": [int(self.vars["owner"].get())] if self.vars["owner"].get().strip().isdigit() else [],
            "allowed_private_uids": [int(self.vars["owner"].get())] if self.vars["owner"].get().strip().isdigit() else [],
            "allowed_groups": [int(x) for x in re.split(r"[,，\s]+", self.vars["groups"].get()) if x.isdigit()],
            "safe_groups": [],
            "watch_group": 0,
            "watch_uids": [],
            "bot_uin": int(self.vars["bot_uin"].get()) if self.vars["bot_uin"].get().strip().isdigit() else 0,
            "feedback_email": self.vars["email"].get().strip(),
            "allow_remote": False,
        }
        cfg["safe_groups"] = cfg["allowed_groups"][:1]

        self.busy = True
        self.btn_go.config(state="disabled", text="部署中…")

        def work():
            try:
                self._do_deploy(src, cfg)
            except Exception as e:
                self.log("部署失败：%s" % e, "err")
            finally:
                self.busy = False
                self.btn_go.config(state="normal", text="开始部署")

        threading.Thread(target=work, daemon=True).start()

    def _do_deploy(self, src, cfg):
        self.log("开始部署到 %s" % self.serial, "info")

        # 0) 手机没装 Termux 就由电脑下载并安装
        ok_tx, fresh = self.d.ensure_termux(
            self.serial, log=lambda m, t=None: self.log(m, t))
        if not ok_tx:
            self.log("Termux 自动安装没成功", "warn")
            tip = (
                "手机上没装 Termux，自动装也没成功。\n\n"
                "安装包已经放到手机的 /sdcard/Download/termux.apk\n"
                "（文件管理器里点一下即可安装）\n\n"
                "如果是小米系统，还需要在开发者选项里打开：\n"
                "  · USB 安装\n"
                "  · USB 调试（安全设置）\n\n"
                "装好 Termux 后点「是」，我会继续部署。")
            if not messagebox.askyesno("需要先装 Termux", tip):
                self.log("已取消部署", "warn")
                return
            if not self.d.termux_installed(self.serial):
                messagebox.showwarning("还没检测到 Termux",
                                       "手机里还是没找到 Termux，先装好再点部署。")
                return
            self.log("检测到 Termux 已安装，继续", "ok")
            # 首次手动安装也要等 bootstrap
            self.d.screen_on(self.serial)
            self.d.open_termux(self.serial)
            time.sleep(45)

        # 1) 先把环境配好（存储权限 / 后台 / 电池白名单 / Termux:Boot）
        self.log("配置手机环境…", "info")
        for name, ok, err in self.d.env_prepare(
                self.serial,
                log=lambda n, o, e: self.log("%s %s" % (n, "✓" if o else ("✗ " + (e or "").strip()[:100])),
                                             "ok" if o else "err")):
            pass

        files = self.d.push_files(src, self.serial,
                                  progress=lambda i, n, f: self._progress(i, n, f))
        self.log("已推送 %d 个文件到 %s" % (len(files), PHONE_TMP), "ok")

        rooted = self.d.has_root(self.serial)

        if not rooted and self.var_auto.get():
            self.log("无 root：尝试界面自动化（需要手机装有 Termux）", "warn")
            steps, _ = self.d.install_noroot_auto(self.serial, cfg,
                                                  progress=lambda i, n, m: self._progress(i, n, m))
            ok = True
            for name, passed, err in steps:
                if passed:
                    self.log("%s ✓" % name, "ok")
                else:
                    ok = False
                    self.log("%s ✗ %s" % (name, (err or "").strip()[:160]), "err")
            if ok:
                self.log("部署完成（无 root 全自动）", "ok")
                self.log("控制台：http://127.0.0.1:8080/app", "info")
                messagebox.showinfo("部署完成",
                                    "已在手机上装好并启动。\n\n"
                                    "手机浏览器打开：\nhttp://127.0.0.1:8080/app")
            else:
                self.log("自动化没走通，可以改用「手动模式」", "warn")
                messagebox.showwarning("自动化未成功",
                                       "看日志里的红行。\n\n"
                                       "常见原因：Termux 没装 / 首次打开还在初始化 / 屏幕锁着。")
            return

        if not rooted:
            cmd = ("cd %s && cp -f *.py %s/ 2>/dev/null; "
                   "bash %s/install.sh" % (PHONE_TMP, APP_DIR, PHONE_TMP))
            self.root.clipboard_clear()
            self.root.clipboard_append(cmd)
            self.log("无 root：已把命令复制到剪贴板", "warn")
            self.log("请在手机上打开 Termux，粘贴并回车：", "warn")
            self.log(cmd, "info")
            messagebox.showinfo("需要手动一步",
                                "手机没有 root，无法全自动。\n\n"
                                "已把命令复制到剪贴板。\n"
                                "请在手机上打开 Termux，长按粘贴后回车。")
            return

        steps, token = self.d.install_rooted(self.serial, cfg)
        ok = True
        for name, passed, err in steps:
            if passed:
                self.log("%s ✓" % name, "ok")
            else:
                ok = False
                self.log("%s ✗ %s" % (name, (err or "").strip()[:160]), "err")

        if ok:
            self.log("部署完成", "ok")
            self.log("控制台：http://127.0.0.1:8080/app", "info")
            self.log("token：%s" % token, "info")
            self.show_token = token

            # 顺手把手机控制台 App 装上并打开
            self.log("安装手机控制台 App…", "info")
            app_ok, app_msg = self.d.install_console(
                self.serial, launch=True,
                log=lambda m, t=None: self.log(m, t))

            tip = ("已经装好并启动。\n\n"
                   "手机浏览器打开：\nhttp://127.0.0.1:8080/app\n\n"
                   "token：%s\n（首次显示二维码，扫码登录 QQ）" % token)
            if app_ok:
                tip += "\n\n手机控制台 App 也装好了，桌面上多了个 Botagent 图标。"
            else:
                tip += "\n\n控制台 App 没装上：%s\n（不影响使用，浏览器也能进）" % (app_msg or "未知原因")
            messagebox.showinfo("部署完成", tip)
        else:
            messagebox.showwarning("部分步骤失败", "看日志里的红色行。")

    def _progress(self, i, n, name):
        self.pb["maximum"] = n
        self.pb["value"] = i
        self.log("推 %d/%d %s" % (i, n, name))


    def uninstall(self):
        """一键卸载（有 root 直接删；无 root 走界面自动化，全自动完成）"""
        if self.busy:
            return
        if not self.d.adb:
            messagebox.showerror("缺少 adb", "没找到 adb.exe。")
            return
        self.scan()
        if not self.serial:
            messagebox.showerror("没有设备", "请先连接手机。")
            return

        rooted = self.d.has_root(self.serial)
        extra = "" if rooted else "\n\n注意：没有 root 时，会连 Termux 一起卸载" \
                                 "（容器、Python、程序目录都在里面）。"
        ans = messagebox.askyesnocancel(
            "确认卸载",
            "要从手机上卸载 Botagent 吗？" + extra + "\n\n"
            "选「是」：删除程序，配置备份到 /sdcard/Download/\n"
            "选「否」：连配置一起彻底删除\n"
            "选「取消」：什么都不做")
        if ans is None:
            return
        purge = (ans is False)

        with_proot = False
        if rooted:
            with_proot = messagebox.askyesno(
                "proot 容器",
                "要不要连 proot Ubuntu 一起删？\n\n"
                "（约 500MB，里面有 Linux QQ 和登录状态；\n"
                "   留着的话下次可以复用）")
        else:
            self.log("无 root：会连 Termux 一起卸载，容器随之清除", "warn")

        self.busy = True
        self.btn_go.config(state="disabled")

        def work():
            try:
                self.log("开始卸载（%s）" % ("有 root" if rooted else "无 root 自动"), "info")
                steps = self.d.uninstall(self.serial, purge=purge,
                                         with_proot=with_proot, root=rooted)
                ok_all = True
                for name, passed, err in steps:
                    if passed:
                        self.log("%s ✓" % name, "ok")
                    else:
                        ok_all = False
                        self.log("%s ✗ %s" % (name, (err or "").strip()[:150]), "err")
                if ok_all:
                    self.log("卸载完成" + ("（含配置）" if purge else "（配置已备份）"), "ok")
                    messagebox.showinfo(
                        "卸载完成",
                        "手机上已经没有 Botagent 了。\n\n"
                        + ("配置也删了。" if purge
                           else "配置备份在 /sdcard/Download/botagent-config-backup.json"))
                else:
                    messagebox.showwarning("部分步骤失败", "看日志里的红色行。")
            except Exception as e:
                self.log("卸载出错：%s" % e, "err")
            finally:
                self.busy = False
                self.btn_go.config(state="normal")

        threading.Thread(target=work, daemon=True).start()

    def install_console(self):
        """把手机控制台 App（Botagent.apk）装到手机上并打开。"""
        if self.busy:
            return
        if not self.d.adb:
            messagebox.showerror("缺少 adb", "没找到 adb.exe。")
            return
        self.scan()
        if not self.serial:
            messagebox.showerror("没有设备", "请先连接手机。")
            return
        if not self.d.find_console_apk():
            messagebox.showerror("缺少安装包",
                                 "没找到 Botagent.apk。\n\n"
                                 "把 Botagent.apk 放到本程序同一目录再来点这个按钮。")
            return

        self.busy = True

        def work():
            try:
                ok, msg = self.d.install_console(
                    self.serial, launch=True,
                    log=lambda m, t=None: self.log(m, t))
                if ok:
                    self.log("控制台已装好并在手机上打开", "ok")
                    messagebox.showinfo("完成",
                                        "控制台 App 已安装并打开。\n\n"
                                        "以后在手机上直接点桌面图标即可。")
                else:
                    self.log("控制台安装失败：%s" % msg, "err")
                    messagebox.showwarning("没装上", msg)
            except Exception as e:
                self.log("出错：%s" % e, "err")
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True).start()

    def open_console(self):
        import webbrowser
        webbrowser.open("http://127.0.0.1:8080/app")

    def save_log(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt",
                                         filetypes=[("文本", "*.txt")])
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.txt.get("1.0", "end"))
        self.log("日志已保存：%s" % p, "ok")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
