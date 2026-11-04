#!/system/bin/sh
# 可靠启动 qq_bot（root）
pkill -9 -f "qq_bot[.]py" 2>/dev/null
sleep 2
setsid sh /data/local/tmp/run_qq_root.sh </dev/null >>/data/data/com.termux/files/home/aibot/qq_bot.log 2>&1 &
sleep 2
echo "qq_bot launched"
