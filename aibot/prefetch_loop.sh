#!/system/bin/sh
# 闲时图库预取循环（单实例 + 超时保护）
export HOME=/data/data/com.termux/files/home
export PATH=/data/data/com.termux/files/usr/bin:$PATH
A=$HOME/aibot
LOCK=/data/local/tmp/.prefetch.lock
LOG=$A/prefetch_loop.log

acquire_lock() {
  L=$1
  i=0
  while [ $i -lt 3 ]; do
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
    i=$((i + 1))
  done
  return 1
}

if ! acquire_lock "$LOCK"; then
  echo "prefetch_loop already running, exit"
  exit 0
fi

cd "$A" || exit 1

while :; do
  H=$(date +%H)
  if [ "$H" -ge 3 ] && [ "$H" -lt 7 ]; then
    echo "--- $(date '+%m-%d %H:%M') 预取开始 ---" >> "$LOG"
    timeout 1200 nice -n 10 nice -n 15 python3 prefetch.py >> "$LOG" 2>&1
    RC=$?
    [ "$RC" = "124" ] && echo "--- 预取超时被杀(124) ---" >> "$LOG"
    sleep 3600
  else
    sleep 600
  fi
done