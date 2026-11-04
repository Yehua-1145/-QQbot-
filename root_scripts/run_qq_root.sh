#!/system/bin/sh
# 以 root 启动 qq_bot（root 有 inet 权限，能连 NapCat 的 3001）
export HOME=/data/data/com.termux/files/home
export PATH=/data/data/com.termux/files/usr/bin:$PATH
export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib
cd /data/data/com.termux/files/home/aibot 2>/dev/null || cd / 2>/dev/null || true
exec /data/data/com.termux/files/usr/bin/python3 /data/data/com.termux/files/home/aibot/qq_bot.py
