#!/usr/bin/env python3
# PhoneAgent WebUI + control panel
# 关键点：聊天走 /api/stream（SSE 流式），模型吐第一个字就显示出来，
# 不用等整段回复生成完。
import http.server
import json
import os
import re
import socketserver
import subprocess
import urllib.parse

import agent


DEFAULT_PERSONA = """你叫「蓝色大肥鱼」，是主人的私人 AI 助手，说话像朋友。
自称「本鱼」，偶尔用鲸鱼/食物的比喻，一次最多一个 emoji。
回答简短直接，别端着，也别反复道歉。
不懂就说不懂，不编造。"""

VERSION = "1.0.0"
APP_DIR = "/data/data/com.termux/files/home/aibot"


def _port_hex(port):
    return ":%04X" % int(port)


def _port_free(port):
    """端口是否已经没人监听（扫 /proc/net/tcp，不依赖 netstat）。"""
    want = _port_hex(port)
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(f) as fh:
                for line in fh.readlines()[1:]:
                    parts = line.split()
                    if len(parts) > 3 and parts[1].endswith(want) and parts[3] == "0A":
                        return False
        except Exception:
            pass
    return True


def _wait_port_free(port, timeout=15.0):
    import time as _t
    end = _t.time() + timeout
    while _t.time() < end:
        if _port_free(port):
            return True
        _t.sleep(0.4)
    return _port_free(port)


def _reap(pattern, exclude_self=True):
    """杀掉 cmdline 里带 pattern 的进程（默认排除自己）。返回杀掉的 pid 列表。"""
    import os as _os
    me = _os.getpid()
    killed = []
    try:
        for pid in _os.listdir("/proc"):
            if not pid.isdigit():
                continue
            n = int(pid)
            if exclude_self and n == me:
                continue
            try:
                cmd = open("/proc/%s/cmdline" % pid, "rb").read().decode("utf-8", "replace")
            except Exception:
                continue
            if pattern in cmd and n not in killed:
                try:
                    _os.kill(n, 9)
                    killed.append(n)
                except Exception:
                    pass
    except Exception:
        pass
    return killed


def _backup_paths():
    return ["config.json", "sent_albums.json", "qq_state.json", "persona.txt", "feedback.jsonl"]


def _do_backup():
    """把配置等打成 zip 放到 /sdcard/Download，返回 (ok, path, 包含文件数)。"""
    import time as _t
    import zipfile as _zip
    ts = _t.strftime("%Y%m%d-%H%M%S")
    out = "/sdcard/Download/botagent-backup-%s.zip" % ts
    n = 0
    try:
        with _zip.ZipFile(out, "w", _zip.ZIP_DEFLATED) as z:
            for name in _backup_paths():
                p = APP_DIR + "/" + name
                if os.path.isfile(p):
                    z.write(p, name)
                    n += 1
            info = {"version": VERSION, "ts": ts}
            z.writestr("BACKUP_INFO.json", __import__("json").dumps(info, ensure_ascii=False))
        return True, out, n
    except Exception as e:
        return False, str(e), 0


def _list_backups():
    import glob as _g
    items = []
    for p in sorted(_g.glob("/sdcard/Download/botagent-backup-*.zip"), reverse=True)[:10]:
        try:
            items.append({"path": p, "name": os.path.basename(p),
                          "size": os.path.getsize(p),
                          "mtime": int(os.path.getmtime(p))})
        except Exception:
            pass
    return items


def _do_restore(path=""):
    """只恢复 config.json，恢复前把现有配置另存一份。"""
    import time as _t
    import zipfile as _zip
    try:
        if not path:
            lst = _list_backups()
            if not lst:
                return False, "没有找到备份文件"
            path = lst[0]["path"]
        if not os.path.isfile(path):
            return False, "备份文件不存在"
        with _zip.ZipFile(path) as z:
            names = z.namelist()
            if "config.json" not in names:
                return False, "备份里没有 config.json"
            data = z.read("config.json")
        old = APP_DIR + "/config.json"
        if os.path.isfile(old):
            import shutil as _sh
            _sh.copyfile(old, old + ".bak." + _t.strftime("%Y%m%d_%H%M%S"))
        with open(old, "wb") as f:
            f.write(data)
        try:
            agent.reload_config()
        except Exception:
            pass
        return True, os.path.basename(path)
    except Exception as e:
        return False, str(e)


def _update_info():
    """本地版本 + 可选的远程版本（config.update_url 指向一个 {"version": "x.y.z"}）。"""
    local = VERSION
    remote = None
    url = ""
    try:
        url = str(_cfg_read().get("update_url") or "")
    except Exception:
        pass
    if url:
        try:
            import json as _json
            import urllib.request as _ur
            with _ur.urlopen(url, timeout=6) as r:
                remote = _json.loads(r.read().decode("utf-8", "replace")).get("version")
        except Exception:
            remote = None
    return {"local": local, "remote": remote, "url": url,
            "has_update": bool(remote and remote != local)}


def _load_token():
    """访问令牌：环境变量 > 本地文件 > 首次随机生成并存盘（不再写死在代码里）。"""
    import os as _os
    import secrets as _secrets
    env = _os.environ.get("PHONEAGENT_TOKEN") or _os.environ.get("BOTAGENT_TOKEN")
    if env:
        return env.strip()
    path = "/data/data/com.termux/files/home/aibot/webui_token.txt"
    try:
        with open(path) as f:
            tok = f.read().strip()
        if tok:
            return tok
    except Exception:
        pass
    tok = _secrets.token_hex(6)
    try:
        with open(path, "w") as f:
            f.write(tok)
        _os.chmod(path, 0o600)
    except Exception:
        pass
    return tok


TOKEN = _load_token()
PORT = 8080
MODE_FILE = "/data/data/com.termux/files/home/aibot/mode.txt"
QR_PATH = ("/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/"
           "installed-rootfs/ubuntu/root/napcat/cache/qrcode.png")


def _mode():
    try:
        with open(MODE_FILE, "r", encoding="utf-8") as f:
            m = f.read().strip().lower()
        return "normal" if m == "normal" else "r18"
    except Exception:
        return "normal"


PANEL = """<!doctype html><meta charset=utf-8><title>Botagent 控制台</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>

#personapage .fbbody,#guidepage .fbbody,#morepage .fbbody,#fbpage 
body.locked{overflow:hidden}
body{font-family:system-ui,sans-serif;margin:0;padding:12px;background:#101418;color:#e8e8e8}
h2{margin:4px 0 12px}
.card{background:#1c232b;border-radius:12px;padding:12px;margin-bottom:10px}
.card h3{margin:0 0 8px;font-size:15px;color:#8fd0ff}
.row{display:flex;gap:8px;flex-wrap:wrap}
button{flex:1;min-width:130px;padding:14px 10px;font-size:15px;border:0;border-radius:10px;
background:#2b6cff;color:#fff;font-weight:600}
button.gray{background:#39424d}
button.red{background:#c23b3b}
button.green{background:#1f9d55}
#out{white-space:pre-wrap;background:#000;color:#3f3;padding:10px;border-radius:10px;
min-height:90px;font-size:13px;margin-top:10px}
</style>
<h2>PhoneAgent 控制台</h2>
<div class=card><h3>群聊</h3><div class=row>
<button class=green onclick="act('group_on')">开放群 994114039</button>
<button class=gray onclick="act('group_off')">关闭群聊</button>
</div></div>
<div class=card><h3>服务</h3><div class=row>
<button onclick="act('restart_bot')">重启 QQ Bot</button>
<button onclick="act('restart_napcat')">重启 NapCat</button>
<button class=gray onclick="act('restart_webui')">重启 WebUI</button>
</div></div>
<div class=card><h3>状态</h3><div class=row>
<button class=gray onclick="act('status')">查看状态</button>
<button class=gray onclick="act('selinux')">SELinux 设为 Permissive</button>
<button class=red onclick="act('force_clash_off')">关 Clash</button>
</div></div>
<div id=out>就绪。</div>
<script>
try{ if('scrollRestoration' in history) history.scrollRestoration='manual'; }catch(e){}
const out=(t)=>{document.getElementById('out').textContent=t;};
async function act(a){
  out('执行 '+a+' ...');
  try{
    const r=await fetch('/api/control?token=__TOKEN__&action='+a);
    out(await r.text());
  }catch(x){out('ERR '+x);}
}
</script>"""


