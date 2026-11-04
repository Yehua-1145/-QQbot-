#!/system/bin/sh
A=/data/data/com.termux/files/home/aibot
echo "=== stop ==="
for p in $(pgrep -f "qq_bot[.]py"); do echo "kill $p"; kill -9 $p 2>&1; done
sleep 2
pgrep -f "qq_bot[.]py" || echo "no qq_bot running"
echo "=== start ==="
cd $A 2>/dev/null || cd /
setsid sh /data/local/tmp/run_qq_root.sh </dev/null >>$A/qq_bot.log 2>&1 &
sleep 4
echo "=== check ==="
pgrep -f "qq_bot[.]py" || echo "NOT RUNNING"
tail -5 $A/qq_bot.log
