#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闲时图库预取（不调用任何模型，纯脚本）

- 只在 3~7 点跑（--now 可强制立刻跑一次）
- 每次随机抓 10~50 张，cosplay / 二次元
- safe 池：Bing 安全图源
- r18 池：JM 禁漫，**优先挑带 cosplay + R-18 标签的相册**
- 24 小时自动清理 + 数量/体积上限
- 落地：/sdcard/Pictures/大肥鱼图库/{safe,r18}/ + index.json（手机相册直接可见）

用法：
  python3 prefetch.py             # 只在时间窗内跑
  python3 prefetch.py --now       # 立刻跑一次
  python3 prefetch.py --clean     # 只做清理
  python3 prefetch.py --test-r18  # 只测 r18（抓 3 张）
"""
# ---- 路径根（内置运行时用环境变量指过来，Termux 下保持默认）----
import os as _os_paths
_HOME_ROOT = _os_paths.environ.get("BOTAGENT_HOME_ROOT") or "/data/data/com.termux/files/home"
_PREFIX_ROOT = _os_paths.environ.get("BOTAGENT_PREFIX") or "/data/data/com.termux/files/usr"

import io
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request

AIBOT = _HOME_ROOT + "/aibot"
CACHE = "/sdcard/Pictures/大肥鱼图库"   # 专放相册能直接看的地方
SAFE_DIR = os.path.join(CACHE, "safe")
R18_DIR = os.path.join(CACHE, "r18")
INDEX = os.path.join(CACHE, "index.json")
LOG = os.path.join(AIBOT, "prefetch.log")

MAX_AGE = 7 * 86400      # 7 天才过期（原来 24 小时会把图库天天清空）
ROTATE_STATE = os.path.join(CACHE, "rotate_state.json")
ROTATE_HOURS = 24        # 每 24 小时自动换一批新图
ROTATE_R18 = 40          # 每次换掉的旧 r18 张数
ROTATE_SAFE = 12         # 每次换掉的旧 safe 张数
MAX_TOTAL = 500            # 图库总上限
R18_MAX = 400              # r18 池容量（最大的池）
SAFE_MAX = 100             # safe 池容量（配角，够用就行）
MAX_BYTES = 3 * 1024 * 1024
MIN_BYTES = 40 * 1024
WINDOW = (3, 7)
# 每天总量上限 150 张：r18 100 + safe 50；分 4 批（3~7 点每小时一批）
DAILY_R18 = 100
DAILY_SAFE = 50
BATCH_R18 = 25             # 每批最多抓多少 r18
BATCH_SAFE = 13            # 每批最多抓多少 safe
DAILY_FILE = os.path.join(CACHE, "daily.json")

SAFE_QUERIES = [
    "cosplay 二次元", "anime cosplay", "コスプレ 二次元",
    "二次元 少女 插画", "anime girl illustration", "cosplay girl anime",
]
# 关键词本身带 R-18 倾向，抓回来再用 tag 二次过滤
R18_QUERIES = ["cosplay R-18", "コスプレ R-18", "レイヤー R-18", "cosplay エロ",
               "コスプレ", "レイヤー", "cosplay", "コス"]

UA = ("Mozilla/5.0 (Linux; Android 11; MI 6) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")



# ---------- 去重：内容 hash + 用过的相册 ----------
SEEN_FILE = os.path.join(CACHE, "seen.jsonl")
SEEN_KEEP_DAYS = 7
_seen_cache = {"hashes": None, "albums": None}


def _md5(data):
    import hashlib
    return hashlib.md5(data).hexdigest()


def _load_seen():
    """返回 (hash集合, 相册集合)；超过 7 天的记录会被清掉。"""
    if _seen_cache["hashes"] is not None:
        return _seen_cache["hashes"], _seen_cache["albums"]
    hashes, albums = set(), set()
    cutoff = time.time() - SEEN_KEEP_DAYS * 86400
    album_cutoff = time.time() - 1 * 86400      # 相册只记 1 天，隔天可重试
    keep = []
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                kind = d.get("kind")
                ts = d.get("ts", 0)
                if kind == "album" and ts < album_cutoff:
                    continue                      # 相册记录过期，明天可重试
                if ts < cutoff:
                    continue
                keep.append(line)
                if kind == "img" and d.get("key"):
                    hashes.add(str(d["key"]))
                elif kind == "album" and d.get("key"):
                    albums.add(str(d["key"]))
    except FileNotFoundError:
        pass
    except Exception:
        pass
    _seen_cache["hashes"] = hashes
    _seen_cache["albums"] = albums
    if keep:
        try:
            io.open(SEEN_FILE, "w", encoding="utf-8").write("\n".join(keep) + "\n")
        except Exception:
            pass
    return hashes, albums


def _mark_seen(kind, key):
    try:
        with io.open(SEEN_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "key": str(key), "ts": int(time.time())},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass
    if kind == "img":
        _seen_cache["hashes"].add(str(key))
    elif kind == "album":
        _seen_cache["albums"].add(str(key))


def _today():
    return time.strftime("%Y-%m-%d")


def _load_daily():
    try:
        with open(DAILY_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("date") == _today():
            return d
    except Exception:
        pass
    return {"date": _today(), "r18": 0, "safe": 0}


def _save_daily(d):
    d["date"] = _today()
    try:
        with open(DAILY_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        log("daily save fail: %s" % e)


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _get(url, timeout=25, referer=None):
    hdr = {"User-Agent": UA, "Accept": "image/*,*/*"}
    if referer:
        hdr["Referer"] = referer
    req = urllib.request.Request(url, headers=hdr)
    return urllib.request.urlopen(req, timeout=timeout).read(MAX_BYTES + 1)


def bing_image_urls(query, want=20):
    q = urllib.parse.quote(query)
    url = ("https://www.bing.com/images/async?q=%s&first=0&count=%d&mmasync=1"
           % (q, max(10, want)))
    try:
        html = _get(url, timeout=20).decode("utf-8", "replace")
    except Exception as e:
        log("bing fail %r: %s" % (query, e))
        return []
    urls = re.findall(r'murl&quot;:&quot;(https?://[^&]+?)&quot;', html)
    if not urls:
        urls = re.findall(r'"murl":"(https?://[^"]+)"', html)
    seen, out = set(), []
    for u in urls:
        u = u.replace("\\u0026", "&").replace("\\/", "/")
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _ext(data, url, ctype=""):
    low = (url or "").lower() + " " + (ctype or "").lower()
    for e in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if e in low:
            return ".jpg" if e == ".jpeg" else e
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8].startswith(b"\x89PNG"):
        return ".png"
    if data[:4] == b"RIFF":
        return ".webp"
    return ".jpg"


def grab_safe(need, stamp):
    got = 0
    random.shuffle(SAFE_QUERIES)
    for q in SAFE_QUERIES:
        if got >= need:
            break
        for u in bing_image_urls(q, need * 2):
            if got >= need:
                break
            try:
                data = _get(u, timeout=20, referer="https://www.bing.com/")
                if not data or not (MIN_BYTES <= len(data) <= MAX_BYTES):
                    continue
                _hashes, _albums = _load_seen()
                _h = _md5(data)
                if _h in _hashes:
                    log("safe skip duplicate image")
                    continue
                ext = _ext(data, u)
                name = "s_%s_%d_%03d%s" % (stamp, os.getpid() % 1000, got + 1, ext)
                with open(os.path.join(SAFE_DIR, name), "wb") as f:
                    f.write(data)
                _mark_seen("img", _h)
                got += 1
                log("safe +1 (%s) %d bytes" % (q, len(data)))
            except Exception as e:
                log("safe skip: %s" % str(e)[:60])
    return got


# ---------------- r18：JM，按 tag 挑 cosplay + R-18 ----------------
def _jm_search_tagged(query, limit=12):
    """jmcomic 的 search_site 返回 (album_id, title) 元组；R-18 标记在标题里。

    返回 [(album_id, title)]。
    """
    try:
        import agent
        client = agent._jm_client()
        page = client.search_site(query)
    except Exception as e:
        log("jm search(%r) fail: %s" % (query, e))
        return []
    out = []
    try:
        for item in page:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                aid, title = str(item[0]), str(item[1])
            else:
                aid = str(getattr(item, "id", "") or getattr(item, "album_id", "") or "")
                title = str(getattr(item, "name", "") or "")
            if not aid:
                continue
            out.append((aid, title))
            if len(out) >= limit:
                break
    except Exception as e:
        log("jm search iterate fail: %s" % e)
    return out


def _score_tags(tags, title):
    """3 = cosplay + R18 都有；2 = 只有 cosplay；1 = 只有 R18；0 = 都不是。"""
    blob = (" ".join(tags) + " " + (title or "")).lower()
    cos = ("cosplay" in blob) or ("コスプレ" in blob) or ("レイヤー" in blob) or ("cos" in blob)
    r18 = ("r-18" in blob) or ("r18" in blob) or ("成人" in blob) or ("エロ" in blob) \
        or ("無修正" in blob) or ("中出" in blob)
    if cos and r18:
        return 3
    if cos:
        return 2
    if r18:
        return 1
    return 0


def _is_photo(data):
    """照片=有颜色；漫画页绝大多数接近灰度。返回 True 表示像真人照片。"""
    try:
        from PIL import Image
        import io as _io
        im = Image.open(_io.BytesIO(data)).convert("RGB")
        im.thumbnail((140, 140))
        px = list(im.getdata())
        if not px:
            return True
        sat = sum(max(p) - min(p) for p in px) / len(px)
        return sat > 26
    except Exception:
        return True


def _album_is_photo_set(aid):
    """查相册详情：页数多 + 标签是 cosplay/写真 + 没有漫画/汉化标记 → 判为真人写真。"""
    import re as _re
    try:
        import agent
        d = agent._jm_client().get_album_detail(str(aid))
    except Exception as e:
        log("album detail fail %s: %s" % (aid, str(e)[:60]))
        return False
    tags = [str(t).lower() for t in (getattr(d, "tags", None) or [])]
    name = str(getattr(d, "name", "") or "").lower()
    blob = " ".join(tags) + " " + name
    pages = int(getattr(d, "page_count", 0) or 0)
    # 漫画/汉化特征直接排除
    if _re.search(r"\bc\d{2,3}\b|漢化|汉化|同人誌|同人cg|cg集|單行本|短篇|雜誌|畫集|画集|イラスト|插畫|插画", blob):
        return False
    # 必须是 cosplay / 写真 类
    if not any(k in blob for k in ("コスプレ", "cosplay", "レイヤー", "自攝", "自撮", "寫真", "写真", "コスホリ")):
        return False
    # 真人写真集通常页数很多
    return pages >= 40


def _jm_tag_albums(keyword, limit=20):
    """按 tag 搜 JM（コスプレ/cosplay 这类 tag 出来的才是真写真，不是漫画）。"""
    try:
        import agent
        client = agent._jm_client()
        page = client.search_tag(keyword)
    except Exception as e:
        log("jm tag(%r) fail: %s" % (keyword, e))
        return []
    out = []
    try:
        for item in page:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                aid, title = str(item[0]), str(item[1])
            else:
                aid = str(getattr(item, "id", "") or "")
                title = str(getattr(item, "name", "") or "")
            if aid:
                out.append((aid, title))
            if len(out) >= limit:
                break
    except Exception as e:
        log("jm tag iterate fail: %s" % e)
    return out


COS_HINT = ("コスプレ", "cosplay", "レイヤー", "寫真", "自攝", "コスホリ", "写真")
MANGA_HINT = ("漢化", "[c9", "[c8", "[c7", "同人誌", "短篇集", "雜誌", "畫集")


def _photo_score(title):
    """判断这本是不是"真人 cos 写真"，不是漫画本。"""
    t = (title or "").lower()
    s = 0
    if any(k.lower() in t for k in COS_HINT):
        s += 2
    if ("自攝" in t) or ("寫真" in t) or ("写真" in t):
        s += 1
    if any(m.lower() in t for m in MANGA_HINT):
        s -= 2
    return s


def _eh_cosplay_galleries(pages=3, limit=40):
    """E-Hentai 的 Cosplay 分类（真人写真），比禁漫可靠得多。"""
    import re as _re
    import agent
    out, seen = [], set()
    for pg in range(pages):
        url = "https://e-hentai.org/cosplay" + ("" if pg == 0 else "?page=%d" % pg)
        try:
            html = agent._eh_get(url).decode("utf-8", "replace")
        except Exception as e:
            log("eh cosplay page %d fail: %s" % (pg, e))
            break
        pairs = _re.findall(
            r'<a href="(https://e-hentai\.org/g/[^"]+)"[^>]*>\s*<div[^>]*class="glink"[^>]*>(.*?)</div>',
            html, _re.S)
        for u, t in pairs:
            if u in seen:
                continue
            seen.add(u)
            out.append((u, _re.sub(r"<[^>]+>", "", t).strip()))
            if len(out) >= limit:
                return out
    return out


PHOTO_RATIO = 0.5          # cos写真 50%（cos : 漫画 = 5 : 5）
SET_RATIO = 0.2            # 散图 20%（算在漫画那一半里）
MANGA_RATIO = 0.3          # 漫画 30%
# E站上这些 tag 表示"没露点/全年龄"，尽量别抓
NON_EXPLICIT_TAGS = ("no sex", "nudity only", "non-nude", "non nude",
                     "all ages", "全年龄", "全年齢", "no nudity")


def _eh_tags(gurl):
    """取 E站画廊的 tag 列表（小写）。"""
    import re as _re
    try:
        import agent
        html = agent._eh_get(gurl).decode("utf-8", "replace")
    except Exception as e:
        log("eh tags fail: %s" % str(e)[:60])
        return []
    return [t.replace("_", " ").strip().lower()
            for t in _re.findall(r'/tag/([^"?]+)', html)]


def _eh_is_explicit(gurl):
    tags = _eh_tags(gurl)
    if not tags:
        return True
    blob = " | ".join(tags)
    for bad in NON_EXPLICIT_TAGS:
        if bad in blob:
            log("r18 跳过无露点画廊（tag: %s）" % bad)
            return False
    return True


def _grab_eh_photos(need, stamp):
    """E站 Cosplay 分类：真人写真（需要代理）。"""
    if need <= 0:
        return 0
    try:
        import agent
    except Exception as e:
        log("import agent failed: %s" % e)
        return 0
    galleries = _eh_cosplay_galleries(10, 120)
    if not galleries:
        log("r18 写真: E站 cosplay 分类没拿到画廊（代理可能不通）")
        return 0
    log("r18 写真: E站 cosplay 分类 %d 个画廊" % len(galleries))

    _hashes, _albums = _load_seen()
    got = 0
    for gurl, title in galleries:
        if got >= need:
            break
        if gurl in _albums:
            continue
        if _is_bad(title) or _is_bad(" ".join(_eh_tags(gurl))):
            log("r18 跳过男同/男娘/福瑞: %s" % title[:24])
            _mark_seen("album", gurl)
            continue
        _mark_seen("album", gurl)
        if not _eh_is_explicit(gurl):
            continue
        try:
            out = agent.t_eh_download(gurl, min(2, need - got), 1, True)
        except Exception as e:
            log("eh dl fail %s: %s" % (title[:20], str(e)[:60]))
            continue
        for _raw in (out or "").splitlines():
            if not _raw.startswith("/"):
                continue
            p = _raw.split(" (")[0].strip()
            if got >= need or not os.path.exists(p):
                continue
            try:
                data = open(p, "rb").read(MAX_BYTES + 1)
                if not (MIN_BYTES <= len(data) <= MAX_BYTES):
                    continue
                h = _md5(data)
                if h in _hashes:
                    continue
                ext = os.path.splitext(p)[1] or ".jpg"
                name = "p_%s_%d_%03d%s" % (stamp, os.getpid() % 1000, got + 1, ext)
                with open(os.path.join(R18_DIR, name), "wb") as f:
                    f.write(data)
                _mark_seen("img", h)
                got += 1
                log("cos +1 %s %d bytes" % (title[:26], len(data)))
            except Exception as e:
                log("cos copy skip: %s" % str(e)[:60])
    return got


def _grab_jm_photos(need, stamp):
    """JM 的 cosplay tag 里也有真人写真，不需要代理（E站不通时兜底）。"""
    if need <= 0:
        return 0
    try:
        import agent
    except Exception as e:
        log("import agent failed: %s" % e)
        return 0
    got = 0
    for kw in ("コスプレ", "cosplay", "レイヤー", "コス", "自撮", "写真集"):
        if got >= need:
            break
        for aid, title in _jm_tag_albums(kw, 20):
            if got >= need:
                break
            if _is_bad(title):
                _mark_seen("album", aid)
                log("cos(JM) 跳过黑名单: %s" % title[:24])
                continue
            if _is_bad(title):
                _mark_seen("album", aid)
                continue
            _hashes, _albums = _load_seen()
            if aid in _albums:
                continue
            if not _album_is_photo_set(aid):
                _mark_seen("album", aid)
                continue
            _mark_seen("album", aid)
            try:
                out = agent.t_jm_download(aid, 1, min(5, need - got), True)
            except Exception as e:
                log("jm photo dl fail %s: %s" % (aid, str(e)[:50]))
                continue
            for _raw in (out or "").splitlines():
                if not _raw.startswith("/"):
                    continue
                p = _raw.split(" (")[0].strip()
                if got >= need or not os.path.exists(p):
                    continue
                try:
                    data = open(p, "rb").read(MAX_BYTES + 1)
                    if not (MIN_BYTES <= len(data) <= MAX_BYTES):
                        continue
                    if not _is_photo(data):
                        continue
                    h = _md5(data)
                    if h in _hashes:
                        continue
                    ext = os.path.splitext(p)[1] or ".jpg"
                    name = "p_%s_%d_%03d%s" % (stamp, os.getpid() % 1000, got + 1, ext)
                    with open(os.path.join(R18_DIR, name), "wb") as f:
                        f.write(data)
                    _mark_seen("img", h)
                    got += 1
                    log("cos(JM) +1 %s %d bytes" % (title[:24], len(data)))
                except Exception as e:
                    log("cos copy skip: %s" % str(e)[:50])
    return got


def grab_r18_photos(need, stamp):
    """写真优先 E站，不通就用 JM tag 兜底。"""
    got = _grab_eh_photos(need, stamp)
    if got < need:
        log("写真: E站只拿到 %d/%d，改用 JM tag 兜底" % (got, need))
        got += _grab_jm_photos(need - got, stamp)
    return got


def _r18_enabled():
    """是否允许抓 R18。默认关闭，需要用户在控制台「更多设置」里手动开启。"""
    try:
        import json as _json
        with open(_HOME_ROOT + "/aibot/config.json", encoding="utf-8") as f:
            d = _json.load(f)
        return bool(d.get("r18_prefetch"))
    except Exception:
        return False


def _proxy_up():
    """tun0 存在 = 代理开着。可用 PF_FORCE_JM=1 强制允许（JM 有时走代理也能通）。"""
    if os.environ.get("PF_FORCE_JM") == "1":
        return False
    try:
        return os.path.exists("/sys/class/net/tun0")
    except Exception:
        return False


def grab_r18_manga(need, stamp):
    """JM 禁漫：漫画。代理开着时国内 CDN 常被 TLS 重置，自动跳过。"""
    if need <= 0:
        return 0
    if _proxy_up():
        log("漫画: 代理开着（tun0），国内 CDN 会 SSL 重置，本批跳过漫画")
        return 0
    try:
        import agent
    except Exception as e:
        log("import agent failed: %s" % e)
        return 0
    got = 0
    _hashes, seen_albums = _load_seen()
    for q in R18_QUERIES:
        if got >= need:
            break
        try:
            res = agent.t_jm_search(q, 20)
        except Exception as e:
            log("jm search fail %r: %s" % (q, e))
            continue
        import re as _re
        hits = _re.findall(r"id=(\d{4,9})", res or "")
        for aid in hits:
            if got >= need:
                break
            if str(aid) in seen_albums:
                continue
            _mark_seen("album", aid)
            try:
                out = agent.t_jm_download(aid, 1, min(2, need - got), True)
            except Exception as e:
                log("jm dl fail %s: %s" % (aid, str(e)[:50]))
                continue
            for _raw in (out or "").splitlines():
                if not _raw.startswith("/"):
                    continue
                p = _raw.split(" (")[0].strip()
                if got >= need or not os.path.exists(p):
                    continue
                try:
                    data = open(p, "rb").read(MAX_BYTES + 1)
                    if not (MIN_BYTES <= len(data) <= MAX_BYTES):
                        continue
                    h = _md5(data)
                    if h in _hashes:
                        continue
                    ext = os.path.splitext(p)[1] or ".jpg"
                    name = "m_%s_%d_%03d%s" % (stamp, os.getpid() % 1000, got + 1, ext)
                    with open(os.path.join(R18_DIR, name), "wb") as f:
                        f.write(data)
                    _mark_seen("img", h)
                    got += 1
                    log("manga +1 %s %d bytes" % (q, len(data)))
                except Exception as e:
                    log("manga copy skip: %s" % str(e)[:50])
    return got


BAD_TAGS = ("yaoi", "bara", "otokonoko", "furry", "kemono", "male only",
            "males only", "gay", "shotacon", "futanari", "trap",
            "男同", "耽美", "男娘", "偽娘", "伪娘", "福瑞", "獸人", "兽人", "guro", "gore", "ryona", "dismember", "分尸", "肢解", "グロ", "リョナ", "肉片", 
            "ホモ", "ゲイ", "やおい", "男の娘", "オトコノコ", "おとこのこ", "女装男子", "futa", "おなべ", "男娼", "ケモノ", "獣人", "ふたなり")


def _is_bad(text):
    """男同 / 男娘 / 福瑞 一律不要。"""
    t = (text or "").lower()
    return any(b.lower() in t for b in BAD_TAGS)


def _eh_image_sets(pages=3, limit=40):
    """E站 Image Set 分类（散图/图集）。"""
    import re as _re
    import agent
    out, seen = [], set()
    for pg in range(pages):
        url = "https://e-hentai.org/?f_cats=32" + ("" if pg == 0 else "&page=%d" % pg)
        try:
            html = agent._eh_get(url).decode("utf-8", "replace")
        except Exception as e:
            log("eh image-set page %d fail: %s" % (pg, e))
            break
        pairs = _re.findall(
            r'<a href="(https://e-hentai\.org/g/[^"]+)"[^>]*>\s*<div[^>]*class="glink"[^>]*>(.*?)</div>',
            html, _re.S)
        for u, t in pairs:
            if u in seen:
                continue
            seen.add(u)
            out.append((u, _re.sub(r"<[^>]+>", "", t).strip()))
            if len(out) >= limit:
                return out
    return out


def grab_r18_sets(need, stamp):
    """抓散图/图集（E站 Image Set），文件名 s_ 前缀。"""
    if need <= 0:
        return 0
    try:
        import agent
    except Exception as e:
        log("import agent failed: %s" % e)
        return 0
    galleries = _eh_image_sets(8, 100)
    if not galleries:
        log("散图: E站 Image Set 分类没拿到画廊")
        return 0
    log("散图: E站 Image Set %d 个画廊" % len(galleries))
    _hashes, _albums = _load_seen()
    got = 0
    for gurl, title in galleries:
        if got >= need:
            break
        if gurl in _albums:
            continue
        _mark_seen("album", gurl)
        try:
            out = agent.t_eh_download(gurl, min(3, need - got), 1, True)
        except Exception as e:
            log("set dl fail %s: %s" % (title[:20], str(e)[:50]))
            continue
        for _raw in (out or "").splitlines():
            if not _raw.startswith("/"):
                continue
            p = _raw.split(" (")[0].strip()
            if got >= need or not os.path.exists(p):
                continue
            try:
                data = open(p, "rb").read(MAX_BYTES + 1)
                if not (MIN_BYTES <= len(data) <= MAX_BYTES):
                    continue
                h = _md5(data)
                if h in _hashes:
                    continue
                ext = os.path.splitext(p)[1] or ".jpg"
                name = "s_%s_%d_%03d%s" % (stamp, os.getpid() % 1000, got + 1, ext)
                with open(os.path.join(R18_DIR, name), "wb") as f:
                    f.write(data)
                _mark_seen("img", h)
                got += 1
                log("set +1 %s %d bytes" % (title[:26], len(data)))
            except Exception as e:
                log("set copy skip: %s" % str(e)[:50])
    return got


def grab_r18(need, stamp):
    """r18 池三桶：cos写真 50% + 散图/图集 30% + 漫画 20%，谁落后先补谁。"""
    if need <= 0:
        return 0
    # 按"当前池内已有比例"动态分配：写真落后就整批补写真
    def _cnt(prefix):
        try:
            return len([f for f in os.listdir(R18_DIR) if f.startswith(prefix)])
        except Exception:
            return 0
    cur_p, cur_s, cur_m = _cnt("p_"), _cnt("s_"), _cnt("m_")
    total = cur_p + cur_s + cur_m + need
    tgt_p = int(round(total * PHOTO_RATIO))
    tgt_s = int(round(total * SET_RATIO))
    tgt_m = max(0, total - tgt_p - tgt_s)
    # 三个桶各自的缺口
    d_p = max(0, tgt_p - cur_p)
    d_s = max(0, tgt_s - cur_s)
    d_m = max(0, tgt_m - cur_m)
    d_sum = d_p + d_s + d_m
    if d_sum <= 0:
        n_photo, n_sets, n_manga = need, 0, 0
    else:
        # 按缺口比例分配（每桶至少 1 张，避免永远轮不到）
        n_photo = int(need * d_p / d_sum)
        n_sets = int(need * d_s / d_sum)
        n_manga = need - n_photo - n_sets
        if d_s > 0 and n_sets == 0:
            n_sets, n_manga = 1, max(0, n_manga - 1)
        if d_m > 0 and n_manga == 0:
            n_manga, n_sets = 1, max(0, n_sets - 1)
        n_manga = max(0, min(n_manga, d_m))
    log("r18 目标 %d 张 = cos写真 %d + 散图 %d + 漫画 %d（5:3:2）"
        % (need, n_photo, n_sets, n_manga))

    a = grab_r18_photos(n_photo, stamp)
    c = grab_r18_sets(n_sets, stamp)
    b = grab_r18_manga(n_manga, stamp)
    log("r18 实际：cos写真 %d + 散图 %d + 漫画 %d = %d" % (a, c, b, a + c + b))
    return a + c + b


def media_scan(path):
    """让系统相册（MediaStore）立刻收录新图，不然原生图库看不到。"""
    import subprocess
    try:
        subprocess.run(["am", "broadcast", "-a",
                        "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                        "-d", "file://" + path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        log("media scan -> %s" % path)
    except Exception as e:
        log("media scan fail: %s" % e)



def _rotate_cfg():
    """换新设置：config.json 里的 rotate_enabled / rotate_hours / rotate_count。"""
    cfg = {}
    try:
        with open(os.path.join(AIBOT, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass
    return {
        "enabled": bool(cfg.get("rotate_enabled", True)),
        "hours": max(1, int(cfg.get("rotate_hours") or ROTATE_HOURS)),
        "count": max(0, int(cfg.get("rotate_count") or ROTATE_R18)),
    }


def _rotate_state():
    try:
        with open(ROTATE_STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _rotate_save(st):
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(ROTATE_STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception as e:
        log("rotate state write fail: %s" % e)


def rotate_gallery(force=False):
    """把最旧的一批图删掉，给新图腾位置。返回删掉的数量。"""
    cfg = _rotate_cfg()
    st = _rotate_state()
    now = time.time()
    last = float(st.get("last") or 0)

    if not force:
        if not cfg["enabled"]:
            return 0
        if now - last < cfg["hours"] * 3600:
            return 0

    n_r18 = cfg["count"] if cfg["count"] else ROTATE_R18
    n_safe = max(0, int(n_r18 * ROTATE_SAFE / max(1, ROTATE_R18)))
    removed = 0
    detail = {}
    for d, n in ((R18_DIR, n_r18), (SAFE_DIR, n_safe)):
        if n <= 0:
            continue
        files = []
        try:
            for fn in os.listdir(d):
                p = os.path.join(d, fn)
                if os.path.isfile(p):
                    try:
                        files.append((os.stat(p).st_mtime, p))
                    except Exception:
                        pass
        except Exception:
            continue
        files.sort()                     # 最旧的在前
        gone = 0
        for _, p in files[:n]:
            try:
                os.remove(p)
                gone += 1
            except Exception:
                pass
        detail[os.path.basename(d)] = gone
        removed += gone

    st["last"] = int(now)
    st["removed"] = detail
    st["total"] = int(st.get("total") or 0) + removed
    _rotate_save(st)
    log("=== 图库换新：删掉旧图 %s，累计 %d 张 ===" % (detail, st["total"]))
    return removed



def clean():
    now = time.time()
    entries = []
    for d, tag in ((SAFE_DIR, "safe"), (R18_DIR, "r18")):
        os.makedirs(d, exist_ok=True)
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            try:
                st = os.stat(p)
            except Exception:
                continue
            if now - st.st_mtime > MAX_AGE:
                try:
                    os.remove(p)
                    log("clean expire %s" % fn)
                except Exception:
                    pass
                continue
            entries.append({"path": p, "tag": tag, "ts": int(st.st_mtime),
                            "size": st.st_size})
    # 分池裁剪：safe / r18 各自上限
    for tag, cap in (("safe", SAFE_MAX), ("r18", R18_MAX)):
        pool = [e for e in entries if e["tag"] == tag]
        if len(pool) > cap:
            pool.sort(key=lambda x: x["ts"])
            for e in pool[:len(pool) - cap]:
                try:
                    os.remove(e["path"])
                except Exception:
                    pass
    entries = [e for e in entries if os.path.exists(e["path"])]
    try:
        with open(INDEX, "w", encoding="utf-8") as f:
            json.dump({"updated": int(now), "count": len(entries),
                       "safe": sum(1 for e in entries if e["tag"] == "safe"),
                       "r18": sum(1 for e in entries if e["tag"] == "r18"),
                       "items": entries}, f, ensure_ascii=False)
    except Exception as e:
        log("index write fail: %s" % e)
    return entries


def main():
    os.makedirs(SAFE_DIR, exist_ok=True)
    os.makedirs(R18_DIR, exist_ok=True)

    if "--clean" in sys.argv:
        e = clean()
        log("clean done: %d images" % len(e))
        return

    if "--test-r18" in sys.argv:
        n = grab_r18(3, time.strftime("%Y%m%d_%H%M"))
        log("test-r18 done: %d" % n)
        clean()
        media_scan(R18_DIR)
        return

    force = "--now" in sys.argv

    if "--rotate" in sys.argv:
        n = rotate_gallery(force=True)
        log("手动换新：删掉 %d 张旧图" % n)
        clean()
        return

    rotate_gallery()
    # 机器忙就先不抓，别和 bot/NapCat 抢内存和 CPU
    try:
        load1 = float(open("/proc/loadavg").read().split()[0])
    except Exception:
        load1 = 0.0
    # proot+QQ 的基线负载就有 3~5，只看 load 会天天跳过；改成"负载极高 或 内存见底"
    try:
        mem_avail = int(open("/proc/meminfo").read().split("MemAvailable:")[1].split()[0]) // 1024
    except Exception:
        mem_avail = 9999
    if not force and (load1 > 7.0 or mem_avail < 250):
        log("负载 %.1f / 可用 %dMB 太吃紧，本批跳过（错峰）" % (load1, mem_avail))
        return
    log("开始抓图（负载 %.1f / 可用 %dMB）" % (load1, mem_avail))
    hour = time.localtime().tm_hour
    if os.environ.get("PF_ANYTIME") == "1":
        hour = 4          # 允许白天也抓（循环判定池子没满时会设这个变量）
    if not force and not (WINDOW[0] <= hour < WINDOW[1]):
        print("[%s] 不在时间窗（%d~%d 点），跳过" % (time.strftime("%H:%M"), WINDOW[0], WINDOW[1]))
        return

    clean()
    # 今日配额 + 每批上限 + 池余量，三者取最小
    daily = _load_daily()
    def _cnt(d):
        try:
            return len([f for f in os.listdir(d)
                        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])
        except Exception:
            return 0
    cur_r18, cur_safe = _cnt(R18_DIR), _cnt(SAFE_DIR)
    if _r18_enabled():
        n_r18 = min(BATCH_R18, max(0, DAILY_R18 - daily["r18"]), max(0, R18_MAX - cur_r18))
    else:
        n_r18 = 0
        if cur_r18 == 0:
            log("r18 抓图默认关闭（控制台 → 设置 → 更多设置 可开启）")
    n_safe = min(BATCH_SAFE, max(0, DAILY_SAFE - daily["safe"]), max(0, SAFE_MAX - cur_safe))
    if n_r18 <= 0 and n_safe <= 0:
        log("今日配额已满/池已满（r18 %d/%d，safe %d/%d），跳过"
            % (daily["r18"], DAILY_R18, daily["safe"], DAILY_SAFE))
        return
    stamp = time.strftime("%Y%m%d_%H%M")
    total = n_safe + n_r18
    log("=== 开始预取：目标 %d 张（safe %d / r18 %d）===" % (total, n_safe, n_r18))
    s = grab_safe(n_safe, stamp)
    r = grab_r18(n_r18, stamp)
    daily["safe"] += s
    daily["r18"] += r
    _save_daily(daily)
    entries = clean()
    media_scan(SAFE_DIR)
    media_scan(R18_DIR)
    log("=== 完成：本次 safe %d + r18 %d；今日累计 safe %d/%d、r18 %d/%d；缓存共 %d 张 ==="
        % (s, r, daily["safe"], DAILY_SAFE, daily["r18"], DAILY_R18, len(entries)))


if __name__ == "__main__":
    main()