def _sh(cmd, timeout=60):
    try:
        p = subprocess.run(["su", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        return ((p.stdout or "") + (p.stderr or "")).strip() or "(ok)"
    except Exception as e:
        return "(error: %s)" % e


NAP_LOG = ("/data/data/com.astrbot.astrbot_android/files/usr/var/lib/"
           "proot-distro/installed-rootfs/ubuntu/root/napcat_run.log")


def _qr_online():
    try:
        import json as _j
        st = _j.load(open("/data/data/com.termux/files/home/aibot/qq_state.json", encoding="utf-8"))
        return st.get("online") is True
    except Exception:
        return False


_STATUS_CACHE = {"ts": 0.0, "data": None}


def _fast_status():
    """不 fork 子进程的快速状态：直接读 /proc，1~5ms 出结果（原来是 5 次 shell，2 秒）。"""
    import time as _t
    import os as _os
    now = _t.time()
    if _STATUS_CACHE["data"] is not None and (now - _STATUS_CACHE["ts"]) < 1.5:
        return _STATUS_CACHE["data"]

    # 1) 监听端口：直接解析 /proc/net/tcp{,6}
    ports = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(f, "r") as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    if parts[3] != "0A":          # 0A = LISTEN
                        continue
                    try:
                        ports.add(int(parts[1].split(":")[1], 16))
                    except Exception:
                        pass
        except Exception:
            pass

    # 2) 进程数：扫 /proc/*/cmdline
    bot = proot = 0
    try:
        for pid in _os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as fh:
                    cmd = fh.read(400).decode("utf-8", "replace")
            except Exception:
                continue
            if "qq_bot.py" in cmd:
                bot += 1
            elif cmd.startswith("proot") or "/proot" in cmd[:60]:
                proot += 1
    except Exception:
        pass

    # 3) 模式 / 内存：直接读文件
    mode = ""
    try:
        with open("/data/data/com.termux/files/home/aibot/mode.txt") as fh:
            mode = fh.read().strip()
    except Exception:
        pass
    mem = 0
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    mem = int(line.split()[1]) // 1024
                    break
    except Exception:
        pass

    data = {"ports": sorted(str(p) for p in ports if p in (3001, 8080, 6099)),
            "bot": bot, "proot": proot, "mode": mode, "mem_mb": mem}
    _STATUS_CACHE["ts"] = now
    _STATUS_CACHE["data"] = data
    return data


def _newest_qr_url(max_age=180):
    """从 NapCat 日志取最新二维码 URL；超过 max_age 秒的旧码直接算无效。"""
    import re as _re
    import time as _t
    try:
        with open(NAP_LOG, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-800:]
        for i in range(len(lines) - 1, -1, -1):
            if "二维码解码URL" not in lines[i]:
                continue
            u = lines[i].split("URL:", 1)[-1].strip()
            if not u.startswith("https://"):
                continue
            # 往前找最近的带时间戳的行（NapCat 的 URL 行本身没有时间）
            stamp = None
            for j in range(i, max(-1, i - 6), -1):
                m = _re.search(r"(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)", lines[j])
                if m:
                    import datetime as _dt
                    now = _dt.datetime.now()
                    try:
                        t = now.replace(month=int(m.group(1)), day=int(m.group(2)),
                                        hour=int(m.group(3)), minute=int(m.group(4)),
                                        second=int(m.group(5)), microsecond=0)
                    except Exception:
                        t = now
                    stamp = t
                    break
            if stamp is None:
                return u          # 没时间戳就信它
            age = (_dt.datetime.now() - stamp).total_seconds()
            if age > max_age:
                return ""         # 旧码，别给人扫
            return u
    except Exception:
        pass
    return ""


# ---------- NapCat 自身状态（比看日志准确） ----------
NAP_LOG = ("/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/"
           "installed-rootfs/ubuntu/root/napcat_run.log")
NAP_WEBUI_CFG = ("/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/"
                 "installed-rootfs/ubuntu/root/napcat/config/webui.json")
_nap_cache = {"ts": 0, "data": None}
_nap_cred = {"token": None, "cred": None, "until": 0}


def _napcat_token():
    """WebUI token：先读配置，再退回日志里那行 WebUi Token。"""
    try:
        import re as _re
        raw = open(NAP_WEBUI_CFG, encoding="utf-8").read()
        m = _re.search(r'"token"\s*:\s*"([^"]+)"', raw)
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        import re as _re
        txt = open(NAP_LOG, encoding="utf-8", errors="ignore").read()[-20000:]
        got = _re.findall(r"WebUi Token:\s*([0-9a-zA-Z]+)", txt)
        if got:
            return got[-1]
    except Exception:
        pass
    return ""


def _napcat_api(path, body, auth=None, timeout=4):
    import json as _json
    import urllib.request as _ur
    url = "http://127.0.0.1:6099" + path
    data = _json.dumps(body).encode("utf-8")
    req = _ur.Request(url, data=data, headers={"Content-Type": "application/json"})
    if auth:
        req.add_header("Authorization", "Bearer " + auth)
    with _ur.urlopen(req, timeout=timeout) as r:
        return _json.loads(r.read().decode("utf-8", "replace"))


def _napcat_status():
    """返回 {state, phase, uin}。state: online / offline / logged_out / verify / unknown"""
    import hashlib as _hl
    import time as _t

    now = _t.time()
    if _nap_cache["data"] is not None and now - _nap_cache["ts"] < 3:
        return _nap_cache["data"]

    out = {"state": "unknown", "phase": "", "uin": ""}
    try:
        token = _napcat_token()
        if not token:
            raise RuntimeError("no token")

        if _nap_cred["token"] != token or now >= _nap_cred["until"]:
            h = _hl.sha256((token + ".napcat").encode()).hexdigest()
            auth = _napcat_api("/api/auth/login", {"hash": h}).get("data") or {}
            if auth.get("require2FA"):
                raise RuntimeError("2fa")
            _nap_cred["token"] = token
            _nap_cred["cred"] = auth.get("Credential")
            _nap_cred["until"] = now + 45 * 60

        st = _napcat_api("/api/QQLogin/CheckLoginStatus", {},
                         auth=_nap_cred["cred"]).get("data") or {}
        phase = str(st.get("loginPhase") or "")
        if st.get("isLogin") and st.get("coreReady"):
            out["state"] = "online"
        elif st.get("isOffline"):
            out["state"] = "offline"
        elif phase in ("waiting_qrcode", "generating_qrcode"):
            out["state"] = "logged_out"
        elif phase in ("qrcode_scanned", "initializing"):
            out["state"] = "unknown"
        elif phase in ("offline", "reconnecting"):
            out["state"] = "offline"
        elif phase in ("captcha", "verification", "new_device"):
            out["state"] = "verify"
        out["phase"] = phase

        if out["state"] == "online":
            try:
                info = _napcat_api("/api/QQLogin/GetQQLoginInfo", {},
                                   auth=_nap_cred["cred"]).get("data") or {}
                if info.get("online"):
                    uin = str(info.get("uin") or "")
                    if uin.isdigit() and 5 <= len(uin) <= 20:
                        out["uin"] = uin
            except Exception:
                pass
    except Exception:
        pass

    _nap_cache["ts"] = now
    _nap_cache["data"] = out
    return out

def _qr_state():
    """返回二维码图片的 mtime（用来判断新鲜度）。"""
    import os as _os
    try:
        return {"mtime": _os.path.getmtime(QR_PATH)}
    except Exception:
        return {"mtime": 0}


def _qr_page():
    html = """<!doctype html><html lang=zh><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>扫码登录</title>
<style>
body{background:#111;color:#eee;font-family:system-ui;text-align:center;padding:18px}
#box{background:#fff;display:inline-block;padding:10px;border-radius:12px;margin-top:10px}
img{width:300px;height:300px;display:block}
#st{margin-top:14px;font-size:15px;color:#9ad}
#u{word-break:break-all;font-size:11px;color:#666;margin-top:10px}
button{margin-top:14px;padding:10px 18px;font-size:16px;border-radius:10px;border:0;background:#2b7;color:#fff}
</style>
<div style="font-size:20px">扫码登录 QQ</div>
<div id=st>加载中…</div>
<div id=box><img id=q src=""></div>
<button onclick="load(true)">立即刷新</button>
<div id=u></div>
<script>
let last="";
async function load(force){
  try{
    const r=await fetch('/api/qr_url?token=TOKEN',{cache:'no-store'});
    const d=await r.json();
    if(d.online){document.getElementById('st').textContent='已登录，无需扫码';return;}
    if(!d.url){document.getElementById('st').textContent='暂时没有可用二维码，正在等 NapCat 出码…';return;}
    if(force||d.url!==last){
      last=d.url;
      document.getElementById('q').src='/api/qr.png?token=TOKEN&t='+Date.now();
      document.getElementById('u').textContent=d.url;
    }
    const age=d.age>=0?d.age:0;
    document.getElementById('st').textContent = age<90 ? ('有效（'+age+' 秒前生成）') : ('可能已过期（'+age+' 秒前），点下面的按钮刷新');
  }catch(e){document.getElementById('st').textContent='读取失败：'+e;}
}
load(true);
setInterval(load, 4000);
</script>
"""
    return html.replace("TOKEN", TOKEN)


def _remote_html():
    """把当前状态直接渲染进远程面板（不用等 JS 才看到数据）。"""
    online = None
    ts = 0
    try:
        import json as _json
        with open("/data/data/com.termux/files/home/aibot/qq_state.json",
                  "r", encoding="utf-8") as f:
            st = _json.load(f)
        online = st.get("online")
        ts = int(st.get("ts") or 0)
    except Exception:
        pass
    raw = _sh("netstat -tln 2>/dev/null | grep LISTEN")
    ports = [pt for pt in ("3001", "8080", "6099") if re.search(r":%s\b" % pt, raw)]
    try:
        bot = int(_sh("pgrep -f 'qq_bot[.]py' | wc -l").strip() or 0)
    except Exception:
        bot = 0
    try:
        proot = int(_sh("pgrep -x proot | wc -l").strip() or 0)
    except Exception:
        proot = 0
    try:
        with open(MODE_FILE, "r", encoding="utf-8") as f:
            mode = f.read().strip() or "?"
    except Exception:
        mode = "?"

    if online is True:
        qq, qqc = "在线", "on"
    elif online is False:
        import time as _t
        age = ""
        if ts:
            d = max(0, int(_t.time()) - ts)
            age = "（%s前）" % ("%d 分钟" % (d // 60) if d >= 60 else "%d 秒" % d)
        qq, qqc = "离线" + age, "off"
    else:
        qq, qqc = "未知", "warn"

    html = (REMOTE.replace("__TOKEN__", TOKEN)
            .replace("__QQCLS__", qqc).replace("__QQ__", qq)
            .replace("__BOTCLS__", "on" if bot > 0 else "off")
            .replace("__BOT__", ("运行中 (%d)" % bot) if bot > 0 else "未运行")
            .replace("__NPCLS__", "on" if proot > 0 else "off")
            .replace("__NP__", "运行中" if proot > 0 else "未运行")
            .replace("__PORTS__", " · ".join(ports) if ports else "无")
            .replace("__MODE__", mode))
    return html


REMOTE = """<!doctype html><html lang=zh><meta charset=utf-8>
<title>PhoneAgent 远程</title>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1">
<style>
*{box-sizing:border-box}
body{margin:0;padding:14px;font-family:system-ui,-apple-system,"PingFang SC",sans-serif;
background:#0e1116;color:#e6edf3;-webkit-text-size-adjust:100%;overflow-x:hidden;max-width:100%}
h1{font-size:19px;margin:2px 0 14px;font-weight:700}
.card{background:#171c23;border:1px solid #232b35;border-radius:14px;padding:14px;margin-bottom:12px}
.row{display:flex;gap:10px;flex-wrap:wrap;width:100%}
button{flex:1 1 calc(50% - 5px);min-width:0;min-height:52px;font-size:15px;font-weight:600;border:0;
border-radius:12px;background:#2f6df6;color:#fff;padding:12px 8px;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
button.gray{background:#2a323c}button.red{background:#c0392b}button.green{background:#1f9d55}
button:active{opacity:.75}
.stat{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;
font-size:15px;border-bottom:1px solid #202833;width:100%}
.stat:last-child{border-bottom:0}
.k{color:#8b98a8;flex:0 0 auto}
.v{font-weight:700;text-align:right;margin-left:auto;min-width:0;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap;max-width:62%}
.on{color:#3fb950}.off{color:#f85149}.warn{color:#d29922}
#qrbox{display:none;text-align:center}
#qr{width:100%;max-width:340px;border-radius:12px;background:#fff;padding:8px}
#qrurl{word-break:break-all;font-size:11px;color:#8b98a8;margin-top:8px}
#msg{white-space:pre-wrap;font-size:13px;color:#9aa7b6;margin-top:10px;min-height:18px}
#hint{font-size:12px;color:#8b98a8;margin-top:6px}
</style>
<h1>📱 PhoneAgent 远程</h1>

<div class=card>
  <div class=stat><span class=k>QQ 账号</span><span id=s-qq class="v __QQCLS__">__QQ__</span></div>
  <div class=stat><span class=k>机器人</span><span id=s-bot class="v __BOTCLS__">__BOT__</span></div>
  <div class=stat><span class=k>NapCat 容器</span><span id=s-np class="v __NPCLS__">__NP__</span></div>
  <div class=stat><span class=k>端口</span><span id=s-port class=v>__PORTS__</span></div>
  <div class=stat><span class=k>模式</span><span id=s-mode class=v>__MODE__</span></div>
</div>

<div id=qrbox class=card>
  <div style="font-weight:700;margin-bottom:10px">扫码登录 QQ</div>
  <img id=qr alt="二维码">
  <div id=qrurl></div>
  <div id=hint>每 8 秒自动刷新；用要登录的那个 QQ 扫</div>
</div>

<div class=card>
  <div class=row style="margin-bottom:10px">
    <button onclick="act('restart_bot')">🔄 重启机器人</button>
    <button class=gray onclick="act('restart_napcat')">📡 重启协议</button>
  </div>
  <div class=row style="margin-bottom:10px">
    <button class=green onclick="act('qr')">📷 重新出码</button>
    <button class=gray onclick="act('restart_webui')">♻️ 重启面板</button>
  </div>
  <div class=row>
    <button class=gray onclick="setMode('r18')">R18</button>
    <button class=gray onclick="setMode('normal')">正常</button>
  </div>
  <div id=msg></div>
</div>

<script>
const T="__TOKEN__";
const $=id=>document.getElementById(id);
function say(t){$('msg').textContent=t;}
async function act(a){
  say('执行 '+a+' …');
  try{
    const r=await fetch('/api/control?token='+T+'&action='+a);
    say(await r.text()); refresh();
  }catch(e){say('错误 '+e);}
}
async function setMode(m){
  try{
    const r=await fetch('/api/control?token='+T+'&action=mode&value='+m);
    say(await r.text()); refresh();
  }catch(e){say('错误 '+e);}
}
function fmtAge(sec){
  if(!sec||sec<0) return '';
  if(sec<60) return sec+' 秒前';
  if(sec<3600) return Math.floor(sec/60)+' 分钟前';
  return Math.floor(sec/3600)+' 小时前';
}
async function refresh(){
  try{
    const r=await fetch('/api/qq?token='+T,{cache:'no-store'});
    const d=await r.json();
    const qq=$('s-qq');
    if(d.online===true){qq.textContent='在线';qq.className='v on';}
    else if(d.online===false){qq.textContent='离线';qq.className='v off';}
    else {qq.textContent='未知';qq.className='v warn';}
    $('s-bot').textContent = d.bot>0 ? ('运行中 ('+d.bot+')') : '未运行';
    $('s-bot').className='v '+(d.bot>0?'on':'off');
    $('s-np').textContent = d.proot>0 ? '运行中' : '未运行';
    $('s-np').className='v '+(d.proot>0?'on':'off');
    $('s-port').textContent = (d.ports&&d.ports.length?d.ports.join(' · '):'无');
    $('s-port').className='v '+(d.ports&&d.ports.length>1?'on':'warn');
    $('s-mode').textContent = d.mode||'?';
    const ts=d.ts?Math.floor(Date.now()/1000)-d.ts:0;
    if(d.online===false){
      $('qrbox').style.display='block';
      const bust=Date.now();
      $('qr').src='/api/qr.png?token='+T+'&t='+bust;
      $('qrurl').textContent = d.qr_url ? ('备用链接：'+d.qr_url) : '';
      $('hint').textContent = '离线'+(ts?'（'+fmtAge(ts)+'）':'')+'；每 8 秒自动刷新，用要登录的 QQ 扫';
    } else {
      $('qrbox').style.display = 'none';
    }
  }catch(e){ $('s-qq').textContent='面板连不上'; $('s-qq').className='v off'; }
}
refresh(); setInterval(refresh, 5000);
</script></html>"""


def _act(action, value=""):
    if action == "ping":
        return "pong"
    if action == "mode":
        m = (value or "").strip().lower()
        if m not in ("normal", "r18", "auto", "e", "j"):
            return "(mode must be normal/r18)"
        try:
            with open(MODE_FILE, "w", encoding="utf-8") as f:
                f.write("r18" if m in ("auto", "e", "j") else m)
            return "mode -> %s" % m
        except Exception as e:
            return "(mode error: %s)" % e
    if action == "qr":
        # 用日志里"最新"的解码 URL 现生成图片（qrcode.png 可能还是旧的）
        dst = "/sdcard/Download/qq_qr.png"
        if _qr_online():
            return "QQ 现在是登录状态，不需要二维码。"
        u = _newest_qr_url(180)
        if not u:
            return ("二维码已过期（NapCat 每次只更新日志里的 URL）。\n"
                    "需要新码的话：点「重启协议」重启 NapCat，或说一声我来拉一张。")
        if u:
            try:
                import urllib.parse as _up
                link = ("https://api.qrserver.com/v1/create-qr-code/"
                        "?size=560x560&margin=8&data=" + _up.quote(u, safe=""))
                _sh("curl -s -m 25 -o '%s' '%s' && chmod 666 '%s'" % (dst, link, dst))
                if _sh("test -s '%s' && echo YES" % dst).endswith("YES"):
                    return "二维码已是最新（来自日志 URL）-> " + dst
            except Exception:
                pass
        src = ("/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/"
               "installed-rootfs/ubuntu/root/napcat/cache/qrcode.png")
        _sh("test -f '%s' && cp '%s' '%s' && chmod 666 '%s'" % (src, src, dst, dst))
        ok = _sh("test -s '%s' && echo YES" % dst).endswith("YES")
        return ("二维码已导出（旧图兜底）: " + dst) if ok else "没找到二维码（NapCat 可能还没启动）"
    if action == "group_on":
        return _sh("grep -q 'ALLOWED_GROUPS' /data/data/com.termux/files/home/aibot/qq_bot.py && echo '群聊 994114039 已启用（@bot 才会回复）'")
    if action == "group_off":
        return _sh("sed -i 's/ALLOWED_GROUPS = {994114039}/ALLOWED_GROUPS = set()/' /data/data/com.termux/files/home/aibot/qq_bot.py && echo '群聊已关闭'")
    if action == "restart_bot":
        _sh("sh /data/local/tmp/start_bot.sh")
        tail = _sh("sleep 6; tail -3 /data/data/com.termux/files/home/aibot/qq_bot.log")
        return "Bot 重启中（root）\n" + tail
    if action == "restart_napcat":
        _sh("sh /data/local/tmp/restart_napcat.sh")
        return "NapCat 重启中（约 60-75 秒）"
    if action == "restart_webui":
        _sh("sh /data/local/tmp/start_webui.sh")
        return "WebUI 重启中"
    if action == "selinux":
        return _sh("setenforce 0; getenforce")
    if action == "force_clash_off":
        return _sh("am force-stop com.github.metacubex.clash.meta; echo 'Clash 已关闭'")
    if action == "status":
        _st = _fast_status()
        up = _st["ports"]
        bot = str(_st["bot"])
        proot = str(_st["proot"])
        mode = _st["mode"]
        mem = str(_st["mem_mb"])
        lines = [
            "模式: " + (mode or "?"),
            "在线端口: " + (" ".join(up) if up else "无"),
            "qq_bot: %s 个    proot: %s 个" % (bot or "0", proot or "0"),
            "可用内存: %s MB" % (mem or "?"),
        ]
        return "\n".join(lines)
    return "(unknown action)"



FEEDBACK_LOG = "/data/data/com.termux/files/home/aibot/feedback.jsonl"


def _feedback_send(text):
    """反馈：有 SMTP 配置就发邮件，没有就落盘排队（不丢）。"""
    import json as _j
    import time as _t
    rec = {"ts": int(_t.time()), "text": text[:4000], "sent": False}
    cfg = _cfg_read()
    smtp = cfg.get("smtp") or {}
    host = smtp.get("host") or ""
    user = smtp.get("user") or ""
    pwd = smtp.get("pass") or ""
    to = smtp.get("to") or _cfg_read().get("feedback_email") or ""
    err = ""
    if host and user and pwd:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.header import Header
            port = int(smtp.get("port") or 465)
            msg = MIMEText(text, "plain", "utf-8")
            msg["Subject"] = Header("Botagent 反馈", "utf-8")
            msg["From"] = user
            msg["To"] = to
            srv = smtplib.SMTP_SSL(host, port, timeout=20)
            srv.login(user, pwd)
            srv.sendmail(user, [to], msg.as_string())
            srv.quit()
            rec["sent"] = True
        except Exception as e:
            err = str(e)[:200]
    try:
        with open(FEEDBACK_LOG, "a", encoding="utf-8") as f:
            f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    if rec["sent"]:
        return {"ok": True, "sent": True, "to": to}
    return {"ok": True, "sent": False, "queued": True, "error": err,
            "hint": "已保存到本地队列（未配置 SMTP，或发送失败）"}


# ================= 控制台后端（配置 / 模型 / 日志 / 操作） =================
CFG_PATH = "/data/data/com.termux/files/home/aibot/config.json"
GALLERY_DIR = "/sdcard/Pictures/大肥鱼图库"


def _cfg_read():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _cfg_write(d):
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CFG_PATH)


def _mask(k):
    if not k:
        return ""
    return k[:5] + "****" + k[-4:] if len(k) > 12 else "****"


def _gallery_stats():
    import os as _os
    import subprocess as _sp
    out = {"cos": 0, "set": 0, "manga": 0, "total": 0, "safe": 0}
    try:
        for f in _os.listdir(_GALLERY_DIR + "/r18"):
            if f.startswith("p_"):
                out["cos"] += 1
            elif f.startswith("s_"):
                out["set"] += 1
            elif f.startswith("m_"):
                out["manga"] += 1
            out["total"] += 1
    except Exception:
        pass
    try:
        out["safe"] = len(_os.listdir(_GALLERY_DIR + "/safe"))
    except Exception:
        pass
    if out["total"] == 0:
        try:
            cmd = ("cd '%s/r18' 2>/dev/null && "
                   "echo cos=$(ls | grep -c '^p_') set=$(ls | grep -c '^s_') "
                   "manga=$(ls | grep -c '^m_') total=$(ls | wc -l); "
                   "echo safe=$(ls '%s/safe' 2>/dev/null | wc -l)" % (GALLERY_DIR, GALLERY_DIR))
            o = _sp.run(["su", "-c", cmd], capture_output=True, timeout=10).stdout.decode("utf-8", "replace")
            for part in o.replace("\n", " ").split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    if k in out:
                        try:
                            out[k] = int(v)
                        except Exception:
                            pass
        except Exception:
            pass
    out["mem_mb"] = _fast_status()["mem_mb"]
    return out


def _model_status():
    """读取 agent 的运行期状态；agent 未加载时给出配置文件里的值。"""
    cfg = _cfg_read()
    info = {"provider": "", "model": "", "base_url": "", "key_set": False,
            "key_hint": "", "last_latency": 0, "last_error": "",
            "cooldown": 0, "max_steps": 0, "max_tokens": 0}
    try:
        import sys as _sys
        _sys.path.insert(0, "/data/data/com.termux/files/home/aibot")
        import agent as _a
        url = getattr(_a, "API_URL", "") or ""
        info["base_url"] = url
        info["model"] = getattr(_a, "MODEL", "") or ""
        info["max_steps"] = getattr(_a, "MAX_STEPS", 0)
        info["max_tokens"] = getattr(_a, "MAX_TOKENS", 0)
        key = getattr(_a, "DEEPSEEK_KEY", "") or ""
        info["key_set"] = bool(key)
        info["key_hint"] = _mask(key)
        info["last_latency"] = round(getattr(_a, "LAST_LATENCY", [0.0])[0], 2)
        info["last_error"] = (getattr(_a, "LAST_ERROR_TEXT", [""])[0] or "")[:120]
        if "deepseek" in url:
            info["provider"] = "DeepSeek"
        elif "openai" in url:
            info["provider"] = "OpenAI"
        elif "moonshot" in url:
            info["provider"] = "Moonshot"
        elif "dashscope" in url or "aliyun" in url:
            info["provider"] = "通义"
        else:
            info["provider"] = "自定义" if url else "—"
    except Exception:
        key = cfg.get("api_key", "")
        info["key_set"] = bool(key)
        info["key_hint"] = _mask(key)
        info["base_url"] = cfg.get("base_url", "")
        info["model"] = cfg.get("model", "")
        info["max_steps"] = cfg.get("max_steps", 0)
        info["max_tokens"] = cfg.get("max_tokens", 0)
    # 冷却：读取 bot 进程内的降温度（用文件共享）
    try:
        import time as _t
        with open("/data/data/com.termux/files/home/aibot/api_cooldown.txt") as f:
            until = float(f.read().strip() or 0)
        info["cooldown"] = max(0, int(until - _t.time()))
    except Exception:
        pass
    return info


_SECRET_PATTERNS = [
    (r"sk-[A-Za-z0-9_\-]{8,}", "sk-***"),
    (r"(?i)(token|password|passwd|credential|secret)\s*[=:]\s*\S+", r"\1=***"),
    (r"(?i)authorization\s*:\s*Bearer\s+\S+", "authorization: Bearer ***"),
    (r"qrcode[^\s]*://\S+", "<二维码链接已隐藏>"),
    (r"(?i)api[_-]?key\s*[=:]\s*\S+", "api_key=***"),
]


def _redact(text):
    """把日志里的 key / token / 二维码链接抹掉，避免截图外泄。"""
    try:
        import re as _re
        for pat, rep in _SECRET_PATTERNS:
            text = _re.sub(pat, rep, text)
    except Exception:
        pass
    return text



def _tail(path, n=60):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 64 * 1024))
            data = f.read().decode("utf-8", "replace")
        return [_redact(x) for x in data.splitlines()[-n:]]
    except Exception:
        return []


def _console_action(action):
    """控制台的按钮实现。全部走 shell，返回 (ok, msg, data)。"""
    import subprocess as _sp
    A = "/data/data/com.termux/files/home/aibot"
    PY = "/data/data/com.termux/files/usr/bin/python3"

    def run(cmd, timeout=90):
        try:
            p = _sp.run(["su", "-c", cmd], capture_output=True, timeout=timeout)
            return p.returncode, (p.stdout or b"").decode("utf-8", "replace"), (p.stderr or b"").decode("utf-8", "replace")
        except Exception as e:
            return 1, "", str(e)

    if action == "restart_bot":
        killed = _reap("qq_bot.py")
        _wait_port_free(3001, 3)
        rc, o, e = run("sh /data/local/tmp/hard_restart_bot.sh", 120)
        return (rc == 0), "bot 已重启（清理 %d 个旧进程）" % len(killed), {"out": o[-400:], "err": e[-200:]}

    if action == "restart_webui":
        killed = _reap("webui.py")
        freed = _wait_port_free(8080, 12)
        run("cd %s && setsid sh run_webui.sh </dev/null >>webui.log 2>&1 &" % A, 15)
        return True, "webui 已重启（端口%s）" % ("已释放" if freed else "仍占用"), {"killed": killed}

    if action == "rotate":
        rc, o, e = run("cd %s && PF_ANYTIME=1 nice -n 15 %s prefetch.py --rotate "
                       ">>/sdcard/aux/pf_console.log 2>&1" % (A, PY), 240)
        return (rc == 0), "已换新一批图（旧的删掉，配额重新计算）", {}

    if action == "backup":
        ok, info, n = _do_backup()
        return ok, ("已备份 %d 个文件：%s" % (n, info)) if ok else info, {"count": n}

    if action == "restore":
        ok, info = _do_restore()
        return ok, ("已从 %s 恢复配置" % info) if ok else info, {}

    if action == "list_backups":
        return True, "ok", {"backups": _list_backups()}

    if action == "restart_napcat":
        rc, o, e = run("sh /data/local/tmp/restart_nap.sh", 180)
        return (rc == 0), "NapCat 重启中（约 60 秒）", {}

    if action == "qr_restart":
        # 快速登录/密码登录都失败时，强制走扫码：临时停用凭据文件再重启
        run("if [ -f /data/local/tmp/.napcat_secret ]; then "
            "mv -f /data/local/tmp/.napcat_secret /data/local/tmp/.napcat_secret.off; fi", 20)
        run("rm -f " + QR_PATH + " 2>/dev/null", 20)
        _wait_port_free(3001, 20)
        rc, o, e = run("sh /data/local/tmp/restart_nap.sh", 180)
        return (rc == 0), "正在强制重新生成二维码（约 50~70 秒）", {}

    if action == "prefetch":
        rc, o, e = run("cd %s && PF_ANYTIME=1 PF_FORCE_JM=1 setsid nice -n 15 %s prefetch.py --now "
                       ">/sdcard/aux/pf_console.log 2>&1 < /dev/null &" % (A, PY), 20)
        return True, "已触发抓图（后台）", {}

    if action == "clean":
        rc, o, e = run("rm -rf %s/jm/* /sdcard/Pictures/.thumbnails 2>/dev/null; "
                       "sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null; echo ok" % A, 60)
        return (rc == 0), "缓存已清理", {}

    if action == "stats":
        return True, "ok", {"gallery": _gallery_stats(), "model": _model_status(),
                            "proc": _fast_status()}

    if action == "reboot_bot":
        # 重载配置：改完 config.json 后重启 bot 生效
        rc, o, e = run("sh /data/local/tmp/hard_restart_bot.sh", 120)
        return (rc == 0), "配置已重载（bot 已重启）", {}

    return False, "未知操作", {}


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """单线程服务器会让一个长请求把 ping/控制按钮全堵死，这里改成多线程。"""
    daemon_threads = True
    allow_reuse_address = True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        pass

    def _authorized(self):
        # 本机（回环地址）请求免 token：手机上的 App 直接访问 127.0.0.1 就能用，
        # 局域网/外部访问仍然需要 token。
        try:
            if self.client_address and self.client_address[0] in ("127.0.0.1", "::1", "localhost"):
                return True
        except Exception:
            pass
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        return params.get("token", [""])[0] == TOKEN or self.headers.get("X-Token") == TOKEN

    def _json(self, obj):
        import json as _j
        data = _j.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _is_local(self):
        try:
            return self.client_address[0] in ("127.0.0.1", "::1", "localhost")
        except Exception:
            return False

    def _remote_allowed(self):
        """config.json 里 allow_remote=true 才允许外网访问危险接口。默认关。"""
        try:
            return bool(_cfg_read().get("allow_remote"))
        except Exception:
            return False

    def _guard_dangerous(self):
        """返回 True 表示放行。"""
        if self._is_local():
            return True
        if self._remote_allowed():
            return True
        self._json({"ok": False, "error": "只允许本机访问（如需远程请设置 allow_remote）"})
        return False

    def _html(self, data, cache=False):
        data = data.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if not cache else "max-age=60")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/remote", "/r"):
            # 手机远程面板（小米12S Pro 等）：状态 + 重启 + 二维码
            if not self._authorized():
                self._html("<meta charset=utf-8><h3>需要 token</h3>"
                           "<p>请在网址后面加 <code>?token=你的token</code></p>")
                return
            self._html(_remote_html())
            return
        if path == "/api/qq":
            if not self._authorized():
                self.send_response(401)
                self.end_headers()
                return
            import json as _json
            out = {"online": None, "ts": 0, "bot": 0, "proot": 0,
                   "ports": [], "mode": "", "qr_mtime": 0, "qr_url": "",
                "nap_state": "unknown", "nap_phase": "", "uin": ""}
            try:
                with open("/data/data/com.termux/files/home/aibot/qq_state.json",
                          "r", encoding="utf-8") as f:
                    st = _json.load(f)
                out["online"] = st.get("online")
                out["ts"] = st.get("ts", 0)
            except Exception:
                pass
            _st = _fast_status()
            out["ports"] = _st["ports"]
            out["bot"] = _st["bot"]
            out["proot"] = _st["proot"]
            try:
                with open(MODE_FILE, "r", encoding="utf-8") as f:
                    out["mode"] = f.read().strip()
            except Exception:
                pass
            try:
                import os as _os
                try:
                    _rs = "/sdcard/Pictures/大肥鱼图库/rotate_state.json"
                    if _os.path.isfile(_rs):
                        import json as _j2
                        _rst = _j2.load(open(_rs, encoding="utf-8"))
                        out["rotate_last"] = int(_rst.get("last") or 0)
                        out["rotate_total"] = int(_rst.get("total") or 0)
                        out["rotate_removed"] = _rst.get("removed") or {}
                except Exception:
                    pass
                try:
                    _nap = _napcat_status()
                    out["nap_state"] = _nap["state"]
                    out["nap_phase"] = _nap["phase"]
                    if _nap["uin"]:
                        out["uin"] = _nap["uin"]
                except Exception:
                    out["nap_state"] = "unknown"
                    out["nap_phase"] = ""
                out["qr_mtime"] = int(_os.path.getmtime(QR_PATH))
            except Exception:
                pass
            # 从 napcat 日志里捞最新的二维码解码 URL（PNG 没生成时也能用）
            try:
                _log = ("/data/data/com.astrbot.astrbot_android/files/usr/var/lib/"
                        "proot-distro/installed-rootfs/ubuntu/root/napcat_run.log")
                with open(_log, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-400:]
                for ln in reversed(lines):
                    if "二维码解码URL" in ln:
                        out["qr_url"] = ln.split("URL:", 1)[-1].strip()
                        break
            except Exception:
                pass
            data = _json.dumps(out).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/panel":
            self._html(PANEL.replace("__TOKEN__", TOKEN))
            return
        if path.startswith("/assets/"):
            import os as _os
            name = _os.path.basename(path)
            fpath = "/data/data/com.termux/files/home/aibot/assets/" + name
            # 原图放 /sdcard/Download/welcome.gif 就优先用它（真·动图）
            if name.endswith(".gif"):
                for cand in ("/sdcard/Download/welcome.gif",
                             "/sdcard/Pictures/welcome.gif",
                             "/data/data/com.termux/files/home/aibot/assets/welcome.gif"):
                    if _os.path.isfile(cand):
                        fpath = cand
                        break
            if not _os.path.isfile(fpath):
                self.send_response(404)
                self.end_headers()
                return
            ctype = "image/webp" if name.endswith(".webp") else (
                "image/gif" if name.endswith(".gif") else (
                "image/png" if name.endswith(".png") else "application/octet-stream"))
            with open(fpath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path in ("/app", "/app/"):
            _cfg_ui = _cfg_read()
            _bili = str(_cfg_ui.get("bili_url") or "https://space.bilibili.com/")
            _fem = str(_cfg_ui.get("feedback_email") or "you@example.com")
            _page = (APP2.replace("__TOKEN__", TOKEN)
                          .replace("__BILI_URL__", _bili)
                          .replace("__FB_EMAIL__", _fem))
            self._html(_page)
            return
        if path == "/qr":
            html = _qr_page()
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/qr_url":
            import json as _j
            import time as _t
            u = _newest_qr_url(600)
            st = _qr_state()
            age = int(_t.time() - st.get("mtime", 0)) if st.get("mtime") else -1
            body = _j.dumps({"url": u, "age": age, "online": _qr_online()},
                            ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/qr.png":
            if not self._authorized():
                self.send_response(401)
                self.end_headers()
                return
            # 已经登录成功就不给码了（旧码没用还可能误导）
            try:
                import json as _j
                st = _j.load(open("/data/data/com.termux/files/home/aibot/qq_state.json", encoding="utf-8"))
                if st.get("online") is True:
                    msg = b"already logged in"
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(msg)))
                    self.end_headers()
                    self.wfile.write(msg)
                    return
            except Exception:
                pass
            # NapCat 每次换码只更新日志里的 URL，qrcode.png 可能还是旧的，
            # 所以这里先取"最新 URL"，用外部服务渲染（比旧图可靠）
            # 优先用 NapCat 本地生成的 qrcode.png（新鲜就直发，完全不依赖外网）
            try:
                import os as _os
                import time as _t
                _age = _t.time() - _os.path.getmtime(QR_PATH)
                if _age < 150:
                    with open(QR_PATH, "rb") as f:
                        _png = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(_png)))
                    self.end_headers()
                    self.wfile.write(_png)
                    return
            except Exception:
                pass
            _newest = _newest_qr_url()
            if _newest:
                import urllib.parse as _up
                target = ("https://api.qrserver.com/v1/create-qr-code/"
                          "?size=560x560&margin=8&data=" + _up.quote(_newest, safe=""))
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            try:
                with open(QR_PATH, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                msg = b"no qrcode yet (napcat not started / already logged in)"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            return
        if path == "/api/config":
            import json as _j
            cfg = _cfg_read()
            self._json({"base_url": cfg.get("base_url", ""), "model": cfg.get("model", ""),
                        "key_set": bool(cfg.get("api_key")),
                        "key_hint": _mask(cfg.get("api_key", "")),
                        "max_steps": cfg.get("max_steps", ""),
                        "max_tokens": cfg.get("max_tokens", "")})
            return

        if path == "/api/version":
            self._json(_update_info())
            return

        if path == "/api/backups":
            if not self._guard_dangerous():
                return
            self._json({"backups": _list_backups(), "local": VERSION})
            return

        if path == "/api/persona":
            cfg = _cfg_read()
            self._json({"persona": str(cfg.get("persona") or ""),
                        "default": DEFAULT_PERSONA})
            return

        if path == "/api/settings":
            cfg = _cfg_read()
            self._json({
                "r18_prefetch": bool(cfg.get("r18_prefetch")),
                "rotate_enabled": bool(cfg.get("rotate_enabled", True)),
                "rotate_hours": int(cfg.get("rotate_hours") or 24),
                "rotate_count": int(cfg.get("rotate_count") or 40),
            })
            return

        if path == "/api/model":
            self._json(_model_status())
            return

        if path == "/api/gallery":
            self._json(_gallery_stats())
            return

        if path == "/api/log":
            if not self._guard_dangerous():
                return
            _q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            n = 60
            try:
                n = max(10, min(400, int((_q.get("lines") or ["60"])[0])))
            except Exception:
                pass
            self._json({"lines": _tail("/data/data/com.termux/files/home/aibot/qq_bot.log", n)})
            return

        if path == "/api/control":
            if not self._authorized():
                self.send_response(401)
                self.end_headers()
                return
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            out = _act(params.get("action", [""])[0], params.get("value", [""])[0])
            data = out.encode("utf-8", "replace")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        # default: agent chat page
        self._html(PAGE.replace("__TOKEN__", TOKEN))

    # ---------- 流式聊天 ----------
    def _sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse(self, event, obj):
        try:
            payload = "event: %s\ndata: %s\n\n" % (
                event, json.dumps(obj, ensure_ascii=False))
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not (path == "/api" or path.startswith("/api/")):
            self.send_response(404)
            self.end_headers()
            return
        if not self._authorized():
            self.send_response(401)
            self.end_headers()
            return
        if path == "/api/config" and self.command == "POST":
            if not self._guard_dangerous():
                return
            import json as _j
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = _j.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception as e:
                self._json({"ok": False, "error": "解析失败: %s" % e})
                return
            cfg = _cfg_read()
            for k in ("base_url", "model", "api_key"):
                v = body.get(k)
                if isinstance(v, str) and v.strip():
                    cfg[k] = v.strip()
            for k in ("max_steps", "max_tokens"):
                v = body.get(k)
                if isinstance(v, int) and v > 0:
                    cfg[k] = v
            try:
                _cfg_write(cfg)
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
            return

        if path == "/api/feedback":
            if not self._guard_dangerous():
                return
            import json as _j
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = _j.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception as e:
                self._json({"ok": False, "error": "解析失败: %s" % e})
                return
            txt = str(body.get("text") or "").strip()
            if not txt:
                self._json({"ok": False, "error": "内容为空"})
                return
            self._json(_feedback_send(txt))
            return

        if path == "/api/persona":
            if not self._guard_dangerous():
                return
            import json as _j
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = _j.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception as e:
                self._json({"ok": False, "error": "解析失败: %s" % e})
                return
            text = str(body.get("persona") or "").strip()
            if len(text) > 4000:
                self._json({"ok": False, "error": "太长了（上限 4000 字）"})
                return
            cfg = _cfg_read()
            cfg["persona"] = text
            try:
                _cfg_write(cfg)
                try:
                    agent.reload_config()
                except Exception:
                    pass
                self._json({"ok": True, "persona": text})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
            return

        if path == "/api/settings":
            if not self._guard_dangerous():
                return
            import json as _j
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = _j.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception as e:
                self._json({"ok": False, "error": "解析失败: %s" % e})
                return
            cfg = _cfg_read()
            if "r18_prefetch" in body:
                cfg["r18_prefetch"] = bool(body["r18_prefetch"])
            if "rotate_enabled" in body:
                cfg["rotate_enabled"] = bool(body["rotate_enabled"])
            if "rotate_hours" in body:
                cfg["rotate_hours"] = max(1, int(body["rotate_hours"]))
            if "rotate_count" in body:
                cfg["rotate_count"] = max(0, int(body["rotate_count"]))
            try:
                _cfg_write(cfg)
                self._json({"ok": True, "r18_prefetch": bool(cfg.get("r18_prefetch"))})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
            return

        if path == "/api/console":
            if not self._guard_dangerous():
                return
            import json as _j
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = _j.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception as e:
                self._json({"ok": False, "error": "解析失败: %s" % e})
                return
            ok, msg, data = _console_action(str(body.get("action") or ""))
            self._json({"ok": ok, "msg": msg, "data": data})
            return

        n = int(self.headers.get("Content-Length", "0") or 0)
        msg = self.rfile.read(n).decode("utf-8", "replace").strip() if n else ""
        if not msg:
            self.send_response(400)
            self.end_headers()
            return

        if path == "/api/stream" and not self._guard_dangerous():
            return
        streaming = path == "/api/stream"
        chunks = []

        def on_text(piece):
            chunks.append(piece)
            if streaming:
                self._sse("text", {"t": piece})

        def on_tool(name, args):
            if streaming:
                brief = json.dumps(args, ensure_ascii=False)
                self._sse("tool", {"name": name, "args": brief[:160]})

        if streaming:
            self._sse_start()
            self._sse("start", {"mode": _mode()})
        try:
            out = agent.run_agent(msg, verbose=False, mode=_mode(),
                                  on_text=on_text, on_tool=on_tool)
        except Exception as e:
            out = "".join(chunks)
            if streaming:
                self._sse("err", {"e": str(e)[:300]})
            else:
                out = "(agent error: %s)" % e
        if streaming:
            self._sse("done", {"text": out, "chars": len(out or "")})
            return
        data = (out or "").encode("utf-8", "replace")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


PAGE = """<!doctype html><meta charset=utf-8><title>PhoneAgent</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;max-width:860px;margin:16px auto;padding:0 12px;background:#f5f5f5}
#log{white-space:pre-wrap;background:#111;color:#2f2;padding:12px;height:64vh;overflow:auto;border-radius:8px;font-size:14px;line-height:1.45}
#in{width:100%;padding:12px;font-size:16px;margin-top:8px;border-radius:8px;border:1px solid #ccc}
.hint{color:#666;font-size:13px;margin-top:6px}
</style>
<h2>PhoneAgent <a href="/panel" style="font-size:13px">控制台 &rarr;</a></h2>
<div id=log></div>
<input id=in placeholder="告诉 AI 你想做什么" autofocus>
<div class=hint>AI 会自己调用工具（root shell、文件、截图、安装、短信等）；回复是流式显示的</div>
<script>
const log=(t)=>{const el=document.getElementById('log');el.textContent+=t;el.scrollTop=el.scrollHeight;};
const logln=(t)=>{log(t+"\\n");};
async function send(m){
  logln('> '+m);
  let cur='';
  try{
    const r=await fetch('/api/stream?token=__TOKEN__',{method:'POST',body:m});
    if(!r.ok){logln('HTTP '+r.status);return;}
    const rd=r.body.getReader(), dec=new TextDecoder(); let acc='';
    for(;;){
      const {value,done}=await rd.read(); if(done)break;
      acc+=dec.decode(value,{stream:true});
      let i;
      while((i=acc.indexOf('\\n\\n'))>=0){
        const frame=acc.slice(0,i); acc=acc.slice(i+2);
        const ev=/^event: (.*)$/m.exec(frame), dt=/^data: (.*)$/m.exec(frame);
        if(!dt)continue;
        let o={}; try{o=JSON.parse(dt[1]);}catch(e){continue;}
        const k=ev?ev[1].trim():'text';
        if(k==='text'){cur+=o.t;log(o.t);}
        else if(k==='tool'){logln('');logln('  ⚙ '+o.name+' '+o.args);logln('');}
        else if(k==='err'){logln('');logln('  ⚠ '+o.e);}
      }
    }
    logln('');
  }catch(x){logln('ERR '+x);}
}
document.getElementById('in').onkeydown=async e=>{
  if(e.key!=='Enter')return;
  const m=e.target.value.trim(); if(!m)return; e.target.value='';
  await send(m);
};
logln('PhoneAgent ready.');
</script>"""

APP2 = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Botagent</title>
<style>

/* 去掉滑动时的白色边缘（回弹/光晕） */
html{background:var(--bg);height:100%;overscroll-behavior:none}
body{background:var(--bg);overscroll-behavior-y:none;-webkit-tap-highlight-color:transparent}
#splash{background:var(--bg) !important}
:root{--bg:#0d1117;--card:#161b22;--line:#26303d;--fg:#e6edf3;--dim:#8b949e;
      --acc:#2ea043;--blue:#1f6feb;--warn:#d29922;--err:#f85149;
      --hdr:rgba(13,17,23,.97);--nav:rgba(16,22,29,.99);--input:#070a0e;--log:#050809}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--fg);transition:background .25s,color .25s;font:15px/1.5 system-ui,-apple-system,"PingFang SC",sans-serif}

/* 启动页 */
#splash{position:fixed;inset:0;z-index:100;background:#0d1117;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:26px;transition:opacity .45s}
#splash.hide{opacity:0;pointer-events:none}
#splash img{width:210px;height:210px;border-radius:22px;object-fit:cover;
  box-shadow:0 10px 40px rgba(31,111,235,.28);animation:spfloat 2.6s ease-in-out infinite}
@keyframes spfloat{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-9px) scale(1.035)}}
#splash .sptitle{font-size:19px;color:#c9d1d9;letter-spacing:.5px}
#splash .sptitle b{color:#58a6ff;font-weight:600}

