#!/system/bin/sh
# 可靠启动 webui（root）
pkill -9 -f "webui[.]py" 2>/dev/null
sleep 2
setsid sh /data/local/tmp/run_webui_root.sh </dev/null >>/data/local/tmp/webui.log 2>&1 &
sleep 2
echo "webui launched"
