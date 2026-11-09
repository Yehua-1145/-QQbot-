# -*- coding: utf-8 -*-
"""
Botagent v2 · 插线部署工具（Windows，带界面）

做的事：
  1. 找 adb（同目录 / platform-tools / PATH）
  2. 列出手机，选一台
  3. 装 APK（装完自动点掉小米的「继续安装」弹窗）
  4. 可选：打开无障碍、启动 App、显示装上的版本号

依赖只有 tkinter + adb（不用 tesseract，识别弹窗用 uiautomator）。
"""

import os
import re
import sys
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_NAME = "Botagent 插线部署"
VERSION = "2.0"
PKG = "com.botagent"

# 常见安装弹窗按钮文案（小米/华为/vivo/oppo 都覆盖）
CONFIRM_WORDS = ["继续安装", "仍然安装", "安装", "打开", "完成", "允许", "确定", "下一步"]


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_adb():
    here = base_dir()
    cands = [
        os.path.join(here, "adb.exe"),
        os.path.join(here, "release", "adb.exe"),
        os.path.join(here, "platform-tools", "adb.exe"),
    ]
    for p in cands:
        if os.path.isfile(p):
            return p
    for p in os.environ.get("PATH", "").split(os.pathsep):
        q = os.path.join(p, "adb.exe")
        if os.path.isfile(q):
            return q
    for p in (os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
              r"D:\platform-tools\adb.exe", r"C:\platform-tools\adb.exe"):
        if os.path.isfile(p):
            return p
    return None


