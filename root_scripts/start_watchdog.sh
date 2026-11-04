#!/system/bin/sh
# PhoneAgent watchdog - keeps NapCat, QQ bot and WebUI alive.
# Runs as root. Restarts anything that died.

LOG=/data/local/tmp/watchdog.log
AIBOT=/data/data/com.termux/files/home/aibot
TERMUX_BASH=/data/data/com.termux/files/usr/bin/bash

log() { echo "[$(date '+%m-%d %H:%M:%S')] $1" >> $LOG; }

restart_napcat() {
    log "NapCat down (QQ process missing) -> restarting"
    su -c "pkill -9 -f /opt/QQ 2>/dev/null; pkill -9 -f Xvfb 2>/dev/null; pkill -9 -f proot 2>/dev/null; pkill -9 -f screen 2>/dev/null"
    sleep 3
    su -c "setsid sh /data/local/tmp/napcat_noscreen.sh > /dev/null 2>&1 &"
    # NapCat needs ~60s to come up; wait before next checks
    sleep 75
}

restart_bot() {
    log "qq_bot down -> restarting"
    run-as com.termux $TERMUX_BASH -c "cd $AIBOT && nohup bash run_qq.sh > qq_bot.log 2>&1 &"
}

restart_webui() {
    log "webui down (8080 missing) -> restarting"
    run-as com.termux $TERMUX_BASH -c "cd $AIBOT && nohup bash run_webui.sh > webui.log 2>&1 &"
}

restart_clash() {
    log "Clash down -> restarting"
    am start -n com.github.metacubex.clash.meta/com.github.kr328.clash.MainActivityAlias > /dev/null 2>&1
    sleep 12
    # if the VPN still is not up, try to toggle the service through the app again
    if ! ifconfig tun0 > /dev/null 2>&1; then
        am force-stop com.github.metacubex.clash.meta
        sleep 2
        am start -n com.github.metacubex.clash.meta/com.github.kr328.clash.MainActivityAlias > /dev/null 2>&1
        sleep 12
    fi
}

log "=== watchdog started ==="

while true; do
    # SELinux must stay permissive for Termux -> NapCat socket access
    if [ "$(getenforce)" != "Permissive" ]; then
        log "SELinux was $(getenforce) -> set Permissive"
        setenforce 0
    fi

    # 1. NapCat / QQ - check the QQ process itself, NOT port 3001
    #    (3001 only opens after QQ login, so it is not a liveness signal)
    if ! pgrep -f '/opt/QQ' > /dev/null 2>&1; then
        restart_napcat
    fi

    # 2. QQ bot process
    if ! pgrep -f qq_bot.py > /dev/null 2>&1; then
        restart_bot
    fi

    # 3. WebUI on 8080
    if ! netstat -tln 2>/dev/null | grep -q ':8080'; then
        restart_webui
    fi

    # 4. Clash proxy (must keep tun0 up for 图源A access)
    if ! pgrep -f 'com.github.metacubex.clash.meta' > /dev/null 2>&1 || ! ifconfig tun0 > /dev/null 2>&1; then
        restart_clash
    fi

    sleep 30
done
