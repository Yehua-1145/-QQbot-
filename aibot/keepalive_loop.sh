#!/system/bin/sh
# QQ 保活循环（单实例 + 断路器；绝不死循环刷重启）
export HOME=/data/data/com.termux/files/home
export PATH=/data/data/com.termux/files/usr/bin:$PATH
A=$HOME/aibot
LOG=$A/keepalive.log

# ---------- 单实例锁（PID 校验，死锁自动回收）----------
acquire_lock() {
  L=$1
  for i in 1 2 3; do
    if [ -f "$L" ]; then
      P=$(cat "$L" 2>/dev/null)
      if [ -n "$P" ] && [ "$P" != "$$" ] && kill -0 "$P" 2>/dev/null; then
        return 1
      fi
      rm -f "$L"
    fi
    echo $$ > "$L"
    sleep 0.3
    if [ "$(cat "$L" 2>/dev/null)" = "$$" ]; then
      return 0
    fi
  done
  return 1
}
LOCK=/data/local/tmp/.keepalive.lock
SHARED=/data/local/tmp/.last_restart      # 与 watchdog 共用的重启节流戳


say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG"; }

notify() {
  cmd notification post -S bigtext -t "$1" phoneagent "$2" >/dev/null 2>&1
}

# Termux 的 netstat 看不到端口，用真实 TCP 连接探测
port_ok() {
  python3 - <<'PY' 2>/dev/null
import socket
s = socket.socket(); s.settimeout(3)
try:
    s.connect(("127.0.0.1", 3001)); print("ok")
except Exception:
    print("fail")
finally:
    s.close()
PY
}

# 与 watchdog 共享的节流：180 秒内只允许一次重启动作
may_restart() {
  NOW=$(date +%s)
  LAST=$(cat "$SHARED" 2>/dev/null || echo 0)
  if [ $((NOW - LAST)) -lt 180 ]; then
    return 1
  fi
  echo "$NOW" > "$SHARED"
  return 0
}

# 只允许一个"重启者"：watchdog 活着时，本循环只负责通知，绝不动手
watchdog_alive() {
  pgrep -f "watchdog[.]sh" >/dev/null 2>&1
}

if ! acquire_lock $LOCK; then
  echo "keepalive_loop.sh already running, exit"
  exit 0
fi

RESTARTS=0
WINDOW_START=$(date +%s)
FAILS=0

while :; do
  sleep 120

  # 断路器：一小时内重启超过 5 次 → 停止自动重启，只通知，歇一小时
  NOW=$(date +%s)
  if [ $((NOW - WINDOW_START)) -ge 3600 ]; then
    WINDOW_START=$NOW
    RESTARTS=0
  fi
  if [ "$RESTARTS" -ge 5 ]; then
    say "一小时内已重启 $RESTARTS 次，进入冷却（1 小时不再自动重启）"
    notify "QQ 反复掉线" "已暂停自动重启 1 小时，请手动检查一次"
    sleep 3600
    RESTARTS=0
    WINDOW_START=$(date +%s)
    continue
  fi

  # 1) 进程在不在
  if ! pgrep -f "aibot/qq_bot[.]py" >/dev/null 2>&1; then
    if watchdog_alive; then
      say "qq_bot 不在，但 watchdog 在管 —— 只通知不动手"
      notify "QQ 机器人似乎停了" "watchdog 正在处理；若 5 分钟内没恢复请看通知/日志"
    elif may_restart; then
      say "qq_bot 不在，重启"
      sh /data/local/tmp/restart_bot2.sh >/dev/null 2>&1
      notify "QQ 机器人已自动重启" "检测到进程不在，已拉起"
      RESTARTS=$((RESTARTS + 1))
    fi
    sleep 20
    continue
  fi

  # 2) NapCat 端口（连续 2 次失败 + 节流后才动它）
  P=$(port_ok)
  if [ "$P" != "ok" ]; then
    FAILS=$((FAILS + 1))
    say "3001 探测失败（第 $FAILS 次）"
    if [ "$FAILS" -ge 2 ] && watchdog_alive; then
      say "3001 连续不通，watchdog 在管 —— 仅通知"
      notify "QQ 掉线了" "NapCat 端口不通，watchdog 正在重启；若需扫码请打开手机 QQ"
      FAILS=0
    elif [ "$FAILS" -ge 2 ] && may_restart; then
      FAILS=0
      say "3001 连续不通，拉起 NapCat"
      sh /data/local/tmp/napcat_quick.sh >/dev/null 2>&1 &
      notify "QQ 掉线了" "NapCat 端口不通，已自动重拉；若需扫码请打开手机 QQ"
      RESTARTS=$((RESTARTS + 1))
    fi
  else
    [ "$FAILS" -ge 2 ] && say "3001 已恢复"
    FAILS=0
  fi

  # 3) 重连风暴
  N=$(tail -40 "$A/qq_bot.log" 2>/dev/null | grep -c "reconnect in 5s")
  if [ "$N" -ge 6 ] && watchdog_alive; then
    say "重连风暴（$N 次），由 watchdog 处理"
  elif [ "$N" -ge 6 ] && may_restart; then
    say "重连风暴（$N 次），重启 bot"
    sh /data/local/tmp/restart_bot2.sh >/dev/null 2>&1
    notify "QQ 机器人重连异常" "检测到反复重连，已自动重启"
    RESTARTS=$((RESTARTS + 1))
  fi
done
