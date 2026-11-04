#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  Botagent 傻瓜式安装脚本（Termux）
#  用法：  bash install.sh
#  可选：  bash install.sh --with-napcat   顺带装 Linux QQ + NapCat
#          bash install.sh --dir ~/mybot   指定安装目录
# ============================================================
set -u

APP_DIR="${HOME}/aibot"
WITH_NAPCAT=0
NONINTERACTIVE=0
REPO_URL="${BOTAGENT_REPO:-}"

C_OK="\033[32m"; C_WARN="\033[33m"; C_ERR="\033[31m"; C_DIM="\033[2m"; C_0="\033[0m"

say()  { printf "${C_OK}==>${C_0} %s\n" "$*"; }
warn() { printf "${C_WARN}[!]${C_0} %s\n" "$*"; }
die()  { printf "${C_ERR}[x]${C_0} %s\n" "$*" >&2; exit 1; }
dim()  { printf "${C_DIM}    %s${C_0}\n" "$*"; }

# ---------- 参数 ----------
while [ $# -gt 0 ]; do
  case "$1" in
    --with-napcat) WITH_NAPCAT=1 ;;
    --noninteractive) NONINTERACTIVE=1 ;;
    --dir) shift; APP_DIR="${1:-$APP_DIR}" ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) warn "忽略未知参数：$1" ;;
  esac
  shift
done

# ---------- 环境检查 ----------
say "检查运行环境"
case "${PREFIX:-}" in
  *com.termux*|*termux*) : ;;
  *) warn "看起来不是 Termux（PREFIX=${PREFIX:-空}），继续但可能失败" ;;
esac

command -v python >/dev/null 2>&1 || die "没有 python，请先装： pkg install python"
PY="$(command -v python)"
dim "python: $PY"

# ---------- 安装依赖 ----------
say "安装必要组件（python / curl / proot-distro）"
if command -v pkg >/dev/null 2>&1; then
  yes | pkg install -y python curl proot-distro >/dev/null 2>&1 || \
    warn "pkg install 有报错，若后面启动失败请手动执行： pkg install python curl proot-distro"
else
  warn "找不到 pkg，跳过依赖安装"
fi

# ---------- 取代码 ----------
say "准备程序目录：$APP_DIR"
mkdir -p "$APP_DIR" || die "无法创建 $APP_DIR"

SRC_CONFIG="/sdcard/Download/botagent/config.json"
SRC_DIR=""
for c in "./aibot" "../aibot" "/sdcard/Download/new_aibot"; do
  [ -f "$c/qq_bot.py" ] && SRC_DIR="$c" && break
done

