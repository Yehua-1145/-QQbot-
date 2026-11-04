#!/system/bin/sh
# 按时段调优（root）
#   day   : 正常时段 —— 不限制后台、CPU 不降频，息屏也保持响应
#   quiet : 安静时段(03-07) —— 稍微限制：CPU 上限压到一半，但网络/后台照常（QQ 不能掉）
MODE=$1
LIT=/sys/devices/system/cpu/cpu0/cpufreq
BIG=/sys/devices/system/cpu/cpu4/cpufreq
LOG=/data/local/tmp/tune.log
STATE=/data/local/tmp/.tune_mode

say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG"; }

w() { echo "$2" > "$1" 2>/dev/null; }

# 所有核心上线
all_cores_online() {
  for n in 1 2 3 4 5 6 7; do
    w /sys/devices/system/cpu/cpu$n/online 1
  done
}

# 先降 min 再设 max（顺序反了会被内核拒绝）
set_range() {
  D=$1; MIN=$2; MAX=$3
  w "$D/scaling_min_freq" 300000
  w "$D/scaling_max_freq" "$MAX"
  w "$D/scaling_min_freq" "$MIN"
}

case "$MODE" in
  quiet)
    all_cores_online
    w "$LIT/scaling_governor" interactive
    w "$BIG/scaling_governor" interactive
    set_range "$LIT" 300000 960000
    set_range "$BIG" 300000 1228800
    # 后台与网络照旧：Doze 保持关闭，WiFi 不休眠（掉了就麻烦了）
    dumpsys deviceidle disable >/dev/null 2>&1
    settings put global wifi_sleep_policy 2
    settings put global low_power 0
    echo quiet > "$STATE"
    say "quiet mode: little<=960M big<=1.22G, cores=$(cat /sys/devices/system/cpu/online)"
    ;;
  day|*)
    all_cores_online
    w "$LIT/scaling_governor" interactive
    w "$BIG/scaling_governor" interactive
    set_range "$LIT" 800000 1900800
    set_range "$BIG" 1000000 2457600
    dumpsys deviceidle disable >/dev/null 2>&1
    settings put global wifi_sleep_policy 2
    settings put global low_power 0
    cmd appops set com.termux WAKE_LOCK allow 2>/dev/null
    cmd appops set com.astrbot.astrbot_android WAKE_LOCK allow 2>/dev/null
    echo day > "$STATE"
    say "day mode: little>=800M big>=1G, cores=$(cat /sys/devices/system/cpu/online)"
    ;;
esac

# 让 QQ / 机器人在低内存时也最后被杀
for p in $(pgrep -x proot) $(pgrep -f 'opt/QQ') $(pgrep -f 'aibot/qq_bot[.]py') $(pgrep -f 'aibot/webui[.]py'); do
  echo -900 > /proc/$p/oom_score_adj 2>/dev/null
done