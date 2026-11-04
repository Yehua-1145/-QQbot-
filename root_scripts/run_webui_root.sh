#!/system/bin/sh
# 以 root 启动 webui（root 有 inet 权限，能 bind socket）
export HOME=/data/data/com.termux/files/home
export PATH=/data/data/com.termux/files/usr/bin:$PATH
export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib
cd /data/data/com.termux/files/home/aibot || exit 1
exec /data/data/com.termux/files/usr/bin/python3 /data/data/com.termux/files/home/aibot/webui.py