if [ -n "$SRC_DIR" ]; then
  dim "从本地复制：$SRC_DIR"
  cp -f "$SRC_DIR"/*.py "$APP_DIR"/ 2>/dev/null
  mkdir -p "$APP_DIR/assets"
  cp -f "$SRC_DIR"/assets/* "$APP_DIR/assets"/ 2>/dev/null
else
  if [ -n "$REPO_URL" ]; then
    say "从仓库拉取：$REPO_URL"
    if command -v git >/dev/null 2>&1; then
      tmpd=$(mktemp -d)
      git clone --depth 1 "$REPO_URL" "$tmpd/repo" >/dev/null 2>&1 || die "git clone 失败"
      cp -f "$tmpd/repo"/aibot/*.py "$APP_DIR"/ 2>/dev/null
      rm -rf "$tmpd"
    else
      die "需要 git 拉代码： pkg install git"
    fi
  else
    warn "没找到代码，也没给仓库地址"
    dim "把 aibot/*.py 放到 $APP_DIR，或用： BOTAGENT_REPO=<仓库地址> bash install.sh"
  fi
fi

[ -f "$APP_DIR/qq_bot.py" ] || die "缺少 qq_bot.py，安装中止"

# ---------- 交互式配置 ----------
CFG="$APP_DIR/config.json"
if [ "$NONINTERACTIVE" = "1" ] && [ -f "$SRC_CONFIG" ]; then
  say "非交互模式：使用预置配置 $SRC_CONFIG"
  cp -f "$SRC_CONFIG" "$CFG" && chmod 600 "$CFG"
  dim "已写入 $CFG"
elif [ -f "$CFG" ]; then
  say "已存在配置 $CFG，保留原设置（想重配就删掉它再跑一次）"
else
  say "第一次配置（直接回车用默认值）"
  printf "  API Key（可空，之后在手机控制台填）: "; read -r API_KEY
  printf "  你的 QQ 号（主人）: "; read -r OWNER_UID
  printf "  要响应的群号（逗号分隔，留空=不响应群）: "; read -r BOT_GROUPS
  printf "  机器人 QQ 号（登录的那个，留空=自动）: "; read -r BOT_UIN
  printf "  反馈接收邮箱（留空=不启用邮件）: "; read -r FB_EMAIL

  dim "采集到：owner=$OWNER_UID groups=${BOT_GROUPS:-（空）} bot=${BOT_UIN:-（自动）}"
  BG_API_KEY="$API_KEY" BG_OWNER="$OWNER_UID" BG_GROUPS="$BOT_GROUPS" \
  BG_BOT_UIN="$BOT_UIN" BG_FB="$FB_EMAIL" BG_CFG="$CFG" "$PY" - <<'PYEOF'
import json, os, re

cfg_path = os.environ["BG_CFG"]
api_key = (os.environ.get("BG_API_KEY") or "").strip()
owner_raw = (os.environ.get("BG_OWNER") or "").strip()
groups_raw = (os.environ.get("BG_GROUPS") or "").strip()
bot_raw = (os.environ.get("BG_BOT_UIN") or "").strip()
fb = (os.environ.get("BG_FB") or "").strip()

owner = int(owner_raw) if owner_raw.isdigit() else 0
bot_uin = int(bot_raw) if bot_raw.isdigit() else 0
groups = [int(x) for x in re.split(r"[,，\s]+", groups_raw) if x.isdigit() and int(x) > 1000]

d = {
    "api_key": api_key,
    "base_url": "https://api.deepseek.com/chat/completions",
    "model": "deepseek-chat",
    "max_steps": 8,
    "max_tokens": 1500,
    "owner_uid": owner,
    "adult_uids": [owner] if owner else [],
    "allowed_private_uids": [owner] if owner else [],
    "allowed_groups": groups,
    "safe_groups": groups[:1],
    "watch_group": 0,
    "watch_uids": [],
    "bot_uin": bot_uin,
    "feedback_email": fb,
    "allow_remote": False,
}
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
os.chmod(cfg_path, 0o600)
print("配置已写入:", cfg_path)
print("  owner_uid =", owner, "| 群 =", groups or "（无）")
PYEOF
fi

# ---------- 生成访问 token ----------
TOKEN_FILE="$APP_DIR/webui_token.txt"
if [ ! -f "$TOKEN_FILE" ]; then
  "$PY" - "$TOKEN_FILE" <<'PYEOF'
import secrets, sys, os
p = sys.argv[1]
open(p, "w").write(secrets.token_hex(6))
os.chmod(p, 0o600)
PYEOF
fi
TOKEN="$(cat "$TOKEN_FILE" 2>/dev/null || echo "")"

# ---------- 启动 / 停止 / 状态 脚本 ----------
say "生成控制脚本（start.sh / stop.sh / status.sh）"
cat > "$APP_DIR/start.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")" || exit 1
mkdir -p logs
nohup python webui.py   >> logs/webui.log 2>&1 &
sleep 1
nohup python qq_bot.py  >> logs/bot.log   2>&1 &
sleep 2
echo "已启动："
echo "  控制台  http://127.0.0.1:8080/app"
echo "  token   $(cat webui_token.txt 2>/dev/null)"
EOS

cat > "$APP_DIR/stop.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
pkill -f "qq_bot.py" 2>/dev/null
pkill -f "webui.py"  2>/dev/null
rm -f qq_bot.pid webui.pid
echo "已停止"
EOS

cat > "$APP_DIR/status.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
echo "bot:   $(pgrep -f 'qq_bot.py'   | wc -l)"
echo "webui: $(pgrep -f 'webui.py'    | wc -l)"
echo "token: $(cat webui_token.txt 2>/dev/null)"
curl -s -m 5 "http://127.0.0.1:8080/api/qq?token=$(cat webui_token.txt 2>/dev/null)" 2>/dev/null
echo
EOS

chmod +x "$APP_DIR"/start.sh "$APP_DIR"/stop.sh "$APP_DIR"/status.sh

# ---------- 开机自启 ----------
say "注册开机自启（需要装 Termux:Boot 插件才生效）"
mkdir -p "$HOME/.termux/boot" && {
  cat > "$HOME/.termux/boot/start-botagent.sh" <<EOS
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock 2>/dev/null
sleep 5
bash "$APP_DIR/start.sh" >> "$APP_DIR/logs/boot.log" 2>&1
EOS
  chmod +x "$HOME/.termux/boot/start-botagent.sh"
  dim "已写入 ~/.termux/boot/start-botagent.sh"
} || warn "写开机自启失败（不影响手动启动）"

# ---------- 可选：NapCat ----------
if [ "$WITH_NAPCAT" = "1" ]; then
  say "安装 proot Ubuntu（Linux QQ 的运行环境，约 500MB）"
  proot-distro install ubuntu >/dev/null 2>&1 || warn "ubuntu 已存在或安装失败，继续"
  dim "装完后还需要在 Ubuntu 里装 Linux QQ + NapCat，步骤见 deploy/DEPLOY.md"
  dim "登录命令： proot-distro login ubuntu"
fi

# ---------- 完成 ----------
echo
say "安装完成"
cat <<EOF

  程序目录   $APP_DIR
  配置文件   $CFG          （含 API Key，权限 600）
  访问 token $TOKEN

  启动：  bash $APP_DIR/start.sh
  停止：  bash $APP_DIR/stop.sh
  状态：  bash $APP_DIR/status.sh

  控制台：  http://127.0.0.1:8080/app
  （手机浏览器打开即可，本机访问不需要 token）

  还需要做的两件事：
   1) 装 Termux:Boot 插件 → 开机自启生效
   2) 手机设置里给 Termux 开「无限制后台」+ 关电池优化

EOF
