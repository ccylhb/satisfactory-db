# -*- coding: utf-8 -*-
"""Satisfactory scraper — satisfactory.fandom.com.

Boards: items / buildings.
Per item: first Infobox simple + ALL {{CraftingTable}} recipes (with
alternate recipes) parsed into a recipes array. Routing is by source
category. Redirects resolved via redirects=1.
"""
import json, os, re, sys, time, urllib.request, urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "src", "data")
CACHE_DIR = os.path.join(BASE_DIR, "scripts", "cache")
API = "https://satisfactory.fandom.com/api.php"
UA = "SatisfactoryDB/1.0 (site: satisfactory-db.pages.dev; contact franceiwhdbks865@gmail.com)"

FETCH_CATS = {
    "items": ["Items", "Crafting components", "Equipment materials", "Fuels"],
    "buildings": ["Buildings", "Logistics buildings"],
}

num_re = re.compile(r"-?\d+(?:\.\d+)?")


def num(v):
    if v is None:
        return None
    m = num_re.search(v)
    return float(m.group(0)) if m else None


def strip_comments(wt):
    wt = re.sub(r"<!--.*?-->", "", wt, flags=re.S)
    return wt


def opener():
    return urllib.request.build_opener()


def opener_proxy():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": "http://127.0.0.1:7897",
                                     "http": "http://127.0.0.1:7897"}))


OP = opener()


