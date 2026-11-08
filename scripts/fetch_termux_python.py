"""把 Termux 的 python 运行时（含依赖）下载并解包到本地目录。

产物：
    <out>/files/usr/bin/python3
    <out>/files/usr/lib/*.so
    <out>/files/usr/lib/python3.14/...
    <out>/debs/*.deb            （缓存，可删）

用法：
    python fetch_termux_python.py --out build/runtime_build
"""
import argparse
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

# 要装的包（python 为主，openssl 让 https 能用）
ROOTS = ["python", "ca-certificates", "openssl", "libsqlite", "libbz2", "liblzma",
         "libexpat", "libffi", "zlib", "ncurses", "readline", "libandroid-support"]

# 不要的（体积大，用不到）
SKIP = {"python-pip", "python-ensurepip-wheels", "clang", "llvm", "lld",
        "libcompiler-rt", "make", "pkg-config", "gdbm", "libandroid-posix-semaphore",
        "libc++"}


def fetch(url, dst=None, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": "Botagent"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if dst:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(data)
    return data


def load_index():
    print("拉取包索引…", flush=True)
    raw = fetch(BASE + DIST + "Packages.gz")
    text = gzip.decompress(raw).decode("utf-8", "replace")
    pkgs, cur = {}, {}
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


def deps_of(pkgs, name, seen=None):
    if seen is None:
        seen = set()
    if name in seen or name not in pkgs:
        return seen
    seen.add(name)
    for d in re.split(r"[,\s]+", pkgs[name].get("Depends", "")):
        d = d.split("(")[0].strip()
        d = d.split("|")[0].strip()
        if d and d not in SKIP:
            deps_of(pkgs, d, seen)
    return seen


def extract(deb_path, out_files):
    """deb = ar 归档，里面 data.tar.{xz,zst,gz} 才是文件。"""
    data = open(deb_path, "rb").read()
    if not data.startswith(b"!<arch>"):
        print("  不是 ar 归档:", deb_path)
        return 0
    pos, payload = 8, None
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        name = hdr[:16].decode("utf-8", "replace").strip()
        size = int(hdr[48:58].decode("utf-8", "replace").strip() or 0)
        body = data[pos + 60:pos + 60 + size]
        if name.startswith("data.tar"):
            payload = body
            break
        pos += 60 + size + (size % 2)
    if payload is None:
        return 0

    if name.endswith(".xz"):
        import lzma
        payload = lzma.decompress(payload)
    elif name.endswith(".zst"):
        try:
            import zstandard
            payload = zstandard.ZstdDecompressor().decompress(payload)
        except ImportError:
            print("  需要 zstandard 才能解 .zst：pip install zstandard")
            return 0
    elif name.endswith(".gz"):
        payload = gzip.decompress(payload)

    n = 0
    with tarfile.open(fileobj=io.BytesIO(payload)) as tf:
        for m in tf:
            p = m.name
            if p.startswith("./"):
                p = p[2:]
            p = p.replace("data/data/com.termux/files/", "")
            if not p or p in (".", "usr", "usr/"):
                continue
            dst = os.path.join(out_files, p)
            if m.isdir():
                os.makedirs(dst, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if m.issym():
                if os.path.lexists(dst):
                    os.remove(dst)
                try:
                    os.symlink(m.linkname, dst)
                except OSError:
                    pass
                n += 1
                continue
            if not m.isfile():
                continue
            with tf.extractfile(m) as src, open(dst, "wb") as out:
                out.write(src.read())
            try:
                os.chmod(dst, m.mode & 0o777)
            except OSError:
                pass
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/runtime_build")
    ap.add_argument("--arch", default="aarch64", help="aarch64 / arm（默认 aarch64）")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    files = os.path.join(out, "files")
    cache = os.path.join(out, "debs")
    os.makedirs(files, exist_ok=True)
    os.makedirs(cache, exist_ok=True)

    pkgs = load_index()
    need = set()
    for r in ROOTS:
        if r in pkgs:
            need |= deps_of(pkgs, r)
        else:
            print("  索引里没有:", r)
    need -= SKIP
    print("要装 %d 个包：%s" % (len(need), ", ".join(sorted(need))), flush=True)

    total = 0
    for name in sorted(need):
        info = pkgs[name]
        fn = info["Filename"].split("/")[-1]
        dst = os.path.join(cache, fn)
        if not os.path.exists(dst):
            print("  下载", fn, flush=True)
            fetch(BASE + info["Filename"], dst)
        n = extract(dst, files)
        total += n
        print("  %-28s %5d 个文件" % (name, n), flush=True)

    print("\n解出 %d 个文件 -> %s" % (total, files), flush=True)
    py = os.path.join(files, "usr/bin/python3")
    print("python3:", "有" if os.path.exists(py) else "没有（检查包列表）")


if __name__ == "__main__":
    main()
