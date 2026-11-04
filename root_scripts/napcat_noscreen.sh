#!/system/bin/sh
# Start NapCat directly (no screen) with output redirected.
BIN=/data/data/com.astrbot.astrbot_android/files/usr/bin
UBUNTU_PATH=/data/data/com.astrbot.astrbot_android/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu
TMPDIR=/data/data/com.astrbot.astrbot_android/files/usr/tmp
export LD_LIBRARY_PATH=$BIN
export PROOT_LOADER=$BIN/loader
export PROOT_TMP_DIR=$TMPDIR
cd /data/data/com.astrbot.astrbot_android/files/home
exec $BIN/proot -0 -r $UBUNTU_PATH --link2symlink \
  -b /dev -b /proc -b /sys -b /dev/pts \
  -b $TMPDIR:$TMPDIR -b $TMPDIR:/dev/shm \
  -b /storage/emulated/0:/sdcard \
  -w /root \
  /usr/bin/env -i HOME=/root TERM=xterm-256color LANG=en_US.UTF-8 TZ=Asia/Shanghai \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /bin/bash -lc "cd /root && exec bash launcher.sh > /root/napcat_run.log 2>&1"
