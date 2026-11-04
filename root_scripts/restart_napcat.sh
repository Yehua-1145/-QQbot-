#!/system/bin/sh
# 重启 NapCat 容器（精确杀进程，避免 pkill -f 自杀和实例堆积）
# 先拍崩溃现场 + 先 TERM 后 KILL：硬杀会让 QQ 登录态失效，下次就得扫码

RUNLOG_ROOT=/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/root
TS=$(date +%Y%m%d_%H%M%S)
OUT=/data/local/tmp/napcat_crash_$TS.log
{
    echo "=== manual napcat restart snapshot $TS ==="
    uptime
    grep -E 'MemTotal|MemAvailable|SwapFree' /proc/meminfo
    ps -A -o PID,ELAPSED,RSS,NAME 2>/dev/null | sort -k3 -rn | head -10
    ps -ef 2>/dev/null | grep -E 'opt/QQ|proot|Xvfb' | grep -v grep | cut -c1-150
    echo "--- napcat_run.log tail 80 ---"
    tail -80 $RUNLOG_ROOT/napcat_run.log 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g'
    echo "--- dmesg tail 20 ---"
    dmesg 2>/dev/null | tail -20
} > $OUT 2>&1
ls -t /data/local/tmp/napcat_crash_*.log 2>/dev/null | tail -n +6 | while read f; do rm -f "$f"; done

pkill -TERM -f 'opt/QQ' 2>/dev/null
sleep 3
pkill -TERM -x proot 2>/dev/null
pkill -TERM -x Xvfb 2>/dev/null
sleep 4
pkill -9 -x proot 2>/dev/null
pkill -9 -x Xvfb 2>/dev/null
pkill -9 -f 'opt/QQ' 2>/dev/null
sleep 3
setsid sh /data/local/tmp/napcat_quick.sh </dev/null > /dev/null 2>&1 &
sleep 1
echo "NapCat 重启中（约 60-75 秒）；现场已存到 $OUT"