/* 顶栏 */
header{position:sticky;top:0;z-index:20;background:var(--hdr);border-bottom:1px solid var(--line);
  padding-top:11px;padding-right:14px;padding-bottom:11px;padding-left:14px;display:flex;align-items:center;gap:10px;backdrop-filter:blur(8px)}
.dot{width:9px;height:9px;border-radius:50%;background:#555;flex:0 0 auto}
.dot.on{background:var(--acc);box-shadow:0 0 8px var(--acc)}
.dot.off{background:var(--err)}
h1{font-size:16px;margin:0;font-weight:600;flex:1}
.mini{font-size:12px;color:var(--dim)}

/* 页签 */
.tab{display:none;padding-bottom:150px}
.tab.active{display:block}
#t-chat{padding-bottom:0}

/* 卡片 */
section.pad{padding:14px 14px calc(160px + env(safe-area-inset-bottom))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding-top:14px;padding-right:14px;padding-bottom:14px;padding-left:14px;margin-bottom:12px}
.card h2{font-size:13px;margin:0 0 10px;color:var(--dim);font-weight:600;letter-spacing:.4px}
.row{display:flex;justify-content:space-between;gap:10px;padding-top:7px;padding-right:0;padding-bottom:7px;padding-left:0;border-bottom:1px dashed #1e2631;font-size:14px}
.row:last-child{border-bottom:0}
.row span:first-child{color:var(--dim)}
.row span:last-child{text-align:right;word-break:break-all}

/* 表单 */
label{display:block;font-size:13px;color:var(--dim);margin:10px 0 5px}
input,select{width:100%;background:var(--input);border:1px solid var(--line);color:var(--fg);
  border-radius:9px;padding-top:10px;padding-right:12px;padding-bottom:10px;padding-left:12px;font-size:14px;font-family:inherit}
input:focus{outline:0;border-color:var(--blue)}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
button{flex:1;min-width:96px;padding-top:11px;padding-right:14px;padding-bottom:11px;padding-left:14px;border-radius:10px;border:1px solid var(--line);
  background:var(--card);color:var(--fg);font-size:14px;font-weight:500;font-family:inherit}
button:active{transform:scale(.98)}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff}
button.blue{background:var(--blue);border-color:var(--blue);color:#fff}
button.danger{background:#3d1b1b;border-color:#5c2626;color:#ffb4b4}
button:disabled{opacity:.45}
pre{background:var(--log);border:1px solid var(--line);border-radius:10px;padding-top:10px;padding-right:10px;padding-bottom:10px;padding-left:10px;font-size:11px;
  line-height:1.45;max-height:38vh;overflow:auto;white-space:pre-wrap;word-break:break-all;margin:8px 0 0;color:var(--dim)}
.tag{display:inline-block;padding-top:2px;padding-right:8px;padding-bottom:2px;padding-left:8px;border-radius:999px;font-size:11px;border:1px solid var(--line);color:var(--dim)}
.tag.ok{color:#7ee787;border-color:#2ea04355;background:#0f2a17}
.tag.warn{color:#f2cc60;border-color:#d2992255;background:#2b2413}
.tag.err{color:#ffa198;border-color:#f8514955;background:#2d1416}
.themes{display:flex;gap:10px;margin:4px 0 2px}
.themes .th{display:flex;align-items:center;gap:8px;justify-content:center;padding-top:12px;padding-right:10px;padding-bottom:12px;padding-left:10px;
  font-size:14px;background:var(--card);color:var(--fg);border:1px solid var(--line)}
.themes .th i{width:22px;height:22px;border-radius:7px;border:1px solid var(--line);display:block}
.themes .th.on{border-color:var(--blue);box-shadow:0 0 0 2px rgba(31,111,235,.30)}

/* B站卡片 */
.card.bili{display:flex;flex-direction:column;align-items:center;gap:12px;padding-top:26px;padding-right:14px;padding-bottom:22px;padding-left:14px;
  background:transparent;border:0;box-shadow:none}
.card.bili .avatar{width:132px;height:132px;border-radius:50%;object-fit:cover;
  border:0;box-shadow:0 10px 30px rgba(251,114,153,.25)}
.card.bili .bbtn{padding-top:10px;padding-right:26px;padding-bottom:10px;padding-left:26px;border-radius:12px;background:#fb7299;color:#fff;
  font-size:14px;font-weight:600;text-decoration:none;
  box-shadow:0 4px 14px rgba(251,114,153,.30)}
.card.bili .bname{font-size:17px;font-weight:600;margin-top:2px}
.card.bili .buid{font-size:12px;color:var(--dim);word-break:break-all;text-align:center}

#splash .spalt{display:none;align-items:center;justify-content:center;
  width:210px;height:210px;border-radius:50%;font-size:92px;font-weight:700;color:#eafaff;
  background:radial-gradient(circle at 50% 40%,#3ca0be 0%,#0f2b3a 78%);
  box-shadow:0 10px 30px rgba(31,111,235,.25)}
.avatarbox{width:132px;height:132px;position:relative;display:flex;
  align-items:center;justify-content:center}
.avatarbox .avph{display:none;width:132px;height:132px;border-radius:50%;
  align-items:center;justify-content:center;font-size:56px;font-weight:700;color:#eafaff;
  background:radial-gradient(circle at 50% 40%,#3ca0be 0%,#0f2b3a 78%);
  box-shadow:0 10px 30px rgba(251,114,153,.20)}
.avatarbox.ph .avph{display:flex}

/* R18 确认弹窗 */
#r18modal{position:fixed;inset:0;z-index:90;background:rgba(0,0,0,.72);display:none;
  align-items:center;justify-content:center;padding:20px}
#r18modal.open{display:flex}
.r18box{background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:20px;max-width:420px;width:100%;max-height:86vh;overflow:auto}
.r18box h3{margin:0 0 12px;font-size:17px;color:#f85149}
.r18box .risk{font-size:13px;line-height:1.75;color:var(--fg)}
.r18box .risk b{color:#f85149}

#btn-refresh{flex:0 0 auto;background:none;border:1px solid var(--line);color:var(--fg);
  border-radius:8px;width:30px;height:30px;font-size:16px;line-height:1;
  margin-left:8px;padding:0;cursor:pointer}
#btn-refresh:active{background:var(--line)}
#btn-refresh.spin{animation:spin .7s linear infinite}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
img.qr{width:230px;height:230px;background:#fff;border-radius:10px;display:block;margin:10px auto}

/* 聊天 */
#chat{display:flex;flex-direction:column;min-height:calc(100vh - 46px)}
#msgs{flex:1;padding-top:14px;padding-right:12px;padding-bottom:8px;padding-left:12px;display:flex;flex-direction:column;gap:10px;overflow-y:auto}
.msg{max-width:86%;padding-top:10px;padding-right:13px;padding-bottom:10px;padding-left:13px;border-radius:14px;font-size:15px;line-height:1.55;
  white-space:pre-wrap;word-break:break-word;animation:fin .18s ease-out}
@keyframes fin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.msg.me{align-self:flex-end;background:var(--blue);color:#fff;border-bottom-right-radius:5px}
.msg.ai{align-self:flex-start;background:var(--card);border:1px solid var(--line);border-bottom-left-radius:5px}
.msg.sys{align-self:center;background:transparent;color:var(--dim);font-size:12px;padding:4px}
.tool{display:inline-block;margin:2px 6px 2px 0;padding-top:2px;padding-right:8px;padding-bottom:2px;padding-left:8px;border-radius:999px;font-size:11px;
  background:#13221a;color:#7ee787;border:1px solid #2ea04344}
.cursor::after{content:"▍";animation:blink 1s steps(1) infinite;color:var(--blue)}
@keyframes blink{50%{opacity:0}}
#composer{position:fixed;left:0;right:0;bottom:64px;padding-top:8px;padding-right:10px;padding-bottom:8px;padding-left:10px;background:var(--na;v);
  border-top:1px solid var(--line);display:flex;gap:8px;align-items:flex-end}
#inp{flex:1;resize:none;max-height:120px;min-height:44px;line-height:22px;padding-top:11px;padding-right:13px;padding-bottom:11px;padding-left:13px;border-radius:12px;
  background:var(--card);border:1px solid var(--line);color:var(--fg);font:15px/1.45 inherit}
#send{flex:0 0 auto;width:auto;min-width:74px;padding-top:11px;padding-right:16px;padding-bottom:11px;padding-left:16px;border-radius:12px;
  background:var(--acc);border:0;color:#fff;font-weight:600}
#send:disabled{background:var(--input);color:var(--dim)}


/* 反馈独立页 */
#personapage,#guidepage{position:fixed;inset:0;z-index:80;background:var(--bg);display:none;flex-direction:column;transform:translateX(100%);transition:transform .25s ease}
#personapage.open,#guidepage.open{display:flex;transform:translateX(0)}
#personapage textarea,#guidepage textarea{width:100%;box-sizing:border-box;min-height:200px;padding:12px;border-radius:10px;background:var(--input);border:1px solid var(--line);color:var(--fg);font-size:15px;line-height:1.6;font-family:inherit;resize:vertical}
#morepage{position:fixed;inset:0;z-index:80;background:var(--bg);display:none;
  flex-direction:column;transform:translateX(100%);transition:transform .25s ease}
#morepage.open{display:flex;transform:translateX(0)}
#fbpage{position:fixed;inset:0;z-index:80;background:var(--bg);display:none;
  flex-direction:column;transform:translateX(100%);transition:transform .25s ease}
#fbpage.open{display:flex;transform:translateX(0)}
.fbhead{display:flex;align-items:center;justify-content:space-between;padding-top:12px;padding-right:12px;padding-bottom:12px;padding-left:12px;
  border-bottom:1px solid var(--line);background:var(--hdr);position:sticky;top:0}
.fbhead b{font-size:16px;font-weight:600}
.fbhead .back{flex:0 0 auto;width:auto;min-width:64px;padding-top:8px;padding-right:12px;padding-bottom:8px;padding-left:12px;border-radius:9px;
  background:transparent;border:0;color:var(--fg);font-size:15px}
.fbbody{flex:1 1 auto;min-height:0;padding-top:16px;padding-right:14px;padding-bottom:16px;padding-left:14px;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;-webkit-overflow-scrolling:touch}
#fbpage textarea{width:100%;background:var(--input);border:1px solid var(--line);color:var(--fg);
  border-radius:12px;padding-top:13px;padding-right:13px;padding-bottom:13px;padding-left:13px;font:15px/1.55 inherit;resize:vertical;min-height:200px;margin-top:12px}
#fbpage textarea:focus{outline:0;border-color:var(--blue)}
nav{position:fixed;left:0;right:0;bottom:0;z-index:30;display:flex;background:var(--nav);
  border-top:1px solid var(--line);padding-top:6px;padding-right:4px;padding-bottom:calc(6px + env(safe-area-inset-bottom));padding-left:4px}
nav div{flex:1;text-align:center;padding-top:8px;padding-right:2px;padding-bottom:8px;padding-left:2px;font-size:12px;color:var(--dim);border-radius:9px;transition:.2s}
nav div.on{color:var(--fg);background:var(--input);border-radius:9px}
nav div b{display:block;font-size:17px;font-weight:400;margin-bottom:2px}
.toast{position:fixed;left:50%;bottom:150px;transform:translateX(-50%);background:var(--blue);color:#fff;
  padding-top:10px;padding-right:16px;padding-bottom:10px;padding-left:16px;border-radius:10px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:60}
.toast.on{opacity:1}
</style>
</head>
<body>

<div id="splash">
  <img src="/assets/welcome.gif" alt="" id="spimg"
       onerror="if(this.dataset.f){this.style.display='none';document.getElementById('spalt').style.display='flex'}else{this.dataset.f=1;this.src='/assets/bili_avatar.png'}">
  <div id="spalt" class="spalt">鱼</div>
  <div class="sptitle">欢迎使用 <b>Botagent</b></div>
</div>
<script>
(function(){
  var s0=document.getElementById('splash');
  function hideSplash(){
    var s=document.getElementById('splash');
    if(!s||s.dataset.gone) return;
    s.dataset.gone=1;
    s.classList.add('hide');
    setTimeout(function(){ if(s&&s.parentNode) s.remove(); },400);
  }
  /* 最快 0.55 秒消失；页面 ready 后立刻消失 */
  var t0=Date.now();
  setTimeout(hideSplash,550);
  if(document.readyState==='complete'){ setTimeout(hideSplash,1); }
  else { window.addEventListener('load', function(){
    var wait=Math.max(0, 550-(Date.now()-t0));
    setTimeout(hideSplash, wait);
  }); }
  setTimeout(hideSplash, 1200);   /* 兜底：最多 1.2 秒 */
})();
</script>

<header>
  <i class="dot" id="dot"></i>
  <h1>Botagent</h1>
  <span class="mini" id="hdr"></span>
  <button id="btn-refresh" onclick="refreshNow()" title="立即刷新状态" style="flex:0 0 auto;width:32px;height:32px;min-width:32px;padding:0;margin:0 2px 0 0;border-radius:50%;font-size:17px;line-height:1;background:transparent;color:var(--fg);border:1px solid var(--line)">⟳</button>
</header>

<!-- 对话 -->
<section id="t-chat" class="tab active">
  <div id="chat">
    <div id="msgs">
      <div class="msg sys">和手机上的机器人对话（跟 QQ 里是同一套能力）</div>
    </div>
  </div>
  <div id="composer">
    <textarea id="inp" rows="1" placeholder="发指令…"></textarea>
    <button id="send" onclick="sendMsg()">发送</button>
  </div>
</section>

<!-- 状态 -->
<section id="t-status" class="tab pad">
  <div class="card">
    <h2>运行状态</h2>
    <div class="row"><span>QQ</span><span id="s-qq">—</span></div>
    <div class="row"><span>端口</span><span id="s-ports">—</span></div>
    <div class="row"><span>bot / proot</span><span id="s-proc">—</span></div>
    <div class="row"><span>模式</span><span id="s-mode">—</span></div>
    <div class="row"><span>可用内存</span><span id="s-mem">—</span></div>
    <div class="row"><span>最后刷新</span><span id="s-ts">—</span></div>
  </div>
  <div class="card">
    <h2>图库</h2>
    <div class="row"><span>r18</span><span id="s-r18">—</span></div>
    <div class="row"><span>safe</span><span id="s-safe">—</span></div>
  </div>
  <div class="btns"><button onclick="refreshNow()">刷新</button></div>
</section>

<!-- 模型 -->
<section id="t-model" class="tab pad">
  <div class="card">
    <h2>模型状态</h2>
    <div class="row"><span>服务商</span><span id="m-prov">—</span></div>
    <div class="row"><span>模型</span><span id="m-model">—</span></div>
    <div class="row"><span>Key</span><span id="m-key">—</span></div>
    <div class="row"><span>最近延迟</span><span id="m-lat">—</span></div>
    <div class="row"><span>最近错误</span><span id="m-err">—</span></div>
    <div class="row"><span>冷却</span><span id="m-cool">—</span></div>
  </div>
  <div class="card">
    <h2>接入配置</h2>
    <div class="mini" style="margin-bottom:6px">兼容所有 OpenAI 格式的接口（DeepSeek / OpenAI / 通义 / 本地 Ollama…）</div>
    <div class="btns" style="margin:0 0 6px 0">
      <button onclick="preset('deepseek')">DeepSeek</button>
      <button onclick="preset('openai')">OpenAI</button>
      <button onclick="preset('qwen')">通义</button>
      <button onclick="preset('ollama')">本地</button>
    </div>
    <label>API 地址</label><input id="c-url" placeholder="https://api.deepseek.com 或 https://api.openai.com/v1">
    <label>模型名</label><input id="c-model" placeholder="deepseek-chat">
    <label>API Key</label><input id="c-key" type="password" placeholder="sk-...（留空则不修改）" autocomplete="off">
    <label>最大步数</label><input id="c-steps" type="number" min="1" max="30">
    <label>单次最大 token</label><input id="c-tokens" type="number" min="128" max="8000">
    <div class="btns">
      <button class="primary" onclick="saveCfg()">保存配置</button>
      <button onclick="toggleKey()">显示/隐藏</button>
    </div>
    <div class="mini" style="margin-top:10px">保存后点「重载配置」生效</div>
  </div>
</section>

<!-- 控制台 -->
<section id="t-console" class="tab pad">
  <div class="card">
    <h2>操作</h2>
    <div class="btns">
      <button onclick="act('restart_bot')">重启 Bot</button>
      <button class="danger" onclick="act('qr_restart')">重新生成二维码</button>
      <button onclick="act('restart_napcat')">重启 NapCat</button>
      <button onclick="act('prefetch')">抓一批图</button>
    </div>
    <div class="btns">
      <button onclick="act('clean')">清理缓存</button>
      <button onclick="act('stats')">看详细状态</button>
      <button class="danger" onclick="act('reboot_bot')">重载配置</button>
    </div>
  </div>
  <div class="card">
    <h2>扫码登录</h2>
    <div class="mini" id="qrstat">—</div>
    <img class="qr" id="qrimg" alt="QR" style="width:200px;height:200px">
    <div class="btns"><button onclick="loadQR(true)">刷新二维码</button></div>
  </div>
  <div class="card">
    <h2>日志</h2>
    <div class="btns"><button onclick="loadLog()">刷新日志</button></div>
    <pre id="log">点击刷新读取…</pre>
  </div>
</section>

<!-- 设置 -->
<section id="t-settings" class="tab pad">
  <div class="card bili">
    <div class="avatarbox">
      <img class="avatar" src="/assets/bili_avatar.png" alt=""
           onerror="this.style.display='none';this.parentNode.classList.add('ph')">
      <span class="avph">鱼</span>
    </div>
    <a class="bbtn" href="__BILI_URL__" target="_blank">看主页 →</a>
    <b class="bname">Botagent</b>
  </div>

  <div class="card">
    <h2>主题背景色</h2>
    <div class="themes" id="themes">
      <button data-t="dark"  class="th on"><i style="background:#0d1117"></i>深色</button>
      <button data-t="light" class="th"><i style="background:#f5f7fa"></i>浅色</button>
      <button data-t="cyan"  class="th"><i style="background:#07212a"></i>青色</button>
    </div>
    <div class="mini" style="margin-top:8px">选择后立即生效，下次打开仍是这个主题</div>
  </div>
  <div class="card">
    <h2>人设</h2>
    <div class="mini">决定机器人的性格、说话方式。改完下一句对话就生效。</div>
    <div class="btns"><button onclick="openPersona()">编辑人设 →</button></div>
  </div>

  <div class="card">
    <h2>使用说明</h2>
    <div class="mini">第一次用先看这个：怎么登录、怎么换模型、怎么发图</div>
    <div class="btns"><button onclick="openGuide()">打开使用说明 →</button></div>
  </div>

  <div class="card">
    <h2>更多设置</h2>
    <div class="mini">抓图模式、抓取范围等高级选项</div>
    <div class="btns"><button onclick="openMore()">进入更多设置 →</button></div>
  </div>

  <div class="card">
    <h2>反馈</h2>
    <div class="mini">意见 / BUG 反馈请戳这，会直接发给我</div>
    <div class="btns"><button class="blue" onclick="openFb()">戳这里 →</button></div>
  </div>
</section>

<!-- 二维码 -->
<section id="t-qr" class="tab pad">
  <div class="card">
    <h2>扫码登录</h2>
    <div class="mini" id="qrstat">加载中…</div>
    <img class="qr" id="qrimg2" alt="">
    <div class="btns"><button onclick="loadQR(true)">立即刷新</button></div>
  </div>
</section>

<nav>
  <div class="on" data-t="chat"><b>◍</b>对话</div>
  <div data-t="status"><b>◉</b>状态</div>
  <div data-t="model"><b>⚙</b>模型</div>
  <div data-t="console"><b>▶</b>控制台</div>
  <div data-t="settings"><b>⚒</b>设置</div>
</nav>


<!-- 独立反馈页 -->
<div id="fbpage">
  <div class="fbhead">
    <button class="back" onclick="closeFb()">‹ 返回</button>
    <b>意见反馈</b>
    <span style="width:64px"></span>
  </div>
  <div class="fbbody">
    <div class="mini">内容会**直接发给我**，可以写问题、建议、想要的功能。<br>看到后会回复，谢谢你的反馈 🙏</div>
    <textarea id="fb" rows="9" placeholder="想说什么都可以…"></textarea>
    <div class="btns">
      <button class="blue" onclick="sendFeedback()">提交反馈</button>
    </div>
    <div class="mini" id="fbst" style="margin-top:10px"></div>
  </div>
</div>


<!-- R18 风险确认弹窗 -->
<div id="r18modal">
  <div class="r18box">
    <h3>⚠️ 开启深度抓图</h3>
    <div class="risk">
      开启后机器人会扩大抓取范围，从更多图源自动下载图片并保存到手机相册。
      <br><br>
      <b>该模式抓取的内容可能包含 R18 内容</b>，包括但不限于：
      <br>· 成人向写真 / 图集
      <br>· 成人向漫画
      <br><br>
      <b>风险提示：</b>
      <br>1. 这些内容仅限你本人设备使用，转发或传播可能违反法律法规
      <br>2. 图库会占用更多存储空间
      <br>3. 若手机被他人使用，相册里的内容会被看到
      <br>4. 部分图源需要代理才能访问
      <br><br>
      确认你已年满 18 周岁，并自行承担以上风险。
    </div>
    <div class="btns">
      <button class="danger" onclick="setR18(true)">我已了解，开启</button>
      <button onclick="closeR18()">取消</button>
    </div>
  </div>
</div>


<!-- 更多设置（独立页） -->
<div id="morepage">
  <div class="fbhead">
    <button class="back" onclick="closeMore()">‹ 返回</button>
    <b>更多设置</b>
    <span style="width:64px"></span>
  </div>
  <div class="fbbody">
    <div class="card" style="margin:0 0 12px">
      <h2>抓图模式</h2>
      <div class="row"><span>深度抓图</span><span id="s-r18sw">—</span></div>
      <div class="mini" style="margin-top:10px">
        默认关闭，只抓普通图源。开启后会扩大抓取范围，可能包含 R18 内容。
      </div>
      <div class="btns">
        <button id="btn-r18" onclick="askR18()">开启深度抓图</button>
      </div>
      <div class="mini" id="morehint" style="margin-top:10px"></div>
    </div>
    <div class="card" style="margin:0 0 12px">
      <h2>图库自动换新</h2>
      <div class="row"><span>每 24 小时换一批</span><span id="s-rotsw">—</span></div>
      <div class="mini" style="margin-top:8px">
        到点后自动删掉最旧的一批图，再抓新的补上，图库不会一直满仓。
      </div>
      <div class="row"><span>上次换新</span><span id="rot-last">—</span></div>
      <div class="row"><span>累计换掉</span><span id="rot-total">—</span></div>
      <div class="btns">
        <button id="btn-rot" onclick="toggleRotate()">关闭自动换新</button>
        <button class="danger" onclick="rotateNow()">立即换新</button>
      </div>
    </div>

    <div class="card" style="margin:0 0 12px">
      <h2>备份与恢复</h2>
      <div class="mini">把配置、图库索引、反馈记录打包到手机「下载」目录。</div>
      <div class="btns">
        <button onclick="doBackup()">立即备份</button>
        <button class="danger" onclick="doRestore()">从最新备份恢复</button>
      </div>
      <div class="mini" id="bkinfo" style="margin-top:10px"></div>
    </div>

    <div class="card" style="margin:0 0 12px">
      <h2>关于</h2>
      <div class="row"><span>版本</span><span id="ver">—</span></div>
      <div class="row"><span>最新版本</span><span id="vernew">—</span></div>
      <div class="btns"><button onclick="checkUpdate()">检查更新</button></div>
    </div>

    <div class="card" style="margin:0">
      <h2>说明</h2>
      <div class="mini">
        · 关闭状态下只抓普通图源，占用更少空间<br>
        · 开启后抓取范围更大，图库增长更快<br>
        · 随时可以关闭，已下载的图片不会自动删除
      </div>
    </div>
  </div>
</div>


<!-- 人设编辑（独立页） -->
<div id="personapage">
  <div class="fbhead">
    <button class="back" onclick="closePersona()">‹ 返回</button>
    <b>人设</b>
    <span style="width:64px"></span>
  </div>
  <div class="fbbody">
    <div class="card" style="margin:0 0 12px">
      <h2>机器人的人设</h2>
      <div class="mini">写它叫什么、什么性格、怎么说话。留空就用默认风格。</div>
      <textarea id="personaText" placeholder="例如：你叫「蓝色大肥鱼」，自称本鱼，说话像朋友，一次最多一个 emoji"></textarea>
      <div class="mini" id="personaHint" style="margin-top:8px"></div>
      <div class="btns">
        <button onclick="savePersona()">保存</button>
        <button class="danger" onclick="fillDefaultPersona()">填入示例</button>
      </div>
      <div class="btns">
        <button class="danger" onclick="clearPersona()">清空（用默认风格）</button>
      </div>
    </div>
    <div class="card" style="margin:0">
      <h2>写法建议</h2>
      <div class="mini">
        · 先说身份：你是谁、叫什么<br>
        · 再说性格：冷淡/热情/毒舌/温柔<br>
        · 再说说话习惯：句子长短、用不用 emoji、怎么称呼对方<br>
        · 最后写禁忌：不要做什么<br><br>
        例：<br>
        「你叫阿七，是主人的助手。说话简短、直接，不用敬语。
        偶尔吐槽但不刻薄。称呼对方为『你』。不要写长篇大论。」
      </div>
    </div>
  </div>
</div>

<!-- 使用说明（首次启动弹窗 + 设置里可再打开） -->
<div id="guidepage">
  <div class="fbhead">
    <button class="back" onclick="closeGuide()">‹ 关闭</button>
    <b>使用说明</b>
    <span style="width:64px"></span>
  </div>
  <div class="fbbody">
    <div class="card" style="margin:0 0 12px">
      <h2>第一次用</h2>
      <div class="mini">
        1. 手机打开这个 App，就是控制台<br>
        2. 点下面「控制台」→ 看「扫码登录」，用要当机器人的 QQ 扫<br>
        3. 扫完状态变「在线」，就可以在 QQ 里跟它说话了
      </div>
    </div>
    <div class="card" style="margin:0 0 12px">
      <h2>怎么跟它说话（触发方式）</h2>
      <div class="mini">
        <b>私聊</b> —— 直接发消息就行，但它只理「主人」和白名单里的人，陌生人发什么都不回。<br><br>
        <b>群聊</b> —— 必须 <b>@它</b> 才会说话，普通聊天它不插嘴；而且只在你配置过的群里生效。<br><br>
        <b>关注的人</b> —— 在指定群里，你标记的那几个人说话它会自动接（有 10~15 秒冷却，避免刷屏）。<br><br>
        <b>夜间免打扰</b> —— 默认 03:00–07:00 只有主人能用，其他人会被礼貌拒绝。
      </div>
    </div>

    <div class="card" style="margin:0 0 12px">
      <h2>怎么让它发图</h2>
      <div class="mini">
        在消息里带上这些词就会触发找图：<br>
        「来张图」「来点图」「发图」「搜图」「整本」「打包」「预览」「色图」「涩图」「本子」「图片」「一张图」「cos图」「插画」<br><br>
        例子：<br>
        · @它 来张 cos 图<br>
        · @它 帮我搜 二次元 插画<br>
        · @它 随机整本<br><br>
        <b>访客有冷却</b>：非主人每 10~15 秒才能要一次图，主人不受限。<br>
        <b>来源</b>：优先用手机里预抓的图库；没有合适的才去网上搜。<br>
        <b>成人图源</b>：需要主人单独授权，默认关闭。
      </div>
    </div>

    <div class="card" style="margin:0 0 12px">
      <h2>谁能用（主人 / 访客）</h2>
      <div class="mini">
        <b>主人</b>（你在安装时填的那个 QQ 号）<br>
        · 全功能：聊天、发图不限制、能执行命令、装 App、改配置<br>
        · 夜间也能用<br>
        · 可以给别人发权限：私聊发「看权限」查看名单，发「给 123456 r18 权限」/「收回 123456 r18」增减<br><br>
        <b>访客</b>（白名单私聊 / 群里 @它）<br>
        · 纯聊天 + 安全图<br>
        · 要图有冷却（10~15 秒一次）<br>
        · 不能执行命令、不能改配置、看不到日志<br>
        · 夜间不可用<br><br>
        <b>不在名单里的人</b>：私聊不回，群里 @ 也不回（除非在那个群的白名单里）。
      </div>
    </div>

    <div class="card" style="margin:0 0 12px">
      <h2>五个页签</h2>
      <div class="mini">
        <b>对话</b> —— 直接在手机上跟它聊，跟 QQ 里是同一套能力<br>
        <b>状态</b> —— QQ 在线状态、端口、图库数量，每 2 秒自动刷新<br>
        <b>模型</b> —— 填 API Key、换服务商（DeepSeek / OpenAI / 通义 / 本地）<br>
        <b>控制台</b> —— 重启、二维码、抓图、日志<br>
        <b>设置</b> —— 主题、人设、反馈、更多设置
      </div>
    </div>
    <div class="card" style="margin:0 0 12px">
      <h2>换模型 / 填 Key</h2>
      <div class="mini">
        进「模型」页 → 点一个服务商预设 → 填 API Key → 保存<br>
        支持任何 OpenAI 兼容接口，也可以填本地 Ollama 地址。
      </div>
    </div>
    <div class="card" style="margin:0 0 12px">
      <h2>让人设像你想的样子</h2>
      <div class="mini">
        设置 → 人设 → 写它的名字、性格、说话方式 → 保存。<br>
        下一句对话就按新人格回复，不用重启。
      </div>
    </div>
    <div class="card" style="margin:0 0 12px">
      <h2>图库</h2>
      <div class="mini">
        默认只抓普通图源。「深度抓图」可能包含 R18 内容，需要手动开启并确认风险。<br>
        图库每 24 小时自动换一批（删最旧的、抓新的），可在更多设置里调整。
      </div>
    </div>
    <div class="card" style="margin:0">
      <h2>出问题怎么办</h2>
      <div class="mini">
        · 显示离线 → 控制台点「重新生成二维码」再扫<br>
        · 提示需要验证 → 去 NapCat 后台完成短信验证<br>
        · 消息不回 → 看控制台日志尾部，一般是 Key 或网络问题<br>
        · 实在不行 → 设置 → 反馈，写给我
      </div>
      <div class="btns"><button onclick="closeGuide()">知道了</button></div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const T="__TOKEN__";
const $=id=>document.getElementById(id);
function toast(m){const t=$("toast");t.textContent=m;t.classList.add("on");setTimeout(()=>t.classList.remove("on"),1800)}

document.querySelectorAll("nav div").forEach(d=>{
  d.onclick=()=>{
    document.querySelectorAll("nav div").forEach(x=>x.classList.remove("on"));
    document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
    d.classList.add("on");
    $("t-"+d.dataset.t).classList.add("active");
    if(d.dataset.t==="status") loadStatus();
    if(d.dataset.t==="model") loadModel();
    if(d.dataset.t==="console"){ loadLog(); loadQR(); }
    if(d.dataset.t==="settings"){ loadSettings(); }
    /* 切页签回到顶部，避免停留在上一个页签的滚动位置 */
    try{ window.scrollTo(0,0); }catch(e){}
    document.querySelectorAll(".tab").forEach(function(sec){
      try{ sec.scrollTop = 0; }catch(e){}
    });
  };
});

async function jget(u){const r=await fetch(u+(u.includes("?")?"&":"?")+"token="+T,{cache:"no-store"});return r.json()}
async function jpost(u,b){const r=await fetch(u+"?token="+T,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b||{})});return r.json()}

/* ---------------- 聊天 ---------------- */
let busy=false;
function addMsg(role, text){
  const d=document.createElement("div");
  d.className="msg "+role;
  d.textContent=text||"";
  $("msgs").appendChild(d);
  $("msgs").scrollTop=$("msgs").scrollHeight;
  return d;
}
function addTool(name){
  const d=document.createElement("div");
  d.className="msg sys";
  d.innerHTML='<span class="tool">🔧 '+name+'</span>';
  $("msgs").appendChild(d);
  $("msgs").scrollTop=$("msgs").scrollHeight;
}
async function sendMsg(){
  const inp=$("inp");
  const t=inp.value.trim();
  if(!t||busy) return;
  inp.value=""; inp.style.height="44px";
  addMsg("me", t);
  const bubble=addMsg("ai","");
  bubble.classList.add("cursor");
  busy=true; $("send").disabled=true;
  let acc="", buf="";
  try{
    const r=await fetch("/api/stream?token="+T,{method:"POST",body:t});
    if(!r.ok || !r.body) throw new Error("HTTP "+r.status);
    const reader=r.body.getReader();
    const dec=new TextDecoder();
    while(true){
      const {value,done}=await reader.read();
      if(done) break;
      buf+=dec.decode(value,{stream:true});
      let idx;
      while((idx=buf.indexOf("\n\n"))>=0){
        const raw=buf.slice(0,idx); buf=buf.slice(idx+2);
        let ev="message", data="";
        raw.split("\n").forEach(line=>{
          if(line.startsWith("event: ")) ev=line.slice(7).trim();
          else if(line.startsWith("data: ")) data+=line.slice(6);
        });
        if(!data) continue;
        let obj={}; try{obj=JSON.parse(data)}catch(e){}
        if(ev==="text" && obj.t){ acc+=obj.t; bubble.textContent=acc;
          $("msgs").scrollTop=$("msgs").scrollHeight; }
        else if(ev==="tool" && obj.name){ addTool(obj.name); }
        else if(ev==="err"){ addMsg("sys","出错："+(obj.e||"")); }
        else if(ev==="done" && obj.text && !acc){ acc=obj.text; bubble.textContent=acc; }
      }
    }
    if(!acc) bubble.textContent="（没有返回内容）";
  }catch(e){
    bubble.textContent="连接失败："+e.message;
  }finally{
    bubble.classList.remove("cursor");
    busy=false; $("send").disabled=false;
    $("msgs").scrollTop=$("msgs").scrollHeight;
  }
}
$("inp").addEventListener("keydown",e=>{
  if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); sendMsg(); }
});
$("inp").addEventListener("input",e=>{
  const el=e.target; el.style.height="44px"; el.style.height=Math.min(el.scrollHeight,120)+"px";
});

/* ---------------- 状态 ---------------- */
let _gal = {ts:0};

/* 顶部状态：每 2 秒刷一次，不管在哪个页签都更新 */
async function pollQQ(){
  if(document.hidden) return;
  try{
    const d=await jget("/api/qq");
    const on=d.online===true;
    $("dot").className="dot "+(on?"on":"off");
    $("hdr").textContent=on?"在线":"离线";
    $("hdr").style.color=on?"#3fb950":"#f85149";
    if($("t-status").classList.contains("active")) fillStatus(d);
    else window._lastQQ = d;
  }catch(e){
    $("dot").className="dot off";
    $("hdr").textContent="连接失败";
    $("hdr").style.color="#f85149";
  }
}


/* 手动刷新：在线状态 + 图库，立即生效 */
async function refreshNow(){
  const b = document.getElementById("btn-refresh");
  if(b) b.classList.add("spin");
  try{
    _gal.ts = 0;
    await pollQQ();
    await loadGallery();
    if($("t-status") && $("t-status").classList.contains("active")) fillStatus(window._lastQQ);
    toast("已刷新");
  }catch(e){
    toast("刷新失败");
  }finally{
    setTimeout(function(){ if(b) b.classList.remove("spin"); }, 500);
  }
}

function fillStatus(d){
  if(!d) return;
  const on=d.online===true;
  const PHASE = {
    "": "",
    waiting_qrcode: "等待扫码",
    generating_qrcode: "生成二维码中",
    qrcode_scanned: "已扫码，初始化中",
    initializing: "初始化中",
    offline: "离线",
    reconnecting: "重连中",
    captcha: "需要短信验证（去 NapCat 后台）",
    verification: "需要安全验证（去 NapCat 后台）",
    new_device: "新设备验证（去 NapCat 后台）"
  };
  let txt = on ? "已登录" : "未登录";
  const ph = PHASE[d.nap_phase] || "";
  if(!on && ph) txt = ph;
  $("s-qq").textContent = txt;
  $("s-qq").style.color = on ? "#3fb950" : (d.nap_state === "verify" ? "#d29922" : "#f85149");
  $("s-ports").textContent=(d.ports||[]).join(" / ")||"无";
  $("s-proc").textContent=(d.bot??"?")+" / "+(d.proot??"?");
  $("s-mode").textContent=(d.mode||"—").toUpperCase();
  const t=document.getElementById("s-ts");
  if(t) t.textContent=new Date().toLocaleTimeString("zh-CN",{hour12:false});
}

/* 图库数字不用刷太勤 */
async function loadGallery(){
  if(document.hidden) return;
  if(Date.now()-_gal.ts < 10000) return;
  _gal.ts=Date.now();
  try{
    const m=await jget("/api/gallery");
    $("s-r18").textContent="cos "+(m.cos??0)+" · set "+(m.set??0)+" · manga "+(m.manga??0)+"（共 "+(m.total??0)+"）";
    $("s-safe").textContent=(m.safe??0)+" 张";
    $("s-mem").textContent=(m.mem_mb??"?")+" MB 可用";
  }catch(e){}
}

async function loadStatus(){
  await pollQQ();
  fillStatus(window._lastQQ);
  await loadGallery();
}

/* ---------------- 模型 ---------------- */
async function loadModel(){
  try{
    const d=await jget("/api/model");
    $("m-prov").textContent=d.provider||"—";
    $("m-model").textContent=d.model||"—";
    $("m-key").innerHTML=d.key_set?('<span class="tag ok">已配置 '+d.key_hint+'</span>'):'<span class="tag err">未配置</span>';
    $("m-lat").textContent=d.last_latency?d.last_latency+" s":'—';
    $("m-err").innerHTML=d.last_error?('<span class="tag err">'+String(d.last_error).slice(0,60)+'</span>'):'<span class="tag ok">无</span>';
    $("m-cool").innerHTML=d.cooldown>0?('<span class="tag warn">冷却 '+d.cooldown+'s</span>'):'<span class="tag ok">正常</span>';
    if(!$("c-url").value) $("c-url").value=d.base_url||"";
    if(!$("c-model").value) $("c-model").value=d.model||"";
    if(!$("c-steps").value) $("c-steps").value=d.max_steps||"";
    if(!$("c-tokens").value) $("c-tokens").value=d.max_tokens||"";
  }catch(e){}
}
const PRESETS={
  deepseek:{url:"https://api.deepseek.com",model:"deepseek-chat"},
  openai:{url:"https://api.openai.com/v1",model:"gpt-4o-mini"},
  qwen:{url:"https://dashscope.aliyuncs.com/compatible-mode/v1",model:"qwen-plus"},
  ollama:{url:"http://127.0.0.1:11434/v1",model:"qwen2.5:7b"}
};
function preset(k){
  const p=PRESETS[k]; if(!p) return;
  $("c-url").value=p.url; $("c-model").value=p.model;
  toast("已填入"+k+"的地址，记得保存");
}
function toggleKey(){const k=$("c-key");k.type=k.type==="password"?"text":"password"}
async function saveCfg(){
  const body={base_url:$("c-url").value.trim(),model:$("c-model").value.trim(),
              max_steps:Number($("c-steps").value||0),max_tokens:Number($("c-tokens").value||0)};
  const k=$("c-key").value.trim(); if(k) body.api_key=k;
  const d=await jpost("/api/config",body);
  if(d.ok){toast("已保存");$("c-key").value="";loadModel()}else toast("保存失败："+(d.error||""))
}

/* ---------------- 控制台 ---------------- */
async function act(a){
  toast("执行中…");
  const d=await jpost("/api/console",{action:a});
  toast(d.ok?("完成："+(d.msg||a)):("失败："+(d.error||a)));
  if(a==="restart_bot"||a==="reboot_bot") setTimeout(loadStatus,3000);
  if(a==="stats") $("log").textContent=JSON.stringify(d.data,null,2);
}
async function loadLog(){
  try{
    const d=await jget("/api/log?lines=60");
    $("log").textContent=(d.lines||[]).join("\n")||"(空)";
  }catch(e){$("log").textContent="读取失败"}
}

/* ---------------- 二维码 ---------------- */
let qlast="";
async function loadQR(force){
  const hint=$("qrhint"), qimg=$("qrimg"), st=$("qrstat");
  try{
    const d=await jget("/api/qr_url");
    if(d.online){
      if(st) st.textContent="\u2705 已登录，无需扫码";
      if(hint) hint.textContent="QQ 已在线，不需要二维码";
      if(qimg){ qimg.removeAttribute("src"); qimg.style.display="none"; }
      return;
    }
    let msg="等 NapCat 出码…";
    if(d.nap_state==="verify") msg="QQ 要求短信/安全验证，请在 NapCat 后台完成，再点「重新生成二维码」";
    else if(d.nap_phase==="qrcode_scanned") msg="已扫码，正在初始化…";
    else if(!d.url) msg="还没生成二维码 —— 点「重新生成二维码」";
    if(hint) hint.textContent=msg;
    if(!d.url){ if(st) st.textContent=msg; if(qimg) qimg.style.display="none"; return; }
    if(force || d.url!==qlast){
      qlast=d.url;
      if(qimg){ qimg.style.display=""; qimg.src="/api/qr.png?token="+T+"&t="+Date.now(); }
    }
    const age=d.age>=0?d.age:0;
    if(st) st.textContent = age<90 ? ("有效（"+age+" 秒前生成）") : ("可能过期（"+age+" 秒），请点刷新");
  }catch(e){}
}


/* ---------------- R18 抓图开关 ---------------- */
async function loadSettings(){
  try{
    const d=await jget("/api/settings");
    const on=!!d.r18_prefetch;
    const sw=$("s-r18sw"), btn=$("btn-r18");
    if(sw){
      sw.innerHTML=on?'<span class="tag err">已开启</span>':'<span class="tag ok">已关闭</span>';
      const hint=document.getElementById("morehint");
      if(hint) hint.textContent = on ? "当前：深度抓图（可能包含 R18 内容）" : "当前：普通抓图";
    }
    if(btn){
      btn.textContent = on ? "关闭深度抓图" : "开启深度抓图";
      btn.className = on ? "danger" : "";
    }
  }catch(e){}
}

/* ---------------- 图库自动换新 ---------------- */
let _rotOn = true;
async function loadRotate(){
  try{
    const d = await jget("/api/settings");
    _rotOn = !!d.rotate_enabled;
    const sw = $("s-rotsw"), btn = $("btn-rot");
    if(sw) sw.innerHTML = _rotOn ? '<span class="tag ok">已开启</span>'
                                 : '<span class="tag err">已关闭</span>';
    if(btn){ btn.textContent = _rotOn ? "关闭自动换新" : "开启自动换新";
             btn.className = _rotOn ? "danger" : ""; }
    const q = await jget("/api/qq");
    const fmt = t => t ? new Date(t*1000).toLocaleString("zh-CN",{hour12:false}) : "还没换过";
    if($("rot-last")) $("rot-last").textContent = fmt(q.rotate_last);
    if($("rot-total")) $("rot-total").textContent = (q.rotate_total||0) + " 张";
  }catch(e){}
}
async function toggleRotate(){
  const d = await jpost("/api/settings", {rotate_enabled: !_rotOn});
  if(d.ok){ toast(_rotOn ? "已关闭自动换新" : "已开启自动换新"); loadRotate(); }
  else toast("保存失败");
}
async function rotateNow(){
  if(!confirm("现在就换一批？\n会删掉最旧的一批图，再抓新的补上")) return;
  toast("换新中，稍等…");
  const r = await jpost("/api/console", {action:"rotate"});
  toast(r.ok ? "已换新" : ("失败：" + (r.error||"")));
  loadRotate();
}


/* ---------------- 人设 ---------------- */
let _defPersona = "";
async function openPersona(){
  openOverlay("personapage");
  try{
    const d = await jget("/api/persona");
    _defPersona = d.default || "";
    $("personaText").value = d.persona || "";
    $("personaHint").textContent = d.persona ? "当前：自定义人设" : "当前：默认风格（没填）";
  }catch(e){}
}
function closePersona(){ closeOverlay("personapage"); }
function fillDefaultPersona(){ $("personaText").value = _defPersona; }
async function savePersona(){
  const t = ($("personaText").value || "").trim();
  const d = await jpost("/api/persona", {persona: t});
  if(d.ok){
    $("personaHint").textContent = t ? "已保存，下一句对话生效" : "已清空，回到默认风格";
    toast(t ? "人设已保存" : "已恢复默认风格");
  }else{ toast("保存失败：" + (d.error||"")); }
}
async function clearPersona(){
  if(!confirm("清空人设，回到默认风格？")) return;
  $("personaText").value = "";
  await savePersona();
}

/* ---------------- 使用说明（首次弹窗） ---------------- */
const GUIDE_KEY = "guide_seen_v1";
function openGuide(){ openOverlay("guidepage"); }
function closeGuide(){
  closeOverlay("guidepage");
  try{ localStorage.setItem(GUIDE_KEY, "1"); }catch(e){}
}
function maybeShowGuide(){
  let seen = null;
  try{ seen = localStorage.getItem(GUIDE_KEY); }catch(e){}
  if(!seen){ setTimeout(openGuide, 900); }
}

/* ---------------- 备份 / 恢复 / 更新 ---------------- */
async function doBackup(){
  const r = await jpost("/api/console", {action:"backup"});
  toast(r.ok ? ("已备份：" + (r.msg||"")) : ("备份失败：" + (r.error||"")));
  loadBackups();
}
async function doRestore(){
  if(!confirm("用最新备份覆盖当前配置？\n当前配置会另存一份 .bak")) return;
  const r = await jpost("/api/console", {action:"restore"});
  toast(r.ok ? ("已恢复：" + (r.msg||"")) : ("恢复失败：" + (r.error||"")));
}
async function loadBackups(){
  try{
    const d = await jget("/api/backups");
    const n = (d.backups||[]).length;
    const el = $("bkinfo");
    if(!el) return;
    if(!n){ el.textContent = "还没有备份"; return; }
    const b = d.backups[0];
    el.textContent = "已有 " + n + " 个备份，最新：" + b.name +
      "（" + Math.round(b.size/1024) + " KB）";
  }catch(e){}
}
async function checkUpdate(){
  try{
    const d = await jget("/api/version");
    $("ver").textContent = d.local || "—";
    $("vernew").textContent = d.remote ? d.remote : (d.url ? "读取失败" : "未配置更新地址");
    toast(d.has_update ? ("有新版本：" + d.remote) : "已是最新");
  }catch(e){ toast("检查失败"); }
}


/* 打开覆盖页时锁住底层页面滚动，避免「滑一下页面跟着跑」 */
function lockBody(on){
  try{
    if(on){ window._scrollY = window.scrollY || 0; document.body.style.overflow = "hidden"; }
    else { document.body.style.overflow = ""; window.scrollTo(0, window._scrollY || 0); }
  }catch(e){}
}
function openOverlay(id){
  var el = typeof id === "string" ? $(id) : id;
  if(el){ el.classList.add("open"); lockBody(true); }
  var body = el ? el.querySelector(".fbbody") : null;
  if(body) body.scrollTop = 0;
}
function closeOverlay(id){
  var el = typeof id === "string" ? $(id) : id;
  if(el){ el.classList.remove("open"); }
  lockBody(false);
}

function openMore(){
  openOverlay("morepage");
  loadSettings();
  loadBackups();
  loadRotate();
  jget("/api/version").then(function(d){
    if($("ver")) $("ver").textContent = d.local || "—";
    if($("vernew")) $("vernew").textContent = d.remote || (d.url ? "读取失败" : "—");
  }).catch(function(){});
}
function closeMore(){ closeOverlay("morepage"); }

function askR18(){
  const on = $("btn-r18") && $("btn-r18").className === "danger";
  if(on){ setR18(false); return; }        // 已开启 -> 直接关
  $("r18modal").classList.add("open");    // 未开启 -> 先弹风险
}
function closeR18(){ $("r18modal").classList.remove("open"); }
async function setR18(v){
  const d=await jpost("/api/settings",{r18_prefetch:!!v});
  closeR18();
  if(d.ok){
    toast(v ? "已开启深度抓图（可能含 R18 内容）" : "已关闭深度抓图");
    loadSettings();
  }else{
    toast("保存失败：" + (d.error||""));
  }
}

/* ---------------- 主题 / 反馈 ---------------- */
const THEMES={
  dark:{bg:"#0d1117",card:"#161b22",line:"#26303d",fg:"#e6edf3",dim:"#8b949e",
        hdr:"rgba(13,17,23,.97)",nav:"rgba(16,22,29,.99)",input:"#070a0e",log:"#050809"},
  light:{bg:"#f5f7fa",card:"#ffffff",line:"#dfe4ea",fg:"#1b2430",dim:"#6b7684",
        hdr:"rgba(245,247,250,.97)",nav:"rgba(255,255,255,.99)",input:"#e7ebf0",log:"#d9e0e8"},
  cyan:{bg:"#1b4f5d",card:"#25606f",line:"#3a7d90",fg:"#f2fdff",dim:"#c3e2e8",
        hdr:"rgba(27,79,93,.97)",nav:"rgba(31,88,103,.99)",input:"#154350",log:"#113b47"}
};
function applyTheme(name, quiet){
  const t=THEMES[name]; if(!t) return;
  const r=document.documentElement.style;
  r.setProperty("--bg",t.bg); r.setProperty("--card",t.card); r.setProperty("--line",t.line);
  r.setProperty("--fg",t.fg); r.setProperty("--dim",t.dim);
  r.setProperty("--hdr",t.hdr); r.setProperty("--nav",t.nav);
  r.setProperty("--input",t.input); r.setProperty("--log",t.log);
  document.body.style.background=t.bg; document.body.style.color=t.fg;
  localStorage.setItem("theme",name);
  document.querySelectorAll("#themes .th").forEach(b=>b.classList.toggle("on",b.dataset.t===name));
  if(!quiet) toast("已切换到"+({dark:"深色",light:"浅色",cyan:"青色"}[name])+"主题");
}
document.querySelectorAll("#themes .th").forEach(b=>{
  b.onclick=()=>applyTheme(b.dataset.t);
});
(function(){ applyTheme(localStorage.getItem("theme")||"dark", true); })();


/* 看主页：优先用 B 站 App 打开，没装再退回网页 */
function openBili(ev){
  var web = "__BILI_URL__";
  var m = web.match(/(\d{5,})/);
  var uid = m ? m[1] : "";
  if (window.Android && Android.openApp) {
    if (ev) ev.preventDefault();
    var appUrl = uid ? ("bilibili://space/" + uid) : "bilibili://";
    Android.openApp(appUrl, web);
    return false;
  }
  return true;   // 电脑浏览器里保持普通链接
}

function openFb(){
  openOverlay("fbpage"); $("fbst").textContent="";
  setTimeout(()=>$("fb").focus(),260);
}
function closeFb(){ $("fbpage").classList.remove("open"); }

async function sendFeedback(){
  const t=$("fb").value.trim();
  if(!t){ toast("先写点内容"); return; }
  $("fbst").textContent="提交中…";
  try{
    const d=await jpost("/api/feedback",{text:t});
    if(d.ok && d.sent){ $("fbst").innerHTML="✅ 已发给我了，谢谢你的反馈！<br><span class=\"mini\">问题会尽快看，可以点左上角返回</span>"; $("fb").value=""; }
    else if(d.ok){ $("fbst").innerHTML="⚠️ 已保存，稍后会自动发给我"+(d.error?("<br><span class=\"mini\">"+d.error+"</span>"):""); $("fb").value=""; }
    else { $("fbst").textContent="❌ "+(d.error||"失败"); }
  }catch(e){ $("fbst").textContent="❌ "+e.message; }
}

loadStatus();
loadSettings();
maybeShowGuide();
setInterval(pollQQ, 2000);
setInterval(loadGallery, 15000);
document.addEventListener("visibilitychange", ()=>{ if(!document.hidden) { pollQQ(); loadGallery(); } });
setInterval(()=>{if($("t-console").classList.contains("active"))loadQR()},4000);
</script>
</body>
</html>
"""

APP = """<!doctype html><html lang=zh><meta charset=utf-8>
<title>PhoneAgent</title>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name=theme-color content="#0d1117">
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%;margin:0;background:#0d1117;color:#e6edf3;
  font-family:system-ui,-apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif}
