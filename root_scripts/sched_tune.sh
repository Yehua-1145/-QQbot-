#!/system/bin/sh
# 调度优化 v3
# 要点：
#   1) 这台机 toybox taskset 认十六进制掩码（f0/c0/6/3）
#   2) toybox renice -n N 是"增量"语义（0 -> 10 -> 19），必须先算差值再调用
#   3) 每 30 秒重跑一次，保证进程重启后也钉得住

M_QQ=f0      # cpu4-7 大核
M_BOT=c0     # cpu6-7
M_WEB=c0
M_NET=6      # cpu1-2
M_BG=3       # cpu0-1

LOG=/data/local/tmp/sched_tune.log
log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$1" >> "$LOG"; }

set_nice() {
  P="$1"
  T="$2"
  C=$(awk '{print $19}' /proc/$P/stat 2>/dev/null)
  [ -z "$C" ] && return
  if [ "$C" != "$T" ]; then
    D=$((T - C))
    renice -n "$D" -p "$P" >/dev/null 2>&1
  fi
}

pin() {
  PAT="$1"
  MASK="$2"
  NI="$3"
  CNT=0
  for p in $(pgrep -f "$PAT" 2>/dev/null); do
    if taskset -p "$MASK" "$p" >/dev/null 2>&1; then
      CNT=$((CNT+1))
    fi
    if [ -n "$NI" ]; then
      set_nice "$p" "$NI"
    fi
  done
  [ "$CNT" -gt 0 ] && log "$PAT -> $MASK ($CNT)"
  return 0
}

pin "opt/QQ"        "$M_QQ"  "-10"
pin "proot -0"      "$M_QQ"  "-10"
pin "qq_bot.py"     "$M_BOT" "-6"
pin "webui.py"      "$M_WEB" "-5"
pin "clash.meta"    "$M_NET" "0"
pin "prefetch.py"   "$M_BG"  "15"
pin "worker.py"     "$M_BG"  "15"

for c in 0 1 2 3; do
  echo 979200 > /sys/devices/system/cpu/cpu$c/cpufreq/scaling_min_freq 2>/dev/null
done
for c in 4 5 6 7; do
  echo 1190400 > /sys/devices/system/cpu/cpu$c/cpufreq/scaling_min_freq 2>/dev/null
done

for c in 4 5 6 7; do
  D=/sys/devices/system/cpu/cpu$c/cpufreq/interactive
  echo 1804800 > "$D/hispeed_freq" 2>/dev/null
  echo 70 > "$D/go_hispeed_load" 2>/dev/null
  echo 20000 > "$D/min_sample_time" 2>/dev/null
  echo "80000 1804800:40000 2457600:20000" > "$D/above_hispeed_delay" 2>/dev/null
done
for c in 0 1 2 3; do
  D=/sys/devices/system/cpu/cpu$c/cpufreq/interactive
  echo 1420800 > "$D/hispeed_freq" 2>/dev/null
  echo 75 > "$D/go_hispeed_load" 2>/dev/null
done

exit 0
