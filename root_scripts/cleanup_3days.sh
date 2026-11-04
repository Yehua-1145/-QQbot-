#!/system/bin/sh
# PhoneAgent 三天自动清理：删除 3 天前的图片/压缩包/截图，避免占满存储。
# 用法：sh cleanup_3days.sh [天数]   （默认 3 天）

DAYS=${1:-3}
LOG=/data/local/tmp/cleanup.log
JM_DIR=/data/data/com.termux/files/home/jm
EH_DIR=/data/data/com.termux/files/home/eh
DL=/sdcard/Download

echo "=== cleanup start $(date) (older than ${DAYS}d) ===" >> $LOG

freed_before=$(df /data | tail -1 | awk '{print $4}')

# 1) 图源B 下载的图片目录
if [ -d "$JM_DIR" ]; then
    find "$JM_DIR" -type f -mtime +$DAYS -delete 2>/dev/null
    find "$JM_DIR" -type d -empty -delete 2>/dev/null
fi

# 2) 图源A 下载的图片
if [ -d "$EH_DIR" ]; then
    find "$EH_DIR" -type f -mtime +$DAYS -delete 2>/dev/null
fi

# 3) /sdcard/Download 里的压缩包 & 图片（保留 apk）
find "$DL" -maxdepth 1 -type f \( -name '*.zip' -o -name '*.webp' -o -name '*.jpg' -o -name '*.png' \) -mtime +$DAYS -delete 2>/dev/null

# 4) 手机截图缓存（agent_shot_*、qr_*、panel 等）
find /sdcard -maxdepth 2 -type f \( -name 'agent_shot_*' -o -name 'qr_*.png' -o -name 'eh*.png' -o -name 'clash*.png' \) -mtime +$DAYS -delete 2>/dev/null

# 5) Termux 临时文件
find /data/data/com.termux/files/home -maxdepth 2 -type f \( -name '*.log' -o -name 'bot.log' \) -mtime +$DAYS -delete 2>/dev/null

freed_after=$(df /data | tail -1 | awk '{print $4}')
echo "before=${freed_before}K after=${freed_after}K (freed $(( (freed_after - freed_before) / 1024 ))M)" >> $LOG
echo "=== cleanup done $(date) ===" >> $LOG
