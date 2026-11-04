#!/system/bin/sh
# Start NapCat directly (no screen) with output redirected.
# -q <uin> 走“快速登录”，避免每次重启都要扫码（二维码登录最容易触发风控）
BIN=/data/data/com.astrbot.astrbot_android/files/usr/bin
UBUNTU_PATH=/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu
TMPDIR=/data/data/com.astrbot.astrbot_android/files/usr/tmp
QQ_UIN=1000000
export LD_LIBRARY_PATH=$BIN
export PROOT_LOADER=$BIN/loader
export PROOT_TMP_DIR=$TMPDIR
# 保留“上一次运行”的日志：QQ 崩溃/被踢的证据在重启时不会被 > 清掉
RUNLOG=$UBUNTU_PATH/root/napcat_run.log
if [ -f "$RUNLOG" ]; then
  cp -f "$RUNLOG" "$UBUNTU_PATH/root/napcat_run.prev.log" 2>/dev/null
fi
cd /data/data/com.astrbot.astrbot_android/files/home
exec $BIN/proot -0 -r $UBUNTU_PATH --link2symlink \
  -b /dev -b /proc -b /sys -b /dev/pts \
  -b $TMPDIR:$TMPDIR -b $TMPDIR:/dev/shm \
  -b /storage/emulated/0:/sdcard \
  -w /root \
  /usr/bin/env -i HOME=/root TERM=xterm-256color LANG=en_US.UTF-8 TZ=Asia/Shanghai \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /bin/bash -lc "cd /root && exec bash launcher.sh -q $QQ_UIN > /root/napcat_run.log 2>&1"
