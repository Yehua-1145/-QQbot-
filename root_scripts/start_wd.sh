#!/system/bin/sh
# 启动 watchdog（脱离当前 shell，避免占住 adb 的 stdio）
pkill -9 -f "watchdog[.]sh" 2>/dev/null
sleep 2
setsid sh /data/local/tmp/watchdog.sh </dev/null >>/data/local/tmp/watchdog_run.log 2>&1 &
sleep 1
echo "watchdog launched"

# 闲时图库预取（0-6 点）
if ! pgrep -f prefetch_loop >/dev/null 2>&1; then
  setsid sh /data/data/com.termux/files/home/aibot/prefetch_loop.sh </dev/null >>/data/data/com.termux/files/home/aibot/prefetch_loop.log 2>&1 &
fi

# QQ 保活循环
if ! pgrep -f keepalive_loop >/dev/null 2>&1; then
  setsid sh /data/data/com.termux/files/home/aibot/keepalive_loop.sh </dev/null >>/data/data/com.termux/files/home/aibot/keepalive.log 2>&1 &
fi
# 防休眠设置（重启会失效，重新应用）
sh /data/local/tmp/nosleep.sh >/dev/null 2>&1

# 时段调优（day / quiet 自动切换）
if ! pgrep -f tune_loop >/dev/null 2>&1; then
  setsid sh /data/local/tmp/tune_loop.sh </dev/null >>/data/local/tmp/tune.log 2>&1 &
fi
# 确保 webui 在跑（用真实 TCP 探测，因为本机 netstat 看不到端口）
if ! /data/data/com.termux/files/usr/bin/python3 -c "import socket,sys
s=socket.socket(); s.settimeout(2)
try:
    s.connect(('127.0.0.1',8080)); sys.exit(0)
except Exception:
    sys.exit(1)" 2>/dev/null; then
  echo "[$(date)] webui 未监听 8080 -> 启动" >> /data/local/tmp/boot_start.log
  sh /data/local/tmp/start_webui.sh
  sleep 8
fi