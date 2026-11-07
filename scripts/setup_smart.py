#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Botagent 智能安装引导（电脑侧，通过 adb）

它会先检查手机上「需要什么」，缺什么补什么，不重复装、不瞎装。

用法：
    python setup_smart.py                # 自动找第一台设备
    python setup_smart.py -s <序列号>     # 指定设备
    python setup_smart.py --dry          # 只体检，不动手
    python setup_smart.py --no-astrbot   # 跳过 AstrBot 检查

特点：
  · 不需要 root（走 adb + run-as）
  · Termux 缺了就自己下载安装（F-Droid 官方包）
  · 每一步都有明确的 成功/跳过/失败 标记
  · 失败会告诉你「为什么」和「下一步该干什么」，不会闷头往下走
"""
import argparse
import base64
import os
import re
import subprocess
import sys
import time
import urllib.request

TERMUX_PKG = "com.termux"
ASTRBOT_PKG = "com.astrbot.astrbot_android"
CONSOLE_PKG = "com.phoneagent"
A11Y_SVC = "com.phoneagent/com.phoneagent.A11yService"

HOME = "/data/data/com.termux/files/home"
PREFIX = "/data/data/com.termux/files/usr"
BASH = PREFIX + "/bin/bash"
PY = PREFIX + "/bin/python3"
AIBOT = HOME + "/aibot"

TERMUX_URLS = [
    # GitHub release（33 MB，arm64-v8a），走 gh-proxy 国内可用
    "https://gh-proxy.com/https://github.com/termux/termux-app/releases/download/"
    "v0.118.3/termux-app_v0.118.3+github-debug_arm64-v8a.apk",
    "https://ghproxy.cc/https://github.com/termux/termux-app/releases/download/"
    "v0.118.3/termux-app_v0.118.3+github-debug_arm64-v8a.apk",
    # 兜底：F-Droid 通用包（97 MB）
    "https://f-droid.org/repo/com.termux_118.apk",
]

# 需要 pip 装的（纯 python，快）
PIP_DEPS = ["websocket-client"]
# 用 pkg 装的（aarch64 有官方包，pip 要编译）
PKG_DEPS = []

C = {
    "ok": "\033[32m", "warn": "\033[33m", "err": "\033[31m",
    "dim": "\033[2m", "b": "\033[1m", "0": "\033[0m",
}


def _build_opener():
    """能用系统代理就用（国内直连 f-droid 经常卡死）。"""
    handlers = []
    proxies = {}
    for env in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(env)
        if v:
            proxies["https"] = v
            proxies["http"] = v
            break
    if not proxies:
        # Clash / v2ray 常见端口，探一下开着没有
        import socket as _s
        for port in (7897, 7890, 10809, 1080):
            sk = _s.socket()
            sk.settimeout(0.3)
            try:
                if sk.connect_ex(("127.0.0.1", port)) == 0:
                    proxies = {"http": "http://127.0.0.1:%d" % port,
                               "https": "http://127.0.0.1:%d" % port}
                    break
            finally:
                sk.close()
    if proxies:
        handlers.append(urllib.request.ProxyHandler(proxies))
        say("走代理下载：%s" % proxies["https"])
    # gh-proxy 这类中转站证书链经常不全，下载 APK 时放宽校验（装完会校验大小）
    import ssl as _ssl
    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


OPENER = None


def c(t, k):
    if os.name == "nt" and not os.environ.get("WT_SESSION"):
        return t
    return C.get(k, "") + t + C["0"]


def say(msg):
    print(c("==> ", "ok") + msg, flush=True)


def info(msg):
    print("    " + msg, flush=True)


def warn(msg):
    print(c("[!] ", "warn") + msg, flush=True)


def err(msg):
    print(c("[x] ", "err") + msg, flush=True)


def hr():
    print(c("-" * 58, "dim"), flush=True)


class Phone:
    def __init__(self, serial=None, dry=False):
        self.serial = serial
        self.dry = dry
        self.report = []          # (name, state, detail)
        self.adb = self._find_adb()

    # ---------- 基础 ----------
    def _find_adb(self):
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, "adb.exe"), "adb"):
            try:
                subprocess.run([p, "version"], capture_output=True, timeout=15)
                return p
            except Exception:
                continue
        return "adb"

    def run(self, args, timeout=120):
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += args
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout)
            out = p.stdout.decode("utf-8", "replace")
            e = p.stderr.decode("utf-8", "replace")
            return p.returncode, out, e
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        except Exception as ex:
            return 1, "", str(ex)

    def sh(self, cmd, timeout=60):
        return self.run(["shell", cmd], timeout=timeout)

    def pick_device(self):
        rc, out, _ = self.run(["devices"])
        devs = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devs.append(parts[0])
        if not devs:
            return None
        self.serial = devs[0]
        return devs

    # ---------- run-as 通道 ----------
    def has_run_as(self):
        rc, out, _ = self.sh("run-as %s %s -c 'echo RUNAS_OK'" % (TERMUX_PKG, BASH), timeout=30)
        return rc == 0 and "RUNAS_OK" in out

    def tx(self, script, timeout=600):
        """在 Termux 里执行一段 bash（脚本走 base64，避免引号地狱）。"""
        full = ("export HOME=%s; export PREFIX=%s; export PATH=$PREFIX/bin:$PATH; "
                "export TMPDIR=$PREFIX/tmp; " % (HOME, PREFIX)) + script
        b64 = base64.b64encode(full.encode()).decode()
        cmd = ("run-as %s %s -c \"echo %s | %s/bin/base64 -d | %s\""
               % (TERMUX_PKG, BASH, b64, PREFIX, BASH))
        return self.sh(cmd, timeout=timeout)

    def tx_read(self, path, n=4000):
        rc, out, _ = self.sh("run-as %s tail -c %d %s" % (TERMUX_PKG, n, path), timeout=40)
        return out if rc == 0 else ""

    # ---------- 检查项 ----------
    def pkg_installed(self, pkg):
        rc, out, _ = self.sh("pm list packages " + pkg, timeout=30)
        return ("package:" + pkg) in out

    def has_root(self):
        rc, out, _ = self.sh("su -c id", timeout=20)
        return rc == 0 and "uid=0" in out

    def termux_ready(self):
        rc, out, _ = self.sh("run-as %s ls %s/bin/bash" % (TERMUX_PKG, PREFIX), timeout=30)
        return rc == 0 and "bash" in out

    def python_ready(self):
        rc, out, _ = self.tx("python -c 'print(1)'", timeout=60)
        return "1" in out

    def aibot_installed(self):
        rc, out, _ = self.sh("run-as %s ls %s/qq_bot.py" % (TERMUX_PKG, AIBOT), timeout=30)
        return "qq_bot.py" in out

    def deps_ready(self):
        rc, out, _ = self.tx('python -c "import websocket; print(\'WS_OK\')"', timeout=60)
        return "WS_OK" in out

    def port_open(self, port):
        rc, out, _ = self.tx(
            "python -c \"import socket;s=socket.socket();"
            "print('OPEN' if s.connect_ex(('127.0.0.1',%d))==0 else 'CLOSED');s.close()\"" % port,
            timeout=40)
        return "OPEN" in out

    def a11y_on(self):
        rc, out, _ = self.sh("settings get secure enabled_accessibility_services", timeout=25)
        return "com.phoneagent" in out

    # ---------- 动作 ----------
    def _unlock_miui(self):
        """MIUI/HyperOS 默认禁止 adb 装应用，这几个键关掉就能装。"""
        keys = [
            "settings put global verifier_verify_adb_installs 0",
            "settings put global package_verifier_enable 0",
            "settings put global adb_install_need_confirm 0",
            "settings put secure adb_install_need_confirm 0",
            "settings put secure install_non_market_apps 1",
            "settings put global usb_install 1",
        ]
        for k in keys:
            self.sh(k, timeout=20)

    def install_apk(self, apk_path, timeout=300):
        """装 APK：先推 /data/local/tmp 用 pm install（绕 MIUI），失败再 adb install。"""
        self._unlock_miui()
        remote = "/data/local/tmp/botagent_install.apk"
        rc, _, e = self.run(["push", apk_path, remote], timeout=300)
        if rc != 0:
            return False, "推包失败：" + e[:100]
        rc, out, er = self.sh("pm install -r -g " + remote, timeout=timeout)
        blob = out + er
        if "Success" in blob:
            return True, ""
        if "INSTALL_FAILED_USER_RESTRICTED" in blob:
            return False, ("小米禁止 USB 安装：设置→更多设置→开发者选项→打开「USB 安装」"
                           "（有的机型还要关「MIUI 优化」），然后重跑")
        if "INSTALL_FAILED_VERSION_DOWNGRADE" in blob:
            return False, "手机上装的版本更高，先卸载旧的"
        # 兜底：adb install
        rc, out2, er2 = self.run(["install", "-r", apk_path], timeout=timeout)
        blob2 = out2 + er2
        if "Success" in blob2:
            return True, ""
        return False, (blob2.strip() or blob.strip()).splitlines()[-1][:160]

    def install_termux(self):
        # 固定文件名不好：上一个进程没退干净会占着句柄
        apk = os.path.join(os.environ.get("TEMP", "."), "termux-smart-%d.apk" % os.getpid())
        # 复用之前下好的（任意 termux-smart-*.apk）
        tmpdir = os.environ.get("TEMP", ".")
        if not (os.path.isfile(apk) and os.path.getsize(apk) > 20 * 1024 * 1024):
            for n in os.listdir(tmpdir) if os.path.isdir(tmpdir) else []:
                if n.startswith("termux-smart") and n.endswith(".apk"):
                    cand = os.path.join(tmpdir, n)
                    if os.path.getsize(cand) > 20 * 1024 * 1024:
                        apk = cand
                        info("复用已下载的 %s" % n)
                        break
        if not (os.path.isfile(apk) and os.path.getsize(apk) > 20 * 1024 * 1024):
            for url in TERMUX_URLS:
                try:
                    info("下载 Termux（约 97 MB，一次就够，之后会复用）")
                    global OPENER
                    if OPENER is None:
                        OPENER = _build_opener()
                    req = urllib.request.Request(url, headers={"User-Agent": "Botagent"})
                    with OPENER.open(req, timeout=600) as r, open(apk, "wb") as f:
                        total = int(r.headers.get("Content-Length") or 0)
                        got = 0
                        step = 4 * 1024 * 1024
                        while True:
                            chunk = r.read(step)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                sys.stdout.write("\r    %5.1f%%  %d/%d MB"
                                                 % (got * 100.0 / total, got // 1048576,
                                                    total // 1048576))
                                sys.stdout.flush()
                    print("", flush=True)
                    break
                except Exception as e:
                    warn("下载失败：%s" % str(e)[:90])
        if os.path.isfile(apk) and os.path.getsize(apk) < 20 * 1024 * 1024:
            try:
                os.remove(apk)
            except Exception:
                pass
        if not os.path.isfile(apk):
            return False, "Termux 安装包没下载到（网络不通；可在电脑上手动下 termux apk 放到临时目录改名 termux-smart.apk）"

        info("安装到手机…")
        return self.install_apk(apk)

    def wait_bootstrap(self, seconds=90):
        """首次装完 Termux 要等它解压 bootstrap。"""
        for i in range(seconds // 5):
            if self.termux_ready():
                return True
            time.sleep(5)
        return False

    def push_bundle(self, src_dir):
        """把 aibot 代码 + install.sh 推到 /sdcard/Download/botagent/。"""
        dst = "/sdcard/Download/botagent"
        self.sh("mkdir -p " + dst)
        files = [f for f in os.listdir(src_dir) if f.endswith((".py", ".sh"))]
        n = 0
        for f in files:
            rc, _, _ = self.run(["push", os.path.join(src_dir, f), dst + "/" + f], timeout=120)
            if rc == 0:
                n += 1
        assets = os.path.join(src_dir, "assets")
        if os.path.isdir(assets):
            self.sh("mkdir -p %s/assets" % dst)
            for f in os.listdir(assets):
                self.run(["push", os.path.join(assets, f), dst + "/assets/" + f], timeout=120)
        return n

    def install_aibot(self):
        """用 run-as 跑安装（不需要 root，也不用在手机上打字）。"""
        script = r"""
