#!/system/bin/sh
# 按时段自动切换调优模式：03:00-07:00 quiet，其余 day
export PATH=/data/data/com.termux/files/usr/bin:$PATH
LOCK=/data/local/tmp/.tune.lock
if [ -f "$LOCK" ]; then
  P=$(cat "$LOCK" 2>/dev/null)
  if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then
    echo "tune_loop already running"; exit 0
  fi
fi
echo $$ > "$LOCK"

STATE=/data/local/tmp/.tune_mode
while :; do
  H=$(date +%H)
  if [ "$H" -ge 3 ] && [ "$H" -lt 7 ]; then
    WANT=quiet
  else
    WANT=day
  fi
  CUR=$(cat "$STATE" 2>/dev/null)
  if [ "$CUR" != "$WANT" ]; then
    sh /data/local/tmp/tune_mode.sh "$WANT"
  fi
  sleep 300
done