#!/system/bin/sh
# PhoneAgent boot script - starts NapCat + WebUI + QQ bot on boot
# Runs as root via Magisk /data/adb/service.d/

LOG=/data/local/tmp/phoneagent_boot.log
echo "=== PhoneAgent boot $(date) ===" >> $LOG

# SELinux permissive (required for Termux -> NapCat socket access)
setenforce 0
echo "SELinux=$(getenforce)" >> $LOG

# wait for system boot
sleep 90

# 1. Start NapCat (QQ) if not running
if pgrep -f /opt/QQ > /dev/null 2>&1; then
    echo "NapCat already running" >> $LOG
else
    echo "starting NapCat..." >> $LOG
    su -c "setsid sh /data/local/tmp/napcat_noscreen.sh > /dev/null 2>&1 &"
fi

# wait for NapCat WebSocket (3001) up to 90s
i=0
while [ $i -lt 18 ]; do
    if netstat -tln 2>/dev/null | grep -q ':3001'; then
        echo "NapCat WS ready" >> $LOG
        break
    fi
    sleep 5
    i=$((i+1))
done

# 2. Start Termux services (webui + qq_bot) as Termux user
run-as com.termux /data/data/com.termux/files/usr/bin/bash -c 'cd /data/data/com.termux/files/home/aibot && nohup bash run_webui.sh > webui.log 2>&1 &'
echo "webui started" >> $LOG

run-as com.termux /data/data/com.termux/files/usr/bin/bash -c 'cd /data/data/com.termux/files/home/aibot && nohup bash run_qq.sh > qq_bot.log 2>&1 &'
echo "qq_bot started" >> $LOG

echo "=== PhoneAgent boot done ===" >> $LOG