#wrap{display:flex;flex-direction:column;height:100%}
header{padding:12px 14px;background:#161b22;border-bottom:1px solid #21262d;
  display:flex;align-items:center;gap:10px;position:sticky;top:0;z-index:5}
#title{font-weight:700;font-size:16px}
#dot{width:9px;height:9px;border-radius:50%;background:#f85149;transition:.3s}
#dot.on{background:#3fb950;box-shadow:0 0 8px #3fb950}
#stat{margin-left:auto;font-size:12px;color:#8b949e;max-width:46%;text-align:right;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#chips{display:flex;gap:8px;overflow-x:auto;padding:10px 12px;background:#0d1117;
  border-bottom:1px solid #21262d;scrollbar-width:none}
#chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;padding:9px 14px;border-radius:999px;background:#21262d;color:#c9d1d9;
  font-size:13px;border:1px solid #30363d;user-select:none}
.chip:active{background:#30363d}
#chat{flex:1;overflow-y:auto;padding:12px 12px 4px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:88%;padding:10px 13px;border-radius:14px;font-size:14.5px;line-height:1.55;
  white-space:pre-wrap;word-break:break-word;animation:in .18s ease}
@keyframes in{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
.me{align-self:flex-end;background:#1f6feb;color:#fff;border-bottom-right-radius:4px}
.ai{align-self:flex-start;background:#161b22;border:1px solid #21262d;border-bottom-left-radius:4px}
.sys{align-self:center;background:transparent;color:#8b949e;font-size:12.5px;
  border:1px dashed #30363d;padding:8px 12px;border-radius:12px;max-width:94%;
  white-space:pre-wrap;text-align:left}
.tool{align-self:flex-start;color:#8b949e;font-size:12.5px;font-family:ui-monospace,monospace;
  background:#0f141b;border-left:2px solid #1f6feb;padding:6px 10px;border-radius:6px;
  max-width:92%;white-space:pre-wrap;word-break:break-all}
#bar{display:flex;gap:8px;padding:10px 12px;background:#161b22;border-top:1px solid #21262d;
  padding-bottom:calc(10px + env(safe-area-inset-bottom))}
#in{flex:1;resize:none;height:44px;max-height:120px;padding:11px 13px;border-radius:12px;
  border:1px solid #30363d;background:#0d1117;color:#e6edf3;font-size:15px;outline:none}
#in:focus{border-color:#1f6feb}
#send{width:64px;border:0;border-radius:12px;background:#238636;color:#fff;font-size:15px;font-weight:600}
#send:disabled{background:#30363d;color:#8b949e}
.spin{display:inline-block;width:12px;height:12px;border:2px solid #8b949e;
  border-top-color:#1f6feb;border-radius:50%;animation:sp .7s linear infinite;vertical-align:-1px}
@keyframes sp{to{transform:rotate(360deg)}}
</style>
<div id=wrap>
  <header>
    <span id=dot></span><span id=title>PhoneAgent</span>
    <span id=stat>连接中…</span>
  </header>
  <div id=chips>
    <div class=chip data-a=status>状态</div>
    <div class=chip data-a=shot>截图</div>
    <div class=chip data-a=qr>二维码</div>
    <div class=chip data-a=restart_bot>重启 Bot</div>
    <div class=chip data-a=restart_napcat>重启 NapCat</div>
    <div class=chip data-a=selinux>修 SELinux</div>
    <div class=chip data-a=mode_j>切 J 模式</div>
    <div class=chip data-a=mode_e>切 E 模式</div>
    <div class=chip data-a=mode_normal>正常</div>
    <div class=chip data-a=clear>清屏</div>
  </div>
  <div id=chat></div>
  <div id=bar>
    <textarea id=in placeholder="让 AI 做什么…" rows=1></textarea>
    <button id=send>发送</button>
  </div>
</div>
<script>
const T="__TOKEN__";
const chat=document.getElementById('chat'), send=document.getElementById('send'),
      inp=document.getElementById('in'), dot=document.getElementById('dot'),
      stat=document.getElementById('stat');
let busy=false;
function add(cls,text){const d=document.createElement('div');d.className='msg '+cls;
  d.textContent=text||'';chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;}
function sys(t){add('sys',t)}
function setOn(ok,txt){dot.className=ok?'on':'';stat.textContent=txt||''}
let lastPing=0;
async function ping(){
  const t0=Date.now();
  try{
    const r=await fetch('/api/control?token='+T+'&action=ping',{cache:'no-store'});
    if(r.ok){setOn(true,'已连接 · '+((Date.now()-t0))+'ms');return true}
  }catch(e){}
  setOn(false,'未连接（服务未启动？）');return false;
}
async function act(a){
  if(a==='clear'){chat.innerHTML='';sys('已清屏');return;}
  if(a==='qr'){showQR();return;}
  if(a==='mode_j'){await ctl('mode','j');return;}
  if(a==='mode_e'){await ctl('mode','e');return;}
  if(a==='mode_normal'){await ctl('mode','normal');return;}
  const d=add('sys','· '+a+' …');
  try{
    const r=await fetch('/api/control?token='+T+'&action='+a);
    d.textContent=await r.text();
  }catch(e){d.textContent='失败: '+e}
  chat.scrollTop=chat.scrollHeight;
}
async function ctl(action,val){
  try{await fetch('/api/control?token='+T+'&action='+action+'&value='+encodeURIComponent(val));
    sys('已切换到 '+val.toUpperCase()+' 模式')}catch(e){sys('切换失败: '+e)}
}

// QQ 掉登录时，直接把 NapCat 的登录二维码显示在聊天里（扫码即可，不用连电脑）
let qrTimer=null, qrLast='';
function showQR(force){
  let d=document.getElementById('qrbox');
  if(!d){
    d=document.createElement('div');
    d.id='qrbox'; d.className='msg tool';
    d.innerHTML='📷 拿要当机器人的那个 QQ 扫码（每 4 秒自动换最新码）<br>'+
      '<div class="mini" id="qrhint" style="margin:8px 0"></div>
<img id="qrimg" alt="QR" style="width:250px;height:250px;background:#fff;border-radius:8px;margin-top:6px;image-rendering:pixelated">'+
      '<div id="qrstat" style="margin-top:6px;color:#8b949e;font-size:12px">加载中…</div>'+
      '<button onclick="showQR(true)" style="margin-top:6px;padding:6px 12px;border-radius:8px;border:0;background:#2b7;color:#fff">立即刷新</button>';
    chat.appendChild(d);
  }
  if(qrTimer){ clearInterval(qrTimer); qrTimer=null; }
  const tick=async()=>{
    try{
      const r=await fetch('/api/qr_url?token='+T,{cache:'no-store'});
      const j=await r.json();
      const st=document.getElementById('qrstat');
      if(!st) return;
      if(j.online){ st.textContent='✅ 已登录，不用扫码了'; if(qrTimer){clearInterval(qrTimer);qrTimer=null;} return; }
      if(!j.url){ st.textContent='等 NapCat 出码…'; return; }
      if(force || j.url!==qrLast){
        qrLast=j.url;
        document.getElementById('qrimg').src =
          '/api/qr.png?token='+T+'&t='+Date.now();
        force=false;
      }
      const age=j.age>=0?j.age:0;
      st.textContent = age<90 ? ('有效（'+age+' 秒前生成）') : ('可能过期（'+age+' 秒），点下面刷新');
    }catch(e){}
  };
  tick();
  qrTimer=setInterval(tick,4000);
  chat.scrollTop=chat.scrollHeight;
  fetch('/api/control?token='+T+'&action=qr').catch(()=>{});
}
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>act(c.dataset.a));

// 流式渲染：event: text / tool / done / err
async function submit(){
  const t=inp.value.trim(); if(!t||busy)return;
  inp.value=''; inp.style.height='44px';
  add('me',t);
  busy=true; send.disabled=true;
  const bubble=add('ai','');
  bubble.innerHTML='<span class=spin></span> <span style="color:#8b949e">思考中</span>';
  const t0=Date.now();
  let acc='', firstAt=0, toolCount=0;
  const toolBox=document.createElement('div'); // 工具行插在气泡前面
  try{
    const r=await fetch('/api/stream?token='+T,{method:'POST',body:t});
    if(!r.ok){bubble.textContent='HTTP '+r.status;return;}
    const rd=r.body.getReader(), dec=new TextDecoder(); let buf='';
    for(;;){
      const {value,done}=await rd.read(); if(done)break;
      buf+=dec.decode(value,{stream:true});
      let i;
      while((i=buf.indexOf('\\n\\n'))>=0){
        const frame=buf.slice(0,i); buf=buf.slice(i+2);
        const ev=/^event: (.*)$/m.exec(frame), dt=/^data: (.*)$/m.exec(frame);
        if(!dt)continue;
        let o={}; try{o=JSON.parse(dt[1]);}catch(e){continue;}
        const k=ev?ev[1].trim():'text';
        if(k==='text'){
          if(!firstAt){firstAt=Date.now()-t0; bubble.textContent='';}
          acc+=o.t; bubble.textContent=acc;
        }else if(k==='tool'){
          toolCount++;
          const line=document.createElement('div');
          line.className='msg tool';
          line.textContent='⚙ '+o.name+(o.args&&o.args!=='{}'?'  '+o.args:'');
          chat.insertBefore(line,bubble);
          stat.textContent='工具 '+toolCount;
        }else if(k==='err'){
          const e=document.createElement('div'); e.className='msg tool';
          e.textContent='⚠ '+o.e; chat.insertBefore(e,bubble);
        }else if(k==='done'){
          if(!acc && o.text){bubble.textContent=o.text; acc=o.text; firstAt=firstAt||1;}
        }
        chat.scrollTop=chat.scrollHeight;
      }
    }
  }catch(e){
    bubble.textContent=(acc||'')+ (acc?'\\n':'') +'请求失败: '+e;
  }finally{
    busy=false; send.disabled=false;
    if(!acc && !bubble.textContent.trim()){bubble.textContent='(空回复)';}
    const dt=((Date.now()-t0)/1000).toFixed(1);
    stat.textContent='首字 '+(firstAt?firstAt+'ms':'-')+' · 共 '+dt+'s';
    chat.scrollTop=chat.scrollHeight;
  }
}
send.onclick=submit;
inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submit();}});
inp.addEventListener('input',()=>{inp.style.height='44px';inp.style.height=Math.min(120,inp.scrollHeight)+'px';});
ping(); setInterval(()=>{if(!busy)ping()},15000);
sys('PhoneAgent 就绪');
// 深链：/app?q=你好 打开就直接问（也方便自动化测试）
try{
  const q=new URLSearchParams(location.search).get('q');
  if(q){inp.value=q;setTimeout(submit,150);}
}catch(e){}
</script></html>"""


if __name__ == "__main__":
    # 单实例：端口占用就说明已有一个在跑，别再起第二个
    _pidf = "/data/data/com.termux/files/home/aibot/webui.pid"
    try:
        import os as _os
        if _os.path.exists(_pidf):
            try:
                _old = int((open(_pidf).read() or "0").strip())
            except Exception:
                _old = 0
            if _old and _old != _os.getpid():
                try:
                    _os.kill(_old, 0)
                    print("another webui already running (pid %d), exit" % _old, flush=True)
                    raise SystemExit(0)
                except OSError:
                    pass
        open(_pidf, "w").write(str(_os.getpid()))
    except SystemExit:
        raise
    except Exception:
        pass
    print("PhoneAgent WebUI on 0.0.0.0:%d  token=%s  (streaming)" % (PORT, TOKEN), flush=True)
    print("panel: http://127.0.0.1:%d/panel" % PORT, flush=True)
    srv = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()
