#!/data/data/com.termux/files/usr/bin/bash
# 启动 PhoneAgent 本地控制台
export HOME=/data/data/com.termux/files/home
export PATH=/data/data/com.termux/files/usr/bin:$PATH
export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib
cd /data/data/com.termux/files/home/aibot || exit 1
exec /data/data/com.termux/files/usr/bin/python3 /data/data/com.termux/files/home/aibot/console.py "$@"
