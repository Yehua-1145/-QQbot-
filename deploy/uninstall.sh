#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  Botagent 卸载脚本
#  用法：
#    bash uninstall.sh              停止 + 删程序，保留配置到 ~/botagent-config-backup.json
#    bash uninstall.sh --purge      全删（配置、token、备份、开机自启）
#    bash uninstall.sh --purge --proot   连 proot Ubuntu 一起删（约 500MB，会删掉 Linux QQ）
#    bash uninstall.sh -y           不再询问，直接执行
# ============================================================
set -u

APP_DIR="${HOME}/aibot"
PURGE=0
RM_PROOT=0
ASSUME_YES=0

C_OK="\033[32m"; C_WARN="\033[33m"; C_ERR="\033[31m"; C_DIM="\033[2m"; C_0="\033[0m"
say()  { printf "${C_OK}==>${C_0} %s\n" "$*"; }
warn() { printf "${C_WARN}[!]${C_0} %s\n" "$*"; }
die()  { printf "${C_ERR}[x]${C_0} %s\n" "$*" >&2; exit 1; }
dim()  { printf "${C_DIM}    %s${C_0}\n" "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1 ;;
    --proot) RM_PROOT=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    --dir) shift; APP_DIR="${1:-$APP_DIR}" ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) warn "忽略未知参数：$1" ;;
  esac
  shift
done

confirm() {
  [ "$ASSUME_YES" = "1" ] && return 0
  printf "%s [y/N] " "$1"
  read -r ans
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

[ -d "$APP_DIR" ] || warn "没找到 $APP_DIR（可能已经卸载过）"

say "停止本目录下正在运行的进程"
# 只杀 cmdline 里带 APP_DIR 的进程，避免误杀别的实例
KILLED=0
for d in /proc/[0-9]*; do
  pid=${d#/proc/}
  [ "$pid" = "$$" ] && continue
  cmd=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null) || continue
  case "$cmd" in
    *"$APP_DIR"*)
      kill -9 "$pid" 2>/dev/null && KILLED=$((KILLED+1))
      ;;
  esac
done
dim "已停止 $KILLED 个进程（匹配 $APP_DIR）"
rm -f "$APP_DIR"/qq_bot.pid "$APP_DIR"/webui.pid 2>/dev/null

say "移除开机自启"
BOOT="$HOME/.termux/boot/start-botagent.sh"
if [ -f "$BOOT" ]; then
  rm -f "$BOOT" && dim "已删除 $BOOT"
else
  dim "没有自启脚本"
fi

if [ "$PURGE" = "1" ]; then
  if confirm "确认彻底删除程序目录和配置？（不可恢复）"; then
    say "删除程序目录 $APP_DIR"
    rm -rf "$APP_DIR"
    BACKUP="$HOME/botagent-config-backup.json"
    [ -f "$BACKUP" ] && rm -f "$BACKUP" && dim "已删除备份 $BACKUP"
  else
    warn "已取消，什么都没删"
    exit 0
  fi
else
  # 保留配置
  if [ -f "$APP_DIR/config.json" ]; then
    BACKUP="$HOME/botagent-config-backup.json"
    cp -f "$APP_DIR/config.json" "$BACKUP" 2>/dev/null && chmod 600 "$BACKUP" 2>/dev/null
    dim "配置已备份到 $BACKUP"
  fi
  say "删除程序目录（保留备份）"
  rm -rf "$APP_DIR"
fi

if [ "$RM_PROOT" = "1" ]; then
  if command -v proot-distro >/dev/null 2>&1; then
    if confirm "确认删除 proot Ubuntu 容器？（会删掉里面的 Linux QQ 和登录状态）"; then
      say "删除 Ubuntu 容器"
      proot-distro remove ubuntu >/dev/null 2>&1 && dim "已删除" || warn "删除失败，可手动： proot-distro remove ubuntu"
    else
      dim "保留容器"
    fi
  else
    warn "没装 proot-distro，跳过"
  fi
fi

echo
say "卸载完成"
cat <<EOF

  已停止    bot / webui / 抓图任务
  已删除    $APP_DIR
  $( [ "$PURGE" = "1" ] && echo "配置已彻底删除" || echo "配置备份   $HOME/botagent-config-backup.json" )
  自启      $( [ -f "$BOOT" ] && echo "仍存在（请手动确认）" || echo "已移除" )

  想重新安装：  bash install.sh
  想恢复配置：  cp ~/botagent-config-backup.json ~/aibot/config.json

EOF