class Deployer(object):
    def __init__(self, log):
        self.adb = find_adb()
        self.log = log

    def run(self, args, timeout=600):
        cmd = [self.adb] + args
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = (p.stdout or b"").decode("utf-8", "replace") + \
              (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out.strip()

    def devices(self):
        if not self.adb:
            return []
        rc, out = self.run(["devices"])
        devs = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            serial, state = line.split("\t")[0], line.split("\t")[-1].strip()
            if state == "device":
                devs.append(serial)
        return devs

    def install(self, serial, apk):
        self.log("安装中…（大包需要 30~90 秒）")
        done = {"ok": False, "out": ""}

        def work():
            try:
                rc, out = self.run(["-s", serial, "install", "-r", apk], timeout=900)
                done["ok"] = (rc == 0 and "Success" in out)
                done["out"] = out
            except Exception as e:  # noqa
                done["out"] = str(e)

        t = threading.Thread(target=work, daemon=True)
        t.start()

        # 边等边帮用户点掉安装确认弹窗
        deadline = time.time() + 300
        while t.is_alive() and time.time() < deadline:
            self.try_confirm(serial)
            time.sleep(3)
        t.join(timeout=5)
        return done["ok"], done["out"]

    def ui_nodes(self, serial):
        rc, _ = self.run(["-s", serial, "shell",
                          "uiautomator dump /sdcard/_ui.xml"], timeout=30)
        tmp = os.path.join(os.environ.get("TEMP", "."), "_botagent_ui.xml")
        rc, _ = self.run(["-s", serial, "pull", "/sdcard/_ui.xml", tmp], timeout=30)
        if not os.path.isfile(tmp):
            return []
        try:
            with open(tmp, "r", encoding="utf-8", errors="replace") as f:
                xml = f.read()
        except Exception:
            return []
        nodes = []
        for m in re.finditer(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
            nodes.append((m.group(1), int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), int(m.group(5))))
        return nodes

    def try_confirm(self, serial):
        for text, x1, y1, x2, y2 in self.ui_nodes(serial):
            if not text:
                continue
            if any(w in text for w in CONFIRM_WORDS):
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                self.run(["-s", serial, "shell", "input tap %d %d" % (cx, cy)], timeout=20)
                self.log("已自动点击「%s」" % text)
                time.sleep(1)
                return True
        return False

    def enable_a11y(self, serial):
        self.run(["-s", serial, "shell",
                  "settings put secure enabled_accessibility_services %s/%s.A11yService"
                  % (PKG, PKG)], timeout=30)
        self.run(["-s", serial, "shell",
                  "settings put secure accessibility_enabled 1"], timeout=30)

    def launch(self, serial):
        self.run(["-s", serial, "shell",
                  "monkey -p %s -c android.intent.category.LAUNCHER 1" % PKG], timeout=60)

    def version(self, serial):
        rc, out = self.run(["-s", serial, "shell",
                            "dumpsys package %s | grep versionName" % PKG], timeout=30)
        m = re.search(r"versionName=(\S+)", out)
        return m.group(1) if m else "?"


class App(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("%s v%s" % (APP_NAME, VERSION))
        self.geometry("720x560")
        self.minsize(660, 520)
        self.d = Deployer(self.log)
        self.dev = tk.StringVar()
        self.apk = tk.StringVar()
        self.opt_a11y = tk.BooleanVar(value=True)
        self.opt_launch = tk.BooleanVar(value=True)
        self.build_ui()
        self.refresh_devices()
        self.autofind_apk()

    # ---------- UI ----------
    def build_ui(self):
        pad = {"padx": 12, "pady": 6}

        box = ttk.LabelFrame(self, text="1. 手机")
        box.pack(fill="x", **pad)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Label(row, text="设备：").pack(side="left")
        self.cb = ttk.Combobox(row, textvariable=self.dev, width=32, state="readonly")
        self.cb.pack(side="left", padx=6)
        ttk.Button(row, text="刷新", command=self.refresh_devices).pack(side="left")
        self.adblbl = ttk.Label(box, text="", foreground="#666")
        self.adblbl.pack(anchor="w", padx=12, pady=(0, 8))

        box2 = ttk.LabelFrame(self, text="2. 安装包")
        box2.pack(fill="x", **pad)
        row2 = ttk.Frame(box2)
        row2.pack(fill="x", padx=10, pady=8)
        ttk.Entry(row2, textvariable=self.apk).pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text="选择…", command=self.pick_apk).pack(side="left", padx=6)

        box3 = ttk.LabelFrame(self, text="3. 选项")
        box3.pack(fill="x", **pad)
        row3 = ttk.Frame(box3)
        row3.pack(fill="x", padx=10, pady=8)
        ttk.Checkbutton(row3, text="装完打开无障碍",
                        variable=self.opt_a11y).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(row3, text="装完启动 App",
                        variable=self.opt_launch).pack(side="left")

        row4 = ttk.Frame(self)
        row4.pack(fill="x", **pad)
        self.btn = ttk.Button(row4, text="开始部署", command=self.start)
        self.btn.pack(side="left")
        ttk.Button(row4, text="清空日志",
                   command=lambda: self.txt.delete("1.0", "end")).pack(side="left", padx=8)

        box4 = ttk.LabelFrame(self, text="日志")
        box4.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.txt = tk.Text(box4, height=14, bg="#0b1e21", fg="#a8e6cf",
                           insertbackground="#fff", relief="flat", wrap="word")
        self.txt.pack(fill="both", expand=True, padx=8, pady=8)

    # ---------- 行为 ----------
    def log(self, msg):
        def put():
            self.txt.insert("end", msg + "\n")
            self.txt.see("end")
        try:
            self.after(0, put)
        except Exception:
            pass

    def refresh_devices(self):
        if not self.d.adb:
            self.adblbl.config(text="找不到 adb：把 platform-tools 放到本目录，或装 Android SDK")
            self.cb["values"] = []
            return
        self.adblbl.config(text="adb: " + self.d.adb)
        devs = self.d.devices()
        self.cb["values"] = devs
        if devs:
            if self.dev.get() not in devs:
                self.dev.set(devs[0])
            self.log("发现 %d 台设备：%s" % (len(devs), ", ".join(devs)))
        else:
            self.dev.set("")
            self.log("没有检测到手机。检查：USB 线、开发者选项、USB 调试授权。")

    def autofind_apk(self):
        here = base_dir()
        cands = [os.path.join(here, "Botagent.apk"),
                 os.path.join(here, "Botagent-v2.0-beta.apk")]
        for c in cands:
            if os.path.isfile(c):
                self.apk.set(c)
                return
        apks = [os.path.join(here, f) for f in os.listdir(here) if f.lower().endswith(".apk")]
        if apks:
            apks.sort(key=os.path.getsize, reverse=True)
            self.apk.set(apks[0])

    def pick_apk(self):
        p = filedialog.askopenfilename(title="选择 APK", filetypes=[("APK", "*.apk")])
        if p:
            self.apk.set(p)

    def start(self):
        serial, apk = self.dev.get().strip(), self.apk.get().strip()
        if not serial:
            messagebox.showwarning("提示", "先选一台设备（点「刷新」）")
            return
        if not apk or not os.path.isfile(apk):
            messagebox.showwarning("提示", "先选 APK 文件")
            return
        mb = round(os.path.getsize(apk) / 1024 / 1024, 1)
        self.log("")
        self.log("=== 开始部署 ===")
        self.log("设备 %s  ←  %s（%.1f MB）" % (serial, os.path.basename(apk), mb))
        self.btn.config(state="disabled")

        def work():
            try:
                ok, out = self.d.install(serial, apk)
                if ok:
                    self.log("安装成功")
                    self.log("版本：" + self.d.version(serial))
                    if self.opt_a11y.get():
                        self.d.enable_a11y(serial)
                        self.log("已写入无障碍设置（个别系统需在手机上确认一次）")
                    if self.opt_launch.get():
                        self.d.launch(serial)
                        self.log("已启动，去手机上按向导走")
                    self.log("完成 ✅")
                else:
                    self.log("安装失败：")
                    for line in (out or "").splitlines()[:12]:
                        self.log("  " + line)
                    if "INSTALL_FAILED_USER_RESTRICTED" in (out or ""):
                        self.log("→ 小米/红米：开发者选项 → 打开「USB 安装」")
                    elif "device not found" in (out or "").lower():
                        self.log("→ 手机掉线了，换线或重插")
            except Exception as e:  # noqa
                self.log("出错：" + str(e))
            finally:
                self.btn.config(state="normal")

        threading.Thread(target=work, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