def api(p, retry_proxy=True):
    global OP
    url = API + "?" + urllib.parse.urlencode({**p, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        return json.load(OP.open(req, timeout=40))
    except Exception as e:
        if retry_proxy:
            print("  [net] direct failed, switching to proxy:", str(e)[:50])
            OP = opener_proxy()
            return api(p, retry_proxy=False)
        raise


def extract_templates(wt, name_re):
    """Yield bodies of top-level templates whose name matches name_re."""
    wt = strip_comments(wt)
    out = []
    for m in re.finditer(r"\{\{\s*([A-Za-z][A-Za-z0-9 _/]{0,50}?)\s*(\||\n|\})", wt):
        name = m.group(1).strip()
        if not re.search(name_re, name, flags=re.I):
            continue
        start = m.start() + 2
        depth, i = 1, start
        while i < len(wt) - 1 and depth > 0:
            if wt[i] == "{":
                depth += 1
            elif wt[i] == "}":
                depth -= 1
            i += 1
        body = wt[start:i - 1]
        if body.count("=") >= 2:
            out.append((name, body))
    return out


def split_params(body):
    parts, buf = [], []
    depth_t = depth_l = 0
    i = 0
    while i < len(body):
        c = body[i]
        if c == "|" and depth_t == 0 and depth_l == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(c)
            if body.startswith("{{", i): depth_t += 1; i += 1
            elif body.startswith("}}", i): depth_t -= 1; i += 1
            elif body.startswith("[[", i): depth_l += 1; i += 1
            elif body.startswith("]]", i): depth_l -= 1; i += 1
        i += 1
    parts.append("".join(buf))
    return parts


def parse_params(body):
    out = {}
    for part in split_params(body):
        part = part.strip()
        if part.startswith("|"):
            part = part[1:]
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip().lower()
        if not k or k in out:
            continue
        out[k] = v.strip()
    return out


def clean(v):
    if not v:
        return ""
    v = strip_comments(v)
    v = re.sub(r"<br\s*/?>", "; ", v)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"\[\[([^|\]]*\|)?([^\]]*)\]\]", r"\2", v)
    v = re.sub(r"\[(https?://\S+)\s+([^\]]+)\]", r"\2", v)
    v = re.sub(r"\[(https?://\S+)\]", "", v)
    v = v.replace("'''", "").replace("''", "")
    # 兜底：清掉被截断的模板尾巴与孤立括号（残留形如 '…Manufacturer.{{craftingTable'）
    v = re.sub(r"\{\{[^{}]*$", "", v)
    v = v.replace("}}", "").replace("{{", "")
    return re.sub(r"\s+", " ", v).strip()


def clean_link(v):
    """Clean but keep [[link]] text as plain name."""
    if not v:
        return ""
    v = strip_comments(v)
    v = re.sub(r"\[\[([^|\]]*\|)?([^\]]*)\]\]", r"\2", v)
    v = re.sub(r"\{\{([^|{}]*\|)?([^{}]*)\}\}", r"\2", v)
    v = re.sub(r"<[^>]+>", "", v)
    return re.sub(r"\s+", " ", v).strip()


def drop_leading_templates(t: str) -> str:
    """按括号深度剥掉开头的连续模板块（含前置的 [[File:...]]）。

    旧写法用 re.search 定位「第一个右括号对」来跳过 infobox：只要 infobox 里
    有嵌套模板、或正文中出现内联模板，就会切在模板内部，正文变成 '}}' /
    'to unlock.' / 'and 4 x |recoverytime=...' 这类残渣（跨站上千条）。
    """
    while True:
        t = re.sub(r"^\s*\[\[(?:File|Image):[^\]]*\]\]\s*", "", t)
        m = re.search(r"\{\{", t)
        if not m or t[: m.start()].strip():
            return t
        depth, j = 0, m.start()
        while j < len(t):
            if t[j] == "{":
                depth += 1
            elif t[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        t = t[: m.start()] + t[j + 1 :]


def first_para(wt):
    body = drop_leading_templates(strip_comments(wt))
    for ln in body.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith(("=", "{", "|", "[[", "<", "#")):
            return clean(ln)[:400]
    return ""


def cat_members(cat):
    titles, cont = [], {}
    while True:
        r = api({"action": "query", "list": "categorymembers", "cmtitle": "Category:" + cat,
                 "cmtype": "page", "cmnamespace": "0", "cmlimit": "500", **cont})
        titles += [m["title"] for m in r.get("query", {}).get("categorymembers", [])]
        cont = r.get("continue") or {}
        if not cont:
            return titles
        time.sleep(0.4)


# --- wiki 魔术字展开 ---------------------------------------------------------
# 清洗器用 re.sub(r"\{\{[^{}]*\}\}", "", v) 整段删无名模板，{{PAGENAME}}（条目名）
# 随之消失，正文出现 "The is a ..." 残句。必须在清洗前展开成真实文本。
_MAGIC_TITLE = re.compile(r"\{\{\s*(?:SUB|BASE|FULL)?PAGENAME(?:E)?\s*\}\}", re.I)
_MAGIC_GAME = re.compile(r"\{\{\s*(?:Gamename|Game|SITENAME|Sitename)\s*\}\}", re.I)
_MAGIC_DROP = re.compile(
    r"\{\{\s*(?:DISPLAYTITLE|DEFAULTSORT|#(?:expr|var|if|ifeq|ifexist|switch|tag|invoke|time|pos|len|replace|sub|explode|titleparts)[^}]*)\}\}",
    re.I,
)


def expand_magic(wt, title):
    """把 {{PAGENAME}} 换成条目名，丢弃解析器函数等元魔术字。"""
    if not wt:
        return wt
    wt = _MAGIC_TITLE.sub(lambda _m: title, wt)
    wt = _MAGIC_GAME.sub("Satisfactory", wt)
    wt = _MAGIC_DROP.sub("", wt)
    return wt


def fetch_wikitexts(titles, cache_path):
    wts = {}
    if os.path.exists(cache_path):
        wts = json.load(open(cache_path, encoding="utf-8"))
    titles = [t for t in titles if t not in wts]
    if not titles:
        return wts
    batch = 15
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        r = None
        for attempt in range(3):
            try:
                r = api({"action": "query", "prop": "revisions", "rvprop": "content",
                         "rvslots": "main", "redirects": 1, "titles": "|".join(chunk)})
                break
            except Exception as e:
                print(f"  [batch {i}] ERR {str(e)[:50]}, retry {attempt + 1}")
                time.sleep(3)
        if not r:
            continue
        q = r.get("query", {})
        for pg in q.get("pages", {}).values():
            rev = pg.get("revisions") or []
            wts[pg["title"]] = rev[0]["slots"]["main"]["*"] if rev else ""
        if (i // batch) % 10 == 0:
            print(f"  fetched {min(i + batch, len(titles))}/{len(titles)}")
        time.sleep(0.35)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    json.dump(wts, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    return wts


def parse_recipes(wt):
    """Parse all CraftingTable templates into recipe dicts."""
    recipes = []
    for name, body in extract_templates(wt, r"craftingtable|crafting\b"):
        p = parse_params(body)
        ingredients = []
        for i in range(1, 5):
            ing = p.get(f"ingredient{i}")
            qty = p.get(f"quantity{i}")
            if ing:
                ingredients.append({"name": clean_link(ing), "qty": num(qty)})
        recipes.append({
            "name": clean_link(p.get("recipename", "")),
            "alternate": (p.get("alternaterecipe", "") or "").lower() in ("1", "true", "yes"),
            "crafted_in": clean_link(p.get("craftedin", "")),
            "craft_time": num(p.get("craftingtime")),
            "product": clean_link(p.get("product", "")),
            "product_count": num(p.get("productcount")),
            "tier": clean(p.get("researchtier", "")),
            "ingredients": ingredients,
        })
    return recipes


def slug(t):
    s = re.sub(r"\s+", "-", t.strip().lower())
    return re.sub(r"[^a-z0-9\-]", "", s) or "item"


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    board_titles = {}
    for board, cats in FETCH_CATS.items():
        ts = set()
        for c in cats:
            got = cat_members(c)
            print(f"[cat] {board} <- {c}: {len(got)}")
            ts.update(got)
            time.sleep(0.3)
        board_titles[board] = sorted(ts)
    all_titles = sorted({t for ts in board_titles.values() for t in ts})
    print(f"[total] {len(all_titles)} unique pages")
    cache = os.path.join(CACHE_DIR, "wikitexts.json")
    wts = fetch_wikitexts(all_titles, cache)
    # 展开 wiki 魔术字（缓存保持原始，每次解析重展开，便于回滚）
    wts = {t: expand_magic(wt, t) for t, wt in wts.items()}
    global_seen = set()
    for board, titles in board_titles.items():
        out = []
        seen = set()
        for t in titles:
            key = slug(t)
            if key in seen or key in global_seen:
                continue
            wt = wts.get(t, "")
            if not wt or wt.startswith("#REDIRECT"):
                continue
            infos = extract_templates(wt, r"infobox")
            if not infos:
                continue
            tname, body = infos[0]
            seen.add(key)
            global_seen.add(key)
            p = parse_params(body)
            recipes = parse_recipes(wt) if board == "items" else []
            rec = {
                "title": t, "slug": key, "template": tname,
                "image": clean(p.get("image", "")),
                "fields": {k: clean(v) for k, v in p.items() if k != "image"},
                "intro": first_para(wt),
                "recipes": recipes,
            }
            out.append(rec)
        path = os.path.join(DATA_DIR, f"satisfactory_{board}.json")
        json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[out] {board}: {len(out)}")


if __name__ == "__main__":
    main()
