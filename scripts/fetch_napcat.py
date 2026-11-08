"""下载 NapCat 官方包并校验 sha256（用于构建内置扩展）。

我们只在**构建出来的 APK** 里附带这个官方原包（许可证允许，附全文+署名+非商业），
仓库本身不存二进制，谁构建谁自己拉，这样仓库干净、也避免重复分发。

用法：
    python fetch_napcat.py --out ../apk_src_v2/napcat_assets
"""
import argparse
import hashlib
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

VER = "v4.18.42"
SHA256 = "02e5ff0f79916c1e04c81c1b4590056406fb4293f1f1300c955e71fd08b2829d"
URL = ("https://github.com/NapNeko/NapCatQQ/releases/download/%s/NapCat.Shell.zip" % VER)
MIRRORS = [
    "https://ghfast.top/" + URL,
    "https://gh-proxy.com/" + URL,
    "https://ghproxy.net/" + URL,
]


def fetch(url, dst):
    req = urllib.request.Request(url, headers={"User-Agent": "Botagent"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dst, "wb") as f:
        f.write(r.read())


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="napcat_assets")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    dst = os.path.join(a.out, "NapCat.Shell.zip")

    if os.path.exists(dst) and sha256(dst).lower() == SHA256:
        print("已存在且校验通过:", dst)
        return

    for i, url in enumerate([URL] + MIRRORS):
        label = "官方直连" if i == 0 else "镜像%d" % i
        try:
            print("尝试%s：%s" % (label, url), flush=True)
            fetch(url, dst)
            got = sha256(dst).lower()
            if got == SHA256:
                print("OK  %s  %.1f MB" % (dst, os.path.getsize(dst) / 1048576))
                return
            print("  校验不通过，丢弃（拿到 %s）" % got[:16])
            os.remove(dst)
        except Exception as e:
            print("  失败：%s" % str(e)[:120])
    print("全部失败。可以手动下载 NapCat.Shell.zip 放到", dst)
    sys.exit(1)


if __name__ == "__main__":
    main()
