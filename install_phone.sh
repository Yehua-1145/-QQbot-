#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  Botagent 手机直装（不需要电脑）
#
#  在你的手机 Termux 里执行：
#    pkg install -y curl && bash -c "$(curl -sL https://cdn.jsdelivr.net/gh/Yehua-1145/-QQbot-@main/install_phone.sh)"
#
#  它会做的事：
#    1. 换国内源、装 python / curl / unzip
#    2. 下载 Botagent 程序
#    3. 问几个问题（QQ 号、API Key）写入配置
#    4. 生成 start.sh / stop.sh / status.sh
#    5. 启动控制台（8080）
#
#  QQ 那半边（协议端）需要 AstrBot App：它自带 Ubuntu + Linux QQ + NapCat
#  装好后把它的 WebSocket 端口设成 3001，本程序就能连上。
# ============================================================
set -u

APP_DIR="${HOME}/aibot"
REPO="Yehua-1145/-QQbot-"
VERSION="${BOTAGENT_VERSION:-v1.1}"
NO_START=0
LOCAL_ZIP=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) shift; APP_DIR="${1:-$APP_DIR}" ;;
    --no-start) NO_START=1 ;;
    --zip) shift; LOCAL_ZIP="${1:-}" ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "忽略未知参数：$1" ;;
  esac
  shift
done

C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_0=$'\033[0m'
say()  { printf "${C_OK}==>${C_0} %s\n" "$*"; }
warn() { printf "${C_WARN}[!]${C_0} %s\n" "$*"; }
die()  { printf "${C_ERR}[x]${C_0} %s\n" "$*" >&2; exit 1; }
dim()  { printf "${C_DIM}    %s${C_0}\n" "$*"; }

say "检查环境"
case "${PREFIX:-}" in
  *com.termux*) dim "Termux: ${PREFIX}" ;;
  *) die "请在 Termux 里运行本脚本（现在 PREFIX=${PREFIX:-空}）" ;;
esac
[ -d /sdcard ] || warn "读不到 /sdcard，可能没给存储权限（termux-setup-storage 可修复）"

# ---------- 1) 换源 + 装依赖 ----------
say "换国内镜像并安装依赖（python / curl / unzip）"
SRC="$PREFIX/etc/apt/sources.list"
[ -f "$SRC" ] && cp -f "$SRC" "$SRC.bak.$(date +%s)" 2>/dev/null
printf 'deb https://packages.termux.dev/apt/termux-main stable main\n' > "$SRC"

pkg update -y >/dev/null 2>&1 || warn "pkg update 有报错，继续"
pkg install -y python curl unzip >/dev/null 2>&1 || warn "依赖安装有报错，继续"
command -v python >/dev/null 2>&1 || die "python 没装上，请手动执行： pkg install python"

# ---------- 2) 下载程序 ----------
say "下载 Botagent 程序（$VERSION）"
# TMPDIR 兜底：有些环境（su / 非交互 shell）没设，mktemp 会失败
TMPDIR="${TMPDIR:-$PREFIX/tmp}"
mkdir -p "$TMPDIR" 2>/dev/null
TMPD="$(mktemp -d 2>/dev/null || true)"
if [ -z "${TMPD:-}" ] || [ ! -d "$TMPD" ]; then
  TMPD="$HOME/.botagent_tmp_$$"
  mkdir -p "$TMPD" || die "建临时目录失败"
  warn "mktemp 不可用，改用 $TMPD"
fi
ZIP="$TMPD/botagent.zip"
URLS="
https://github.com/${REPO}/releases/download/${VERSION}/Botagent-${VERSION}.zip
https://gh-proxy.com/https://github.com/${REPO}/releases/download/${VERSION}/Botagent-${VERSION}.zip
https://ghproxy.cc/https://github.com/${REPO}/releases/download/${VERSION}/Botagent-${VERSION}.zip
"
ok=0
if [ -n "$LOCAL_ZIP" ] && [ -f "$LOCAL_ZIP" ]; then
  cp -f "$LOCAL_ZIP" "$ZIP" && ok=1
  dim "用本地包：$LOCAL_ZIP"
fi
if [ "$ok" != "1" ]; then
for u in $URLS; do
  dim "尝试 $u"
  if curl -fsSL --connect-timeout 12 --max-time 300 -o "$ZIP" "$u"; then ok=1; break; fi
done
fi
[ "$ok" = "1" ] || die "下载失败（临时目录 $TMPD）。可以手动下载 zip 放到 /sdcard/Download/ 再跑： bash install_phone.sh --zip /sdcard/Download/Botagent-${VERSION}.zip"

say "解压"
unzip -oq "$ZIP" -d "$TMPD/x" || die "解压失败"
SRC_AIBOT="$(find "$TMPD/x" -maxdepth 4 -type d -name aibot | head -1)"
[ -n "$SRC_AIBOT" ] || die "压缩包里没找到 aibot 目录"

