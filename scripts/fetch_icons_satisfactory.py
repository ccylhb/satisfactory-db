# -*- coding: utf-8 -*-
"""Satisfactory icon fetcher — pageimages API route.

Infobox simple has no |image param, so resolve each page's pageimage via
prop=pageimages (fandom allows it), then build the static md5 URL:
  https://static.wikia.nocookie.net/satisfactory_gamepedia_en/images/<h1>/<h2>/<File>
"""
import concurrent.futures as cf
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "src", "data")
ICON_DIR = os.path.join(BASE_DIR, "public", "icons")
DL_HOST = "https://static.wikia.nocookie.net/satisfactory_gamepedia_en/images"
API = "https://satisfactory.fandom.com/api.php"
UA = "SatisfactoryDB/1.0 (site: satisfactory-db.pages.dev; contact franceiwhdbks865@gmail.com)"

DATASETS = ["items", "buildings"]


def cap_first(name):
    return name[0].upper() + name[1:] if name else name


def icon_url(fname):
    cap = cap_first(fname)
    h = hashlib.md5(cap.encode()).hexdigest()
    return f"{DL_HOST}/{h[0]}/{h[:2]}/{urllib.parse.quote(cap)}"


def download(url, outpath):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=30).read()
    if len(data) < 200:
        return "tiny"
    with open(outpath, "wb") as f:
        f.write(data)
    return "ok"


def opener_proxy():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": "http://127.0.0.1:7897",
                                     "http": "http://127.0.0.1:7897"}))


def api(p):
    url = API + "?" + urllib.parse.urlencode({**p, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        return json.load(urllib.request.urlopen(req, timeout=40))
    except Exception:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return json.load(opener_proxy().open(req, timeout=40))


def pageimages(titles):
    """Batched pageimages: {title: filename}."""
    out = {}
    batch = 50
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        r = api({"action": "query", "prop": "pageimages", "piprop": "name",
                 "pilimit": "max", "titles": "|".join(chunk)})
        q = r.get("query", {})
        redir = {rr["from"]: rr["to"] for rr in q.get("redirects", [])}
        for pg in q.get("pages", {}).values():
            fname = pg.get("pageimage")
            if fname:
                out[pg["title"]] = fname
        print(f"  pageimages {min(i + batch, len(titles))}/{len(titles)} (cum {len(out)})")
        time.sleep(0.4)
    return out


def main():
    os.makedirs(ICON_DIR, exist_ok=True)
    stats = {"ok": 0, "cached": 0, "fail": 0, "tiny": 0}
    fails = []
    jobs = []
    for ds in DATASETS:
        data = json.load(open(os.path.join(DATA_DIR, f"satisfactory_{ds}.json"), encoding="utf-8"))
        titles = [x["title"] for x in data]
        pim = pageimages(titles)
        for x in data:
            fname = pim.get(x["title"])
            if not fname:
                continue
            fname = os.path.basename(fname)
            safe = re.sub(r"[^A-Za-z0-9._\-]", "_", fname)
            outpath = os.path.join(ICON_DIR, safe)
            if not (os.path.exists(outpath) and os.path.getsize(outpath) > 0):
                jobs.append((fname, safe, outpath))
            else:
                stats["cached"] += 1
            x["icon_file"] = safe
        json.dump(data, open(os.path.join(DATA_DIR, f"satisfactory_{ds}.json"), "w", encoding="utf-8"), ensure_ascii=False)

    def work(args):
        fname, safe, outpath = args
        try:
            res = download(icon_url(fname) + "?format=original", outpath)
            return fname, res
        except Exception as e:
            return fname, f"fail:{str(e)[:40]}"

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for fname, res in ex.map(work, jobs):
            if res == "ok":
                stats["ok"] += 1
            elif res == "cached":
                stats["cached"] += 1
            elif res == "tiny":
                stats["tiny"] += 1
                fails.append((fname, res))
            else:
                stats["fail"] += 1
                fails.append((fname, res))
    print("stats:", stats)
    print("failed sample:", fails[:10])
    total = stats["ok"] + stats["cached"]
    print(f"coverage: {total}/{total + stats['fail'] + stats['tiny']}")


if __name__ == "__main__":
    main()
