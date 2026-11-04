#!/system/bin/sh
# 防止夜里被系统省电掐网/杀进程（root 执行一次即可，重启后由 start_wd.sh 再跑）
set -x 2>/dev/null

echo "=== 1) 电池优化白名单（Doze 不冻结这两个 App）==="
for P in com.termux com.astrbot.astrbot_android; do
  dumpsys deviceidle whitelist +$P 2>/dev/null
  cmd deviceidle whitelist +$P 2>/dev/null
  am set-standby-bucket $P active 2>/dev/null
  cmd appops set $P RUN_IN_BACKGROUND allow 2>/dev/null
  cmd appops set $P RUN_ANY_IN_BACKGROUND allow 2>/dev/null
  cmd appops set $P WAKE_LOCK allow 2>/dev/null
done

echo "=== 2) WiFi 永不休眠 ==="
settings put global wifi_sleep_policy 2
settings put global wifi_scan_always_enabled 0
settings put global low_power 0 2>/dev/null
svc wifi enable

echo "=== 3) 尽量关掉 Doze 深度休眠（专用机可以激进）==="
dumpsys deviceidle disable 2>/dev/null
echo "deviceidle: $(dumpsys deviceidle get deep 2>/dev/null)"

echo "=== 4) 结果 ==="
dumpsys deviceidle whitelist 2>/dev/null | grep -E "termux|astrbot" || echo "(白名单读取失败，属正常)"
settings get global wifi_sleep_policy
echo DONE
