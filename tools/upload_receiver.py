#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PhoneAgent 文件中转（跑在「协议端」那台手机上，Termux 里即可，不需要 root）

主手机（小米6）把要发的 zip/图片 POST 过来，这边落到本机 Download 目录，
返回一个 NapCat/Shamrock 能读到的路径。

用法（辅机）：
    python3 upload_receiver.py --port 8099 --token 一长串随机字符
    # 目录默认 /sdcard/Download，可用 --dir 改

主手机（小米6）：
    export PHONEAGENT_FILE_RELAY=http://<辅机内网IP>:8099
    export PHONEAGENT_FILE_RELAY_TOKEN=同一串
"""
import argparse
import base64
import json
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = None


def safe_name(name):
    name = urllib.parse.unquote(name or "")
    name = os.path.basename(name)
    name = re.sub(r"[^\w\u4e00-\u9fff.\-()\[\]]+", "_", name)
    return name or "file.bin"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == "/ping":
            self._json(200, {"ok": True, "dir": ARGS.dir})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/upload":
            self._json(404, {"ok": False, "error": "not found"})
            return
        if not self._authorized():
            self._json(403, {"ok": False, "error": "bad token"})
            return
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n <= 0:
            self._json(400, {"ok": False, "error": "empty body"})
            return
        name = safe_name(self.headers.get("X-Filename", "file.bin"))
        os.makedirs(ARGS.dir, exist_ok=True)
        path = os.path.join(ARGS.dir, name)
        with open(path, "wb") as f:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        os.chmod(path, 0o644)
        print("[relay] saved %s (%d bytes)" % (path, os.path.getsize(path)), flush=True)
        self._json(200, {"ok": True, "path": path, "size": os.path.getsize(path)})

    def _authorized(self):
        if not ARGS.token:
            return True
        return self.headers.get("X-Token", "") == ARGS.token


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--token", default="")
    ap.add_argument("--dir", default="/sdcard/Download")
    ARGS = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", ARGS.port), Handler)
    srv.daemon_threads = True
    print("upload receiver on 0.0.0.0:%d -> %s (token %s)"
          % (ARGS.port, ARGS.dir, "on" if ARGS.token else "OFF"), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
