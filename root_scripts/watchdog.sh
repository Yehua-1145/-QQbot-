#!/system/bin/sh
# PhoneAgent watchdog - keeps NapCat, QQ bot and WebUI alive.
# Runs as root. Restarts anything that died.
#
# 2026-10-26 加固：
#   - 重启 NapCat 前先拍“崩溃现场”（dmesg/ps/内存/上一次日志尾巴），保留最近 5 份
#   - 停 QQ 先 TERM 再 KILL（硬杀容易让 QQ 的登录态失效，下次就得扫码）
#   - 确保 QQ/腾讯域名走直连（fake-ip 下 GEOIP 可能判成国外，走代理会触发风控）

LOG=/data/local/tmp/watchdog.log
AIBOT=/data/data/com.termux/files/home/aibot
TERMUX_BASH=/data/data/com.termux/files/usr/bin/bash
RUNLOG_ROOT=/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/root
# WiFi 掉线时尝试重连的 SSID（开放网络）
WIFI_SSID=hnxxjsxy


# 用真实 TCP 连接判断端口（本机 netstat 经常看不到自己起的端口）
tcp_ok() {
    /data/data/com.termux/files/usr/bin/python3 -c "
import socket, sys
s = socket.socket(); s.settimeout(2)
try:
    s.connect(('127.0.0.1', $1)); sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

log() { echo "[$(date '+%m-%d %H:%M:%S')] $1" >> $LOG; }

# 手机通知栏提示（掉登录等需要人处理的事，别默默失败）
notify() {
    cmd notification post -S bigtext -t "PhoneAgent" phoneagent "$1" > /dev/null 2>&1
}

# 掉登录状态跟踪（避免每 30 秒重复通知）
LOGOUT_COUNT=0
LOGOUT_NOTIFIED=0
RELOGIN_STAMP=/data/local/tmp/.relogin_stamp

# 保护 QQ 进程不被低内存杀手干掉（这是“莫名掉线”的隐形原因之一）
protect_oom() {
    for p in $(pgrep -x proot) $(pgrep -f 'opt/QQ') $(pgrep -x Xvfb); do
        echo -900 > /proc/$p/oom_score_adj 2>/dev/null
    done
}

# 崩溃现场快照：下次“为什么掉线”就有据可查
snapshot_napcat() {
    TS=$(date +%Y%m%d_%H%M%S)
    OUT=/data/local/tmp/napcat_crash_$TS.log
    {
        echo "=== napcat snapshot $TS ==="
        echo "--- uptime / load ---"
        uptime
        echo "--- meminfo ---"
        grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree' /proc/meminfo
        echo "--- top RSS ---"
        ps -A -o PID,ELAPSED,RSS,NAME 2>/dev/null | sort -k3 -rn | head -10
        echo "--- proot / QQ processes ---"
        ps -ef 2>/dev/null | grep -E 'opt/QQ|proot|Xvfb' | grep -v grep | cut -c1-150
        echo "--- napcat_run.log tail 80 ---"
        tail -80 $RUNLOG_ROOT/napcat_run.log 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g'
        echo "--- napcat_run.prev.log tail 40 ---"
        tail -40 $RUNLOG_ROOT/napcat_run.prev.log 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g'
        echo "--- dmesg tail 30 ---"
        dmesg 2>/dev/null | tail -30
        echo "--- last logcat lines (proot/QQ) ---"
        logcat -d -t 200 2>/dev/null | grep -aiE "proot|opt/QQ|linker|libnapcat" | tail -15
    } > $OUT 2>&1
    ls -t /data/local/tmp/napcat_crash_*.log 2>/dev/null | tail -n +6 | while read f; do rm -f "$f"; done
    log "snapshot saved -> $OUT"
}

restart_napcat() {
    # 原子锁：watchdog 和手动「重启 NapCat」同时进来会互相杀进程/叠实例
    # 锁超过 5 分钟视为僵死，自动清掉（否则会像 10-27 那样永久卡住）
    if [ -d /data/local/tmp/.napcat.lock ]; then
        LOCK_AGE=$(( $(date +%s) - $(stat -c %Y /data/local/tmp/.napcat.lock 2>/dev/null || echo 0) ))
        if [ "$LOCK_AGE" -gt 300 ]; then
            rm -rf /data/local/tmp/.napcat.lock
            log "stale napcat lock (${LOCK_AGE}s) removed"
        fi
    fi
    if ! mkdir /data/local/tmp/.napcat.lock 2>/dev/null; then
        log "napcat restart skipped (another restart in progress)"
        return
    fi
    log "NapCat down (QQ process missing) -> restarting"
    snapshot_napcat
    # 先礼后兵：TERM 让 QQ 有机会把登录态写回磁盘，再 KILL
    pkill -TERM -f 'opt/QQ' 2>/dev/null
    sleep 3
    pkill -TERM -x proot 2>/dev/null
    pkill -TERM -x Xvfb 2>/dev/null
    sleep 4
    pkill -9 -x proot 2>/dev/null
    pkill -9 -x Xvfb 2>/dev/null
    pkill -9 -f 'opt/QQ' 2>/dev/null
    sleep 4
    setsid sh /data/local/tmp/napcat_quick.sh </dev/null > /dev/null 2>&1 &
    # NapCat needs ~60s to come up; wait before next checks
    sleep 75
    if ! pgrep -x proot > /dev/null 2>&1; then
        log "napcat launch FAILED (proot not running) - retrying once"
        setsid sh /data/local/tmp/napcat_quick.sh </dev/null > /dev/null 2>&1 &
        sleep 60
    fi
    rmdir /data/local/tmp/.napcat.lock 2>/dev/null
}

restart_bot() {
    # 原子锁：防止 watchdog 与手动重启同时拉起两个 bot 实例（会重复回复+卡顿）
    if ! mkdir /data/local/tmp/.bot.lock 2>/dev/null; then
        return
    fi
    log "qq_bot down -> restarting (root)"
    sh /data/local/tmp/start_bot.sh > /dev/null 2>&1
    sleep 5
    dedupe_bot
    rmdir /data/local/tmp/.bot.lock 2>/dev/null
}

dedupe_bot() {
    CNT=$(pgrep -f 'qq_bot[.]py' | wc -l)
    if [ "$CNT" -gt 1 ]; then
        FIRST=$(pgrep -f 'qq_bot[.]py' | head -1)
        for p in $(pgrep -f 'qq_bot[.]py'); do
            if [ "$p" != "$FIRST" ]; then
                kill -9 "$p" 2>/dev/null
            fi
        done
        log "duplicate bot instances: kept $FIRST, killed the rest (was $CNT)"
    fi
}

restart_webui() {
    log "webui down (8080 missing) -> restarting (root)"
    sh /data/local/tmp/start_webui.sh > /dev/null 2>&1
}

restart_clash() {
    log "Clash/VPN down -> restarting"
    # `am start` 只是把界面打开，VPN 并不会自己起来，必须点一下界面里的启动按钮。
    am force-stop com.github.metacubex.clash.meta > /dev/null 2>&1
    sleep 2
    am start -n com.github.metacubex.clash.meta/com.github.kr328.clash.MainActivityAlias > /dev/null 2>&1
    sleep 6
    if ! ifconfig tun0 > /dev/null 2>&1; then
        # 主开关（1080x1920 下的“点此启动”位置；点偏了也不会造成损害）
        input tap 615 524 > /dev/null 2>&1
        sleep 4
    fi
    if ! ifconfig tun0 > /dev/null 2>&1; then
        input tap 615 448 > /dev/null 2>&1
        sleep 4
    fi
    if ifconfig tun0 > /dev/null 2>&1; then
        log "Clash VPN is up (tun0)"
    else
        log "Clash VPN still down after retry"
    fi
}

# QQ / 腾讯域名强制直连：订阅每天更新会覆盖配置，缺了就补上并重载
ensure_direct_rules() {
    [ -f /data/local/tmp/.no_touch_clash ] && return 0
    # 10 分钟内最多重载一次，避免规则写不进去时反复重启 Clash
    STAMP=/data/local/tmp/.clash_rules_stamp
    NOW=$(date +%s)
    LAST=$(cat $STAMP 2>/dev/null || echo 0)
    [ $((NOW - LAST)) -lt 600 ] && return
    CFG=$(ls /data/data/com.github.metacubex.clash.meta/files/imported/*/config.yaml 2>/dev/null | head -1)
    [ -z "$CFG" ] && return
    MISSING=""
    for d in qq.com tencent.com gtimg.com qpic.cn tencent-cloud.com qcloud.com myqcloud.com deepseek.com; do
        if ! grep -q "DOMAIN-SUFFIX,$d,DIRECT" "$CFG" 2>/dev/null; then
            MISSING="$MISSING $d"
        fi
    done
    if [ -n "$MISSING" ]; then
        echo "$NOW" > $STAMP
        cp -f "$CFG" "$CFG.bak.$(date +%s)" 2>/dev/null
        for d in $MISSING; do
            sed -i "/^rules:/a\\    - 'DOMAIN-SUFFIX,$d,DIRECT'" "$CFG"
        done
        log "added DIRECT rules for:$MISSING -> reloading Clash"
        restart_clash
    fi
}

log "=== watchdog started ==="

RULE_TICK=0
NAPCAT_MISS=0

clean_jm_cache() {
    JM=/data/data/com.termux/files/home/jm
    [ -d "$JM" ] || return 0
    SZ=$(du -sm "$JM" 2>/dev/null | cut -f1)
    [ -z "$SZ" ] && SZ=0
    if [ "$SZ" -gt 3000 ]; then
        rm -rf "$JM"/* 2>/dev/null
        log "jm cache ${SZ}MB > 3GB -> cleared all"
    else
        N=$(find "$JM" -mindepth 1 -maxdepth 1 -type d -mtime +2 2>/dev/null | wc -l)
        if [ "$N" -gt 0 ]; then
            find "$JM" -mindepth 1 -maxdepth 1 -type d -mtime +2 -exec rm -rf {} + 2>/dev/null
            log "jm cache: removed $N old album(s) (${SZ}MB before)"
        fi
    fi
    sync
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null
    log "page cache dropped, mem: $(free -m | awk 'NR==2{print $7"MB free"}')"
}

while true; do
    # SELinux must stay permissive for Termux -> NapCat socket access
    if [ "$(getenforce)" != "Permissive" ]; then
        log "SELinux was $(getenforce) -> set Permissive"
        setenforce 0
    fi

    # 0. 给 QQ 相关进程加 OOM 保护（每轮刷新，进程重启后依然生效）
    protect_oom

    # 1. NapCat container: restart only when the container / WebUI is really gone.
    #    连续 2 轮(≈60s)都缺才动手：手动重启/开局那 60 秒不该被 watchdog 插一脚，
    #    否则两边同时 pkill 会把容器叠起来。
    if [ ! -f /data/local/tmp/.no_napcat ] && { ! pgrep -x proot > /dev/null 2>&1 || ! tcp_ok 6099; }; then
        NAPCAT_MISS=$((NAPCAT_MISS + 1))
        if [ "$NAPCAT_MISS" -ge 2 ]; then
            restart_napcat
            NAPCAT_MISS=0
        fi
        LOGOUT_COUNT=0
    else
        NAPCAT_MISS=0
        if ! tcp_ok 3001; then
            LOGOUT_COUNT=$((LOGOUT_COUNT + 1))
            # 掉登录后先自己试着重登：连续 3 轮(≈90s)都缺 3001 就重启容器走快速登录
            if [ "$LOGOUT_COUNT" -ge 3 ]; then
                NOW=$(date +%s)
                LAST=$(cat /data/local/tmp/.relogin_stamp 2>/dev/null || echo 0)
                if [ $((NOW - LAST)) -gt 600 ]; then
                    echo "$NOW" > /data/local/tmp/.relogin_stamp
                    log "3001 missing 3 ticks -> auto restart NapCat to try quick-login"
                    restart_napcat
                    LOGOUT_COUNT=0
                    continue
                fi
            fi
            if [ "$LOGOUT_COUNT" = "4" ] && [ "$LOGOUT_NOTIFIED" != "1" ]; then
                log "NapCat alive but 3001 missing: QQ is logged out -> QR scan needed"
                notify "QQ 掉登录了，需要扫码" "NapCat 还在跑，但 QQ 登录态失效。打开 PhoneAgent App 点「二维码」扫码即可恢复。反复重登容易被风控，建议先静置一会儿。"
                LOGOUT_NOTIFIED=1
            fi
        else
            if [ "$LOGOUT_NOTIFIED" = "1" ]; then
                log "QQ is back online (3001 up)"
                LOGOUT_NOTIFIED=0
            fi
            LOGOUT_COUNT=0
        fi
    fi

    # 2. QQ bot process
    if ! pgrep -f 'qq_bot[.]py' > /dev/null 2>&1; then
        restart_bot
    else
        dedupe_bot
    fi

    # 3. WebUI on 8080
    if ! tcp_ok 8080; then
        restart_webui
    fi

    # 4. Clash proxy —— 有 /data/local/tmp/.no_clash 标记时完全不管（主人要求临时不用代理）
    if [ ! -f /data/local/tmp/.no_clash ] && [ ! -f /data/local/tmp/.no_touch_clash ]; then
        if ! pgrep -f 'com.github.metacubex.clash.meta' > /dev/null 2>&1 || ! ifconfig tun0 > /dev/null 2>&1; then
            restart_clash
        fi
    fi

    # 4.6 直连规则（DeepSeek 变慢、QQ 被风控都跟它有关）；每 20 轮查一次
    RULE_TICK=$((RULE_TICK + 1))
    if [ $((RULE_TICK % 20)) = 0 ]; then
        ensure_direct_rules
    fi

    # 4.5 WiFi 掉线自动重连（没有网 = AI 完全不可用）
    if ! ip addr show wlan0 2>/dev/null | grep -q 'inet '; then
        log "WiFi offline -> reconnecting $WIFI_SSID"
        cmd wifi connect-network "$WIFI_SSID" open > /dev/null 2>&1
        sleep 12
        if ip addr show wlan0 2>/dev/null | grep -q 'inet '; then
            log "WiFi reconnected"
            notify "WiFi 已自动重连" "网络断开后已自动连回 $WIFI_SSID"
        else
            log "WiFi reconnect failed"
            notify "WiFi 重连失败" "尝试连接 $WIFI_SSID 失败，AI 现在无法联网。请手动检查网络。"
        fi
    fi

    # 5. daily cleanup: delete files older than 3 days (once per day)
    TODAY=$(date +%Y%m%d)
    if [ "$(cat /data/local/tmp/.last_cleanup 2>/dev/null)" != "$TODAY" ]; then
        echo "$TODAY" > /data/local/tmp/.last_cleanup
        log "daily cleanup (files older than 3 days)"
        sh /data/local/tmp/cleanup_3days.sh 3 > /dev/null 2>&1
        clean_jm_cache
    fi

    sleep 30
done
