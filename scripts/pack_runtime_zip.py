"""把 runtime 的 files/ 树打成 runtime.zip（保留符号链接与权限位）。

App 侧的 RuntimeManager 会用 ZipInputStream 解压，然后靠
restoreSymlinks() 把符号链接重建出来（因为 Android 读不到 zip 里的 S_IFLNK）。

用法：
    python pack_runtime_zip.py --files build/runtime_build/files --out build/runtime.zip
"""
import argparse
import os
import stat
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", default="build/runtime_build/files",
                    help="runtime 的 files 目录（里面是 usr/…）")
    ap.add_argument("--out", default="build/runtime.zip")
    ap.add_argument("--level", type=int, default=6, help="压缩级别 1~9")
    a = ap.parse_args()

    files = os.path.abspath(a.files)
    out = os.path.abspath(a.out)
    if not os.path.isdir(files):
        print("没有这个目录:", files)
        sys.exit(1)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    count = links = total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=a.level) as z:
        for root, dirs, names in os.walk(files):
            for name in names:
                p = os.path.join(root, name)
                arc = os.path.relpath(p, files).replace("\\", "/")
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if stat.S_ISLNK(st.st_mode):
                    zi = zipfile.ZipInfo(arc)
                    zi.create_system = 3
                    zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(zi, os.readlink(p))
                    links += 1
                    count += 1
                    continue
                zi = zipfile.ZipInfo(arc)
                zi.create_system = 3
                zi.external_attr = (stat.S_IFREG | (st.st_mode & 0o777)) << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                data = open(p, "rb").read()
                z.writestr(zi, data)
                count += 1
                total += len(data)

    size = os.path.getsize(out)
    print("打包完成：%d 个条目（其中软链 %d），原始 %.1f MB -> zip %.1f MB"
          % (count, links, total / 1048576, size / 1048576))

    # 抽查关键文件
    with zipfile.ZipFile(out) as z:
        for probe in ("usr/bin/python3", "usr/lib/libssl.so.3",
                      "usr/lib/python3.14/os.py", "usr/etc/tls/cert.pem"):
            hit = probe in z.namelist()
            print("  %-32s %s" % (probe, "有" if hit else "缺"))


if __name__ == "__main__":
    main()
