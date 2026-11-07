"""把 websocket-client 装进 runtime 的 site-packages，然后打包成 runtime.tar.gz"""
import io
import os
import sys
import tarfile
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

FILES = r"D:\runtime_build\files"
SITE = os.path.join(FILES, "usr", "lib", "python3.14", "site-packages")
OUT_TGZ = r"D:\runtime_build\runtime.tar.gz"

os.makedirs(SITE, exist_ok=True)


def install_wheel(name, version):
    """从 PyPI 下纯 python wheel 并解到 site-packages。"""
    url = "https://pypi.org/pypi/%s/%s/json" % (name, version)
    req = urllib.request.Request(url, headers={"User-Agent": "Botagent"})
    import json
    meta = json.loads(urllib.request.urlopen(req, timeout=60).read())
    whl = None
    for f in meta["urls"]:
        if f["filename"].endswith(".whl") and "py3-none-any" in f["filename"]:
            whl = f["url"]
            break
    if not whl:
        for f in meta["urls"]:
            if f["filename"].endswith(".whl"):
                whl = f["url"]
                break
    if not whl:
        print("  没找到 wheel:", name)
        return False
    print("  %s <- %s" % (name, whl.split("/")[-1]))
    data = urllib.request.urlopen(urllib.request.Request(whl, headers={"User-Agent": "Botagent"}),
                                  timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        n = 0
        for m in z.namelist():
            if m.endswith("/"):
                continue
            if m.startswith(("websocket/", "websocket_client-")):
                z.extract(m, SITE)
                n += 1
    print("    解出 %d 个文件" % n)
    return True


print("装 websocket-client…")
install_wheel("websocket-client", "1.9.0")

# 检查
print("site-packages 内容:", os.listdir(SITE)[:6])

print("\n打包 runtime.tar.gz…")
total = 0
with tarfile.open(OUT_TGZ, "w:gz", compresslevel=6) as tf:
    for root, dirs, files in os.walk(FILES):
        for d in dirs:
            p = os.path.join(root, d)
            arc = os.path.relpath(p, FILES)
            ti = tarfile.TarInfo(arc)
            ti.type = tarfile.DIRTYPE
            ti.mode = 0o755
            tf.addfile(ti)
        for f in files:
            p = os.path.join(root, f)
            arc = os.path.relpath(p, FILES)
            try:
                st = os.lstat(p)
                ti = tarfile.TarInfo(arc)
                ti.mode = st.st_mode & 0o777 or 0o644
                if os.path.islink(p):
                    ti.type = tarfile.SYMTYPE
                    ti.linkname = os.readlink(p)
                    tf.addfile(ti)
                    continue
                ti.size = st.st_size
                tf.addfile(ti, open(p, "rb"))
                total += st.st_size
            except Exception:
                pass

print("原始 %.1f MB -> 压缩后 %.1f MB"
      % (total / 1048576, os.path.getsize(OUT_TGZ) / 1048576))
