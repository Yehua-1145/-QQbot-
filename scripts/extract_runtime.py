"""修正解包路径：Termux 的 deb 里路径是 data/data/com.termux/files/usr/...
我们想要 files/usr/... ，所以剥掉前缀。顺便清掉解错的位置。
"""
import os
import shutil
import sys
import tarfile

sys.stdout.reconfigure(encoding="utf-8")

OUT = r"D:\runtime_build"
FILES = os.path.join(OUT, "files")
CACHE = os.path.join(OUT, "debs")

# 清掉之前解错的结构
shutil.rmtree(FILES, ignore_errors=True)
os.makedirs(FILES, exist_ok=True)

TARGET = "data/data/com.termux/files/"


def extract_deb(deb_path, dest):
    data = open(deb_path, "rb").read()
    pos = 8
    body = None
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        name = hdr[0:16].decode("ascii", "replace").strip()
        size = int(hdr[48:58].decode("ascii").strip() or 0)
        if name.startswith("data.tar"):
            body = data[pos + 60:pos + 60 + size]
            break
        pos += 60 + size + (size % 2)
    if body is None:
        return 0
    import io

    n = 0
    with tarfile.open(fileobj=io.BytesIO(body)) as tf:
        for m in tf.getmembers():
            name = m.name[2:] if m.name.startswith("./") else m.name
            if not name.startswith(TARGET):
                continue
            rel = name[len(TARGET):]
            if not rel or rel == ".":
                continue
            m.name = rel
            try:
                tf.extract(m, dest, filter="data")
                n += 1
            except TypeError:
                tf.extract(m, dest)
                n += 1
            except Exception:
                pass
    return n


total = 0
for fn in sorted(os.listdir(CACHE)):
    if not fn.endswith(".deb"):
        continue
    try:
        n = extract_deb(os.path.join(CACHE, fn), FILES)
        total += n
        print("  %-40s %4d 个文件" % (fn, n), flush=True)
    except Exception as e:
        print("  失败 %s: %s" % (fn, str(e)[:70]), flush=True)

print("总文件:", total)
for probe in ("usr/bin/python3", "usr/bin/proot", "usr/lib/libpython3.14.so",
              "usr/lib/libssl.so.3", "usr/etc/tls/cert.pem"):
    p = os.path.join(FILES, probe)
    print("  %-32s %s" % (probe, "有" if os.path.exists(p) else "没有"))
