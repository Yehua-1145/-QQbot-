"""给运行时目录塞一个纯 python 的第三方依赖：websocket-client。

aibot 连 NapCat 用的是 `import websocket`，Termux 里是 pip 装的。
内置运行时没有 pip，所以直接把包文件拷进 site-packages。

用法：
    python add_websocket_client.py --runtime build/runtime_build
"""
import argparse
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

VERSION = "1.8.0"
URL = ("https://files.pythonhosted.org/packages/source/w/websocket-client/"
       "websocket_client-%s.tar.gz" % VERSION)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", default="build/runtime_build")
    ap.add_argument("--pyver", default="")
    a = ap.parse_args()

    files = os.path.join(os.path.abspath(a.runtime), "files")
    libdir = os.path.join(files, "usr", "lib")
    if not os.path.isdir(libdir):
        print("没有运行时目录:", libdir)
        sys.exit(1)

    # 找 python3.X
    pyvers = sorted(d for d in os.listdir(libdir) if d.startswith("python3."))
    if not pyvers:
        print("usr/lib 里没找到 python3.x")
        sys.exit(1)
    py = a.pyver or pyvers[-1]
    site = os.path.join(libdir, py, "site-packages")
    os.makedirs(site, exist_ok=True)
    print("目标:", site)

    tmp = tempfile.mkdtemp()
    tgz = os.path.join(tmp, "ws.tar.gz")
    print("下载 websocket-client %s …" % VERSION, flush=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "Botagent"})
    with urllib.request.urlopen(req, timeout=180) as r, open(tgz, "wb") as f:
        f.write(r.read())

    import tarfile
    with tarfile.open(tgz) as tf:
        tf.extractall(tmp)

    src = None
    for d in os.listdir(tmp):
        cand = os.path.join(tmp, d, "websocket")
        if os.path.isdir(cand):
            src = cand
            break
    if not src:
        print("压缩包里没找到 websocket/ 目录")
        sys.exit(1)

    dst = os.path.join(site, "websocket")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    n = sum(len(fs) for _, _, fs in os.walk(dst))
    print("已放入 websocket/（%d 个文件）" % n)

    # 验证
    ok = os.path.exists(os.path.join(dst, "__init__.py"))
    print("校验:", "OK" if ok else "缺 __init__.py")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
