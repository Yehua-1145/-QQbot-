#!/system/bin/sh
# 开机自启（Magisk service.d）
# 关键：手机刚开机时 /data 还是加密的（FBE），Termux 的目录不存在，
# 这时候启动 webui/bot 会一路 cd: No such file or directory。
# 所以先等"用户解锁 + 目录可见"，再拉起全套。
echo "[$(date)] boot hook start" >> /data/local/tmp/boot_start.log

A=/data/data/com.termux/files/home/aibot
i=0
while [ $i -lt 180 ]; do
  if [ -d "$A" ] && [ -f "$A/qq_bot.py" ]; then
    break
  fi
  sleep 10
  i=$((i + 1))
done

if [ ! -f "$A/qq_bot.py" ]; then
  echo "[$(date)] WAIT TIMEOUT: $A 一直不可见（可能一直没解锁）" >> /data/local/tmp/boot_start.log
  exit 0
fi

echo "[$(date)] data ready after ${i}0s -> starting stack" >> /data/local/tmp/boot_start.log
sh /data/local/tmp/start_wd.sh >> /data/local/tmp/boot_start.log 2>&1
sleep 3
sh /data/local/tmp/nosleep.sh >> /data/local/tmp/boot_start.log 2>&1
echo "[$(date)] boot done" >> /data/local/tmp/boot_start.log