cd /sdcard/Download/botagent || exit 1
if [ ! -f install.sh ]; then echo NO_INSTALL_SH; exit 1; fi
export HOME=%(home)s
mkdir -p $HOME/aibot/assets
cp -f *.py $HOME/aibot/ 2>/dev/null
cp -f *.sh $HOME/aibot/ 2>/dev/null
cp -f assets/* $HOME/aibot/assets/ 2>/dev/null
chmod +x $HOME/aibot/*.sh 2>/dev/null
cd $HOME/aibot
bash /sdcard/Download/botagent/install.sh --noninteractive > $HOME/install_smart.log 2>&1
echo INSTALL_RC=$?
tail -3 $HOME/install_smart.log
""" % {"home": HOME}
        rc, out, e = self.tx(script, timeout=900)
        return "INSTALL_RC=0" in out, out + e

    def start_services(self):
        script = r"""
cd %(aibot)s || exit 1
pkill -f webui.py 2>/dev/null; pkill -f qq_bot.py 2>/dev/null
sleep 1
nohup python webui.py >> logs/webui.log 2>&1 &
sleep 2
nohup python qq_bot.py >> logs/bot.log 2>&1 &
sleep 3
echo STARTED
""" % {"aibot": AIBOT}
        rc, out, e = self.tx(script, timeout=180)
        return "STARTED" in out

    def install_console_apk(self, apk_path):
        return self.install_apk(apk_path)

    def enable_a11y(self):
        self.sh("settings put secure enabled_accessibility_services ''")
        self.sh("settings put secure accessibility_enabled 0")
        time.sleep(1.5)
        self.sh("settings put secure enabled_accessibility_services " + A11Y_SVC)
        self.sh("settings put secure accessibility_enabled 1")
        time.sleep(3)
        return self.a11y_on()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-s", "--serial")
    ap.add_argument("--dry", action="store_true", help="只体检，不动手")
    ap.add_argument("--no-astrbot", action="store_true")
    ap.add_argument("--src", default=None, help="aibot 源码目录")
    args = ap.parse_args()

    ph = Phone(args.serial, dry=args.dry)
    here = os.path.dirname(os.path.abspath(__file__))

    print()
    print(c("  Botagent 智能安装", "b"))
    hr()

    say("找设备")
    devs = ph.pick_device()
    if not devs:
        err("没找到设备。检查：数据线是不是只能充电的线 / 手机上有没有点「允许 USB 调试」")
        return 2
    info("设备 %s%s" % (ph.serial, "（检测到 root）" if ph.has_root() else "（无 root，走 run-as）"))

    # ---------------- 体检 ----------------
    say("体检")
    st = {}
    st["termux"] = ph.pkg_installed(TERMUX_PKG)
    st["bootstrap"] = ph.termux_ready() if st["termux"] else False
    st["python"] = ph.python_ready() if st["bootstrap"] else False
    st["aibot"] = ph.aibot_installed() if st["bootstrap"] else False
    st["deps"] = ph.deps_ready() if st["python"] else False
    st["webui"] = ph.port_open(8080) if st["python"] else False
    st["astrbot"] = ph.pkg_installed(ASTRBOT_PKG)
    st["napcat"] = ph.port_open(3001) if st["python"] else False
    st["apk"] = ph.pkg_installed(CONSOLE_PKG)
    st["a11y"] = ph.a11y_on() if st["apk"] else False

    labels = [
        ("termux", "Termux 已装"),
        ("bootstrap", "Termux 初始化完成"),
        ("python", "Python 可用"),
        ("aibot", "程序已安装"),
        ("deps", "依赖齐全（websocket）"),
        ("webui", "控制台 8080 在跑"),
        ("astrbot", "QQ 协议端（AstrBot）已装"),
        ("napcat", "NapCat 端口 3001 通"),
        ("apk", "控制台 App 已装"),
        ("a11y", "无障碍已开"),
    ]
    for k, name in labels:
        mark = c("✓", "ok") if st[k] else c("✗", "err")
        print("    %s %s" % (mark, name))
        ph.report.append((name, st[k]))

    missing = [k for k, _ in labels if not st[k]]
    print()
    if not missing:
        say("全都齐了，不需要做什么")
        return 0
    if args.dry:
        print(c("  缺 %d 项，去掉 --dry 就会自动补" % len(missing), "warn"))
        return 0

    # ---------------- 补 ----------------
    hr()
    say("开始补齐（缺什么补什么）")

    # 1 Termux
    if not st["termux"]:
        ok, msg = ph.install_termux()
        if not ok:
            err(msg)
            print()
            warn("这一步只能你手动做：装好 Termux 再重跑本脚本")
            return 3
        info("Termux 装好了，正在启动它解压 bootstrap（首次约 30~90 秒）")
        # 必须真的把 Termux 拉起来一次，它才会解压引导包
        ph.sh("monkey -p %s -c android.intent.category.LAUNCHER 1" % TERMUX_PKG, timeout=40)
        time.sleep(3)
        if not ph.wait_bootstrap(180):
            ph.sh("am start -n %s/.HomeActivity" % TERMUX_PKG, timeout=30)
            if not ph.wait_bootstrap(120):
                err("Termux 初始化没等到。手动打开 Termux 一次，看到 $ 提示符后再重跑")
                return 3
        st["termux"] = st["bootstrap"] = True
        info("初始化完成")

    # 2 权限 / run-as
    if not ph.has_run_as():
        warn("run-as 不可用（Termux 不是 debuggable 版本？）—— 只能走手动流程")
        print(c("  请在手机 Termux 里粘贴：", "warn"))
        print("    pkg install -y python curl && "
              "bash -c \"$(curl -sL https://cdn.jsdelivr.net/gh/Yehua-1145/-QQbot-@main/install_phone.sh)\"")
        return 4

    ph.sh("pm grant com.termux android.permission.READ_EXTERNAL_STORAGE 2>/dev/null")
    ph.sh("pm grant com.termux android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null")

    # 3 python + 依赖
    if not st["python"] or not st["deps"]:
        say("装 Python 和依赖")
        script = r"""
printf 'deb https://packages.termux.dev/apt/termux-main stable main\n' > $PREFIX/etc/apt/sources.list
pkg update -y >/dev/null 2>&1
pkg install -y python curl unzip >/dev/null 2>&1
python -m pip install --no-cache-dir websocket-client >/dev/null 2>&1
python -c "import websocket; print('DEPS_OK')"
"""
        rc, out, e = ph.tx(script, timeout=1200)
        if "DEPS_OK" not in out:
            err("依赖没装成，看下面输出：")
            print((out + e)[-600:])
            return 5
        info("依赖就绪")
        st["python"] = st["deps"] = True

    # 4 程序
    if not st["aibot"]:
        src = args.src or os.path.join(here, "aibot")
        if not os.path.isdir(src):
            for cand in (os.path.join(here, "..", "aibot"),
                         os.path.join(here, "..", "源码", "aibot"),
                         r"C:\Users\Administrator\Desktop\qq机器人工程\源码\aibot"):
                if os.path.isdir(cand):
                    src = cand
                    break
        if not os.path.isdir(src):
            err("找不到 aibot 源码目录，用 --src 指定")
            return 5
        say("推送程序文件")
        n = ph.push_bundle(src)
        info("推了 %d 个文件" % n)
        say("安装（这条会自动配好配置、token、启动脚本）")
        ok, out = ph.install_aibot()
        if not ok:
            err("安装脚本失败，输出尾部：")
            print(out[-800:])
            return 5
        st["aibot"] = True
        info("程序装好了")

    # 5 启动
    if not st["webui"]:
        say("启动服务")
        if not ph.start_services():
            err("启动失败，进 Termux 手动跑： bash ~/aibot/start.sh")
        time.sleep(4)
        st["webui"] = ph.port_open(8080)
        info("控制台：%s" % ("在跑 ✓" if st["webui"] else "没起来 ✗"))
    st["napcat"] = ph.port_open(3001)

    # 6 AstrBot
    if not args.no_astrbot and not st["astrbot"]:
        warn("QQ 协议端（AstrBot）没装 —— 这一步没法替你自动装（1 GB，且要扫码登录）")
        print("    轻量版 95 MB: https://github.com/MuFengDR/AstrBot-Bubble-Android-App/releases")
        print("    完整版 1 GB : https://github.com/JunWan666/astrbot-for-android/releases")
        print("    装完把 WebSocket 端口设成 3001")

    # 7 控制台 App + 无障碍
    apk = None
    for cand in (os.path.join(here, "Botagent.apk"),
                 r"C:\Users\Administrator\Desktop\qq机器人工程\一键部署-带无障碍\Botagent.apk",
                 r"C:\Users\Administrator\Desktop\qq机器人工程\源码\deploy\pc\Botagent.apk"):
        if os.path.isfile(cand):
            apk = cand
            break
    if not st["apk"] and apk:
        say("装控制台 App（带无障碍）")
        ok, msg = ph.install_console_apk(apk)
        if ok:
            info("装好了")
            st["apk"] = True
        else:
            warn("没装上：%s" % msg)
    if st["apk"] and not ph.a11y_on():
        say("开无障碍")
        if ph.enable_a11y():
            info("已开启")
            st["a11y"] = True
        else:
            warn("没开成功，手动：设置 → 无障碍 → 已下载的服务 → Botagent")

    # ---------------- 总结 ----------------
    hr()
    say("结果")
    for k, name in labels:
        mark = c("✓", "ok") if st[k] else c("✗", "err")
        print("    %s %s" % (mark, name))

    print()
    if st["webui"]:
        print(c("  控制台：", "b") + "http://127.0.0.1:8080/app  （手机上打开）")
    if not st["napcat"]:
        print(c("  QQ 还连不上", "warn") + " —— 装完 AstrBot、端口设 3001，再看 3001 那行")
    elif st["webui"]:
        print(c("  QQ 通道已通", "ok") + "，在 QQ 里发一句试试")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
