"""把 Termux 的 python 运行时（含依赖）下载并解包到本地 runtime 目录。

产物结构：
  build_runtime/files/usr/bin/python3 ...
  build_runtime/files/usr/lib/*.so
用来塞进 APK 的 assets/runtime.tar.gz
"""
import gzip
import io
import os
import re
import sys
import tarfile
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://packages.termux.dev/apt/termux-main/"
DIST = "dists/stable/main/binary-aarch64/"
OUT = r"D:\runtime_build"
FILES = os.path.join(OUT, "files")
CACHE = os.path.join(OUT, "debs")

# 要装什么：python 为主，proot 用来起容器
ROOTS = ["python", "proot", "ca-certificates", "openssl", "curl"]
# 明确不要的（体积大且用不到）
SKIP = {"python-pip", "python-ensurepip-wheels", "clang", "llvm", "lld",
        "libcompiler-rt", "make", "pkg-config", "gdbm", "libandroid-posix-semaphore"}


def fetch(url, dst=None, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "Botagent"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if dst:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(data)
    return data


def load_index():
    print("拉取包索引…", flush=True)
    raw = fetch(BASE + "dists/stable/main/binary-aarch64/Packages.gz")
    text = gzip.decompress(raw).decode("utf-8", "replace")
    pkgs = {}
    cur = {}
    for line in text.splitlines():
        if not line.strip():
            if cur.get("Package"):
                pkgs[cur["Package"]] = cur
            cur = {}
            continue
        if line[0] in " \t":
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip()
    if cur.get("Package"):
        pkgs[cur["Package"]] = cur
    print("索引里有 %d 个包" % len(pkgs), flush=True)
    return pkgs


def deps_of(pkg):
    d = pkg.get("Depends", "") or ""
    d = d.replace("|", ",")
    alts = []
    for item in d.split(","):
        item = item.strip()
        if not item:
            continue
        # 取每个依赖的包名（去掉版本约束）
        name = re.split(r"[ (:]", item)[0].strip()
        if name:
            alts.append(name)
    return alts


def resolve(index, roots):
    """广度优先解析依赖；同名依赖取第一个可用（简单策略）。"""
    need, queue, seen = [], list(roots), set()
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        if name not in index:
            print("  跳过不存在的包:", name, flush=True)
            continue
        if name in SKIP:
            print("  按规则跳过:", name, flush=True)
            continue
        need.append(name)
        for d in deps_of(index[name]):
            if d not in seen:
                queue.append(d)
    return need


def deb_extract(deb_path, dest):
    """解 .deb（ar 包里有 data.tar.xz）到 dest。"""
    import lzma
    data = open(deb_path, "rb").read()
    if not data.startswith(b"!<arch>\n"):
        raise RuntimeError("不是 ar 包: " + deb_path)
    pos = 8
    data_tar = None
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        name = hdr[0:16].decode("ascii", "replace").strip()
        size = int(hdr[48:58].decode("ascii").strip() or 0)
        body = data[pos + 60:pos + 60 + size]
        if name.startswith("data.tar"):
            data_tar = body
            break
        pos += 60 + size + (size % 2)
    if data_tar is None:
        raise RuntimeError("没找到 data.tar: " + deb_path)
    bio = io.BytesIO(data_tar)
    if data_tar[:2] == b"\x1d\x8b" or data_tar[:6] == b"\xfd7zXZ\x00":
        pass
    with tarfile.open(fileobj=bio) as tf:
        for m in tf.getmembers():
            if m.name.startswith("./"):
                m.name = m.name[2:]
            tf.extract(m, dest)


def main():
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(FILES, exist_ok=True)
    index = load_index()
    pkgs = resolve(index, ROOTS)
    print("需要 %d 个包：%s" % (len(pkgs), ", ".join(pkgs)), flush=True)

    total = 0
    for name in pkgs:
        pkg = index[name]
        fn = pkg["Filename"].split("/")[-1]
        dst = os.path.join(CACHE, fn)
        if not os.path.isfile(dst):
            try:
                fetch(BASE + pkg["Filename"], dst)
            except Exception as e:
                print("  下载失败 %s: %s" % (name, str(e)[:60]), flush=True)
                continue
        sz = os.path.getsize(dst)
        total += sz
        print("  %-22s %6.1f MB" % (name, sz / 1048576), flush=True)
        try:
            deb_extract(dst, FILES)
        except Exception as e:
            print("   解包失败: %s" % str(e)[:80], flush=True)

    print("\n解包完成，总下载 %.1f MB" % (total / 1048576), flush=True)
    p = os.path.join(FILES, "usr", "bin", "python3")
    print("python3 在:", os.path.isfile(p) or os.path.islink(p))
    print("proot 在:", os.path.isfile(os.path.join(FILES, "usr", "bin", "proot")))


if __name__ == "__main__":
    main()
