"""把 runtime 的 files/ 打成 zip（保留 unix 权限位），给 Android 的 ZipInputStream 用。"""
import os
import stat
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

FILES = r"D:\runtime_build\files"
OUT = r"D:\runtime_build\runtime.zip"

count = 0
total = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, dirs, files in os.walk(FILES):
        for name in files:
            p = os.path.join(root, name)
            arc = os.path.relpath(p, FILES).replace("\\", "/")
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode):
                # 符号链接：目标写进内容，标记 S_IFLNK
                try:
                    target = os.readlink(p)
                except OSError:
                    continue
                zi = zipfile.ZipInfo(arc)
                zi.create_system = 3
                zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(zi, target)
                count += 1
                continue
            mode = st.st_mode & 0o777
            zi = zipfile.ZipInfo(arc)
            zi.create_system = 3
            zi.external_attr = (stat.S_IFREG | mode) << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            with open(p, "rb") as f:
                data = f.read()
            z.writestr(zi, data)
            count += 1
            total += len(data)
            if count % 500 == 0:
                print("  ...%d 个文件" % count, flush=True)

print("打包完成：%d 个文件，原始 %.1f MB -> zip %.1f MB"
      % (count, total / 1048576, os.path.getsize(OUT) / 1048576))

# 抽查几个关键文件
with zipfile.ZipFile(OUT) as z:
    for probe in ("usr/bin/python3", "usr/bin/proot", "usr/lib/libssl.so.3"):
        try:
            zi = z.getinfo(probe)
            mode = (zi.external_attr >> 16) & 0o777
            print("  %-24s %6d 字节  权限 %o" % (probe, zi.file_size, mode))
        except KeyError:
            print("  %-24s 没有" % probe)