mkdir -p "$APP_DIR" || die "创建 $APP_DIR 失败"
cp -f "$SRC_AIBOT"/*.py "$APP_DIR"/ 2>/dev/null
mkdir -p "$APP_DIR/assets"
cp -f "$SRC_AIBOT"/assets/* "$APP_DIR/assets"/ 2>/dev/null
cp -f "$SRC_AIBOT"/*.sh "$APP_DIR"/ 2>/dev/null
[ -f "$APP_DIR/qq_bot.py" ] || die "复制文件失败"
dim "程序在 $APP_DIR"

# ---------- 3) 配置 ----------
CFG="$APP_DIR/config.json"
if [ -f "$CFG" ]; then
  say "已有配置，保留（想重配就删掉 $CFG 再跑）"
else
  say "填三个问题（直接回车用默认）"
  printf "  你的 QQ 号（主人，必填）: "; read -r OWNER
  printf "  机器人 QQ 号（可空，自动识别）: "; read -r BOTUIN
  printf "  API Key（可空，之后在控制台填）: "; read -r APIKEY
  printf "  要响应的群号（逗号分隔，可空）: "; read -r GROUPS

  BG_OWNER="$OWNER" BG_BOTUIN="$BOTUIN" BG_APIKEY="$APIKEY" BG_GROUPS="$GROUPS" BG_CFG="$CFG" \
  python - <<'PYEOF'
import json, os, re
cfg = {
    "api_key": (os.environ.get("BG_APIKEY") or "").strip(),
    "base_url": "https://api.deepseek.com/chat/completions",
    "model": "deepseek-chat",
    "max_steps": 8, "max_tokens": 1500,
    "owner_uid": 0, "adult_uids": [], "allowed_private_uids": [],
    "allowed_groups": [], "safe_groups": [], "watch_group": 0, "watch_uids": [],
    "bot_uin": 0, "feedback_email": "", "allow_remote": False,
    "napcat_ws": "ws://127.0.0.1:3001",
}
o = (os.environ.get("BG_OWNER") or "").strip()
if o.isdigit():
    cfg["owner_uid"] = int(o)
    cfg["adult_uids"] = [int(o)]
    cfg["allowed_private_uids"] = [int(o)]
b = (os.environ.get("BG_BOTUIN") or "").strip()
if b.isdigit():
    cfg["bot_uin"] = int(b)
g = [int(x) for x in re.split(r"[,，\s]+", (os.environ.get("BG_GROUPS") or "")) if x.isdigit()]
if g:
    cfg["allowed_groups"] = g
    cfg["safe_groups"] = g[:1]
p = os.environ["BG_CFG"]
with open(p, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
os.chmod(p, 0o600)
print("  配置已写入，owner=%s 群=%s" % (cfg["owner_uid"], cfg["allowed_groups"] or "无"))
PYEOF
fi

# token
[ -f "$APP_DIR/webui_token.txt" ] || python -c "import secrets,os;p=os.path.join('$APP_DIR','webui_token.txt');open(p,'w').write(secrets.token_hex(6));os.chmod(p,0o600)"
TOKEN="$(cat "$APP_DIR/webui_token.txt" 2>/dev/null)"

# ---------- 4) 控制脚本 ----------
cat > "$APP_DIR/start.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")" || exit 1
mkdir -p logs
pkill -f webui.py 2>/dev/null; pkill -f qq_bot.py 2>/dev/null
sleep 1
nohup python webui.py >> logs/webui.log 2>&1 &
sleep 2
nohup python qq_bot.py >> logs/bot.log 2>&1 &
sleep 2
echo "控制台: http://127.0.0.1:8080/app"
echo "token : $(cat webui_token.txt 2>/dev/null)"
EOS
cat > "$APP_DIR/stop.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
pkill -f qq_bot.py 2>/dev/null; pkill -f webui.py 2>/dev/null
echo 已停止
EOS
cat > "$APP_DIR/status.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
echo "bot  : $(pgrep -f qq_bot.py | wc -l)"
echo "webui: $(pgrep -f webui.py | wc -l)"
python - <<'PY'
import urllib.request, json
try:
    d = json.loads(urllib.request.urlopen("http://127.0.0.1:8080/api/qq", timeout=5).read())
    print("online:", d.get("online"), "| napcat:", d.get("nap_phase") or d.get("nap_state"))
except Exception as e:
    print("webui 没起来:", e)
PY
EOS
chmod +x "$APP_DIR"/*.sh

# ---------- 5) 启动 ----------
if [ "$NO_START" = "1" ]; then
  say "跳过启动（--no-start）"
else
  say "启动服务"
  bash "$APP_DIR/start.sh"
fi

sleep 3
echo
say "自检"
python - <<'PY'
import socket, urllib.request, json
def port(p):
    try:
        s = socket.socket()
    except Exception:
        return None          # 某些环境（非 App 进程）没权限建 socket
    try:
        r = s.connect_ex(("127.0.0.1", p))
        return r == 0
    finally:
        s.close()
p80 = port(8080); p30 = port(3001)
fmt = lambda v, on, off: "未知" if v is None else (on if v else off)
print("  8080 控制台 :", fmt(p80, "开", "关"))
print("  3001 NapCat :", fmt(p30, "开", "关（QQ 那半边还没装，见下面）"))
try:
    d = json.loads(urllib.request.urlopen("http://127.0.0.1:8080/api/qq", timeout=5).read())
    print("  webui       : 正常", d.get("ports"))
except Exception as e:
    print("  webui       : 异常", e)
PY

cat <<EOF

${C_OK}装好了。${C_0}

  程序目录  $APP_DIR
  token     $TOKEN

  启动  bash $APP_DIR/start.sh
  停止  bash $APP_DIR/stop.sh
  状态  bash $APP_DIR/status.sh

${C_WARN}还差一步：QQ 那半边${C_0}
  控制台现在能开，但 QQ 里还看不到机器人 —— 因为协议端（NapCat）没起来。
  做法：装 AstrBot App（自带 Ubuntu + Linux QQ + NapCat），在里面扫码登录 QQ，
        把它的 WebSocket 端口设成 3001，这边就能连上。

  然后手机浏览器打开 http://127.0.0.1:8080/app 管理（token 见上面）。

${C_DIM}（控制台 App 想装的话，解压包里 手机端手动部署/Botagent.apk，装上开无障碍就能让 AI 点屏幕）${C_0}
EOF
