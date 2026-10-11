#!/usr/bin/env python3
"""fb_collabnet — the Facebook analog of collabnet: walk a network of FB accounts, one after the next.

Metadata only, nothing downloaded, READ-ONLY (it scrolls a profile and reads what Facebook
sends; it never clicks, likes, comments, follows or messages). Default login: JustinR
(conf/facebook.justinriggs.cookies.txt), the one account TB hasn't blocked (2026-10-10).

Facebook has no "Collaborators" field like Instagram. What it does have, per post, and what
this script records as links between accounts:

  coauthor     the post has more than one author (FB "collaborative" posts: actors > 1)
  with         the header line names people: "Tim Ballard is with Julie Teron."
  shared_from  the post shares someone else's post (its attached story's author)
  mention      @-tags inside the post text (kept in the data; only on the graph with --mentions)

Comments, reactions and the viewer's own notifications are NOT read (2026-10-10: a reel in
JustinR's notification menu was once mistaken for a Tim post; posts here come only from
Facebook's own feed data for the profile).

For each account in a queue file:
  1. scrape     scroll its profile, read the feed data -> outputs/fb_timelines/<key>_<date>/<key>_posts.jsonl
                (skipped if we already have a scrape of it; --refresh scrapes again)
  2. word sort  bin/ig_word_sort.py on it -> <run>/word_sorts/<key>_word_sort.txt
then waits a random few minutes (--gap) before the next one. When the whole queue is done it
draws ONE graph (key + colour-banded edges, dated copy in graph/history/), as collabnet does.

Accounts that stop at the scroll cap (--rounds) before the feed ends are logged CAPPED.

Queue file: one account per line, anything after # is a comment. An account is a page/profile
name as in its URL (officialtimballard, JulieCTeron), a numeric profile id, or a full URL
(https://www.facebook.com/profile.php?id=61570960377083).
--snowball appends each account's new coauthor/with/shared_from partners to the queue.

Run folder: ~/Desktop/claude/<today>/fb_collabnet_<queue name>/
    run_<time>.log  status.tsv  word_sorts/  graph/ (collab_graph.png/.html, edges.tsv, nodes.tsv, history/)

Usage:
    python bin/fb_collabnet.py QUEUE.txt [--snowball] [--max-accounts 10] [--gap 3 6] [--pause 3 6]
        [--rounds 60] [--cookies conf/facebook.justinriggs.cookies.txt] [--refresh] [--mentions] [--dry-run]
    python bin/fb_collabnet.py --parse-capture DIR OWNER   (offline: parse saved graphql_*.json/page.html)
    fbcollabnet QUEUE.txt ...      (wrapper in ~/.local/bin: activates the env)
"""
import argparse
import collections
import glob
import html
import importlib.util
import json
import random
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TIMELINES = REPO / "outputs" / "fb_timelines"
sys.path.insert(0, str(REPO))

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
GRAPH_RELATIONS = ("coauthor", "with", "shared_from")
SCRIPT_JSON = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "bin" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- accounts ----------

def account_key(token):
    """'officialtimballard' / '61570960377083' / a facebook URL -> (key, url). Keys are lower-case."""
    token = token.strip()
    m = re.search(r"profile\.php\?id=(\d+)", token) or re.fullmatch(r"(?:id:)?(\d{6,})", token)
    if m:
        return m.group(1), f"https://www.facebook.com/profile.php?id={m.group(1)}"
    m = re.search(r"facebook\.com/(?:people/[^/]+/(\d+)|([A-Za-z0-9.\-]+))", token)
    if m:
        token = m.group(1) or m.group(2)
        if m.group(1):
            return token, f"https://www.facebook.com/profile.php?id={token}"
    return token.lower(), f"https://www.facebook.com/{token}"


def entity_key(ent):
    """FB user/page entity from the feed data -> (key, name). Vanity name from its URL, else its id."""
    url = ent.get("url") or ent.get("profile_url") or ent.get("mobileUrl") or ""
    m = re.search(r"facebook\.com/([A-Za-z0-9.\-]+)/?$", url)
    if m and m.group(1) not in ("profile.php", "people", "groups", "pages", "watch", "reel"):
        key = m.group(1).lower()
    else:
        m = re.search(r"id=(\d+)", url)
        key = m.group(1) if m else str(ent.get("id") or "")
    return key, ent.get("name") or ""


def read_queue(path):
    seen, out = set(), []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        tok = line.split("#", 1)[0].strip()
        if not tok:
            continue
        key, url = account_key(tok)
        if key not in seen:
            seen.add(key)
            out.append((key, url))
    return out


# ---------- parsing Facebook's feed data ----------

def json_blobs_from_text(text):
    """Every JSON object in a graphql response body (one per line) or in a page's <script> tags."""
    if "<script" in text[:5000] or "<html" in text[:200].lower():
        chunks = SCRIPT_JSON.findall(text)
    else:
        chunks = text.splitlines()
    for c in chunks:
        c = c.strip()
        if c.startswith("{"):
            try:
                yield json.loads(c)
            except ValueError:
                pass


def _walk(o, path=()):
    if isinstance(o, dict):
        yield path, o
        for k, v in o.items():
            yield from _walk(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, path + (i,))


def _entities(text_obj):
    """User/Page entities tagged in a {text, ranges} object."""
    out = []
    text = (text_obj or {}).get("text") or ""
    for r in (text_obj or {}).get("ranges") or []:
        ent = r.get("entity") or {}
        if ent.get("__typename") in ("User", "Page") and (ent.get("id") or ent.get("url")):
            key, name = entity_key(ent)
            # tagged entities carry only short_name ("Julie"); the full name is the tagged text itself
            off, ln = r.get("offset"), r.get("length")
            if isinstance(off, int) and isinstance(ln, int) and text[off:off + ln].strip():
                name = text[off:off + ln].strip()
            out.append((key, name or ent.get("short_name") or ""))
    return out


def _get(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def parse_story(st):
    """One top-level Story node -> post record (None if it has no author/time)."""
    actors = [entity_key(a) for a in st.get("actors") or [] if a.get("id")]
    if not actors or not st.get("creation_time"):
        return None
    cs = st.get("comet_sections") or {}
    title = _get(cs, "context_layout", "story", "comet_sections", "title", "story", "title")
    message = _get(cs, "content", "story", "comet_sections", "message", "story", "message") or st.get("message")
    author_keys = {k for k, _ in actors}
    rel = collections.OrderedDict()  # key -> (relation, name)
    for k, n in actors[1:]:
        rel.setdefault(k, ("coauthor", n))
    for k, n in _entities(title):
        if k not in author_keys:
            rel.setdefault(k, ("with", n))
    for att in (st.get("attached_story"), st.get("work_reposted_story")):
        for a in (att or {}).get("actors") or []:
            k, n = entity_key(a)
            if k and k not in author_keys:
                rel.setdefault(k, ("shared_from", n))
    for k, n in _entities(message):
        if k not in author_keys:
            rel.setdefault(k, ("mention", n))
    url = st.get("permalink_url") or ""
    return {
        "shortcode": str(st.get("post_id") or st.get("id")),
        "taken_at": int(st["creation_time"]),
        "url": url,
        "author": actors[0][0],
        "author_name": actors[0][1],
        "authors": [k for k, _ in actors],
        "title": (title or {}).get("text") or "",
        "caption": (message or {}).get("text") or "",
        "links": [{"account": k, "relation": r, "name": n} for k, (r, n) in rel.items()],
        # collaborators = graph links (so bin/ig_word_sort.py and friends read it like an IG timeline)
        "collaborators": [k for k, (r, _) in rel.items() if r in GRAPH_RELATIONS],
        "names": {k: n for k, n in actors + [(k, n) for k, (_r, n) in rel.items()] if n},
    }


def stories_in(blob):
    """Top-level Story nodes in one JSON blob (shared/attached stories are read via their parent)."""
    for path, d in _walk(blob):
        if (d.get("__typename") == "Story" and d.get("post_id") and "creation_time" in d
                and "attached_story" not in path and "work_reposted_story" not in path):
            yield d


def parse_texts(texts, owner):
    """{post_id: record} for posts authored (or co-authored) by owner, from response/page texts."""
    found = {}
    for t in texts:
        for blob in json_blobs_from_text(t):
            for st in stories_in(blob):
                rec = parse_story(st)
                if rec and (owner in rec["authors"] or not owner):
                    found.setdefault(rec["shortcode"], rec)
    return found


# ---------- scraping (read-only) ----------

def scrape(url, owner, cookies_path, max_rounds=60, pause=(3, 6), log=print):
    """Scroll one profile, collect its posts from the feed data. Returns (posts, how it ended, owner key)."""
    import http.cookiejar
    from playwright.sync_api import sync_playwright

    # read a copy: nothing should ever write back into the conf/ cookie file
    tmp = Path(tempfile.mkdtemp()) / "cookies.txt"
    shutil.copy(cookies_path, tmp)
    jar = http.cookiejar.MozillaCookieJar(str(tmp))
    jar.load(ignore_discard=True, ignore_expires=True)
    cookies = [dict(name=c.name, value=c.value, domain=c.domain, path=c.path, secure=bool(c.secure)) for c in jar if c.name]
    bodies = []

    def on_resp(r):
        if "/api/graphql" in r.url:
            try:
                bodies.append(r.text())
            except Exception:
                pass

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path="/usr/bin/google-chrome", args=["--headless=new"])
        ctx = b.new_context(viewport={"width": 1280, "height": 1400}, locale="en-US", user_agent=UA)
        ctx.add_cookies(cookies)
        pg = ctx.new_page()
        pg.on("response", on_resp)
        pg.goto(url, wait_until="commit", timeout=60000)
        pg.wait_for_timeout(8000)
        page = pg.content()
        if "isn't available" in pg.inner_text("body")[:3000] or "/login" in pg.url:
            b.close()
            return {}, "unavailable (blocked, private, or not logged in)", owner
        # the profile's own id/vanity: the author most of its first posts share
        first = parse_texts([page] + bodies, None)
        # (a page's posts can name it by id rather than the vanity name in its URL)
        if first and owner not in {a for r in first.values() for a in r["authors"]}:
            owner = collections.Counter(r["author"] for r in first.values()).most_common(1)[0][0]
        posts, still, ended = {}, 0, "max_rounds"
        for i in range(max_rounds):
            new = parse_texts([page] + bodies, owner)
            bodies.clear()
            page = ""
            added = {k: v for k, v in new.items() if k not in posts}
            posts.update(added)
            still = 0 if added else still + 1
            if i % 5 == 0 or added:
                log(f"      round {i + 1}: +{len(added)} (total {len(posts)})")
            if still >= 5:
                ended = "feed_end"
                break
            pg.mouse.wheel(0, random.randint(1300, 1800))
            pg.wait_for_timeout(random.uniform(*pause) * 1000)
        b.close()
    return posts, ended, owner


# ---------- graph ----------

def load_timelines(root=None):
    """{account: newest posts.jsonl}"""
    root = root or TIMELINES
    found = collections.defaultdict(list)
    for p in root.glob("*_*/*_posts.jsonl"):
        if p.stat().st_size:
            found[p.name[: -len("_posts.jsonl")]].append(p)
    return {a: max(ps, key=lambda p: p.stat().st_mtime) for a, ps in found.items()}


def build_edges(files, relations):
    """Edges between a post's author(s) and every linked account, a post counted once (by id)."""
    posts, names = {}, {}
    for acct, path in files.items():
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                names.update(r.get("names") or {})
                rec = posts.setdefault(r["shortcode"], {"r": r, "seen_in": set()})
                rec["seen_in"].add(acct)
    edges = {}
    for code, rec in posts.items():
        r = rec["r"]
        for a in r["authors"]:
            for l in r["links"]:
                if l["relation"] not in relations or l["account"] == a:
                    continue
                pair = tuple(sorted((a, l["account"])))
                e = edges.setdefault(pair, {"n": 0, "first": None, "last": None, "codes": [], "relations": collections.Counter()})
                e["n"] += 1
                e["relations"][l["relation"]] += 1
                t = r["taken_at"]
                e["first"] = t if e["first"] is None else min(e["first"], t)
                e["last"] = t if e["last"] is None else max(e["last"], t)
                if len(e["codes"]) < 3:
                    e["codes"].append(r.get("url") or code)
    return edges, names, posts


def step_graph(queue_keys, run_dir, relations):
    cg = _load("ig_collab_graph")
    files = load_timelines()
    edges, names, posts = build_edges(files, relations)
    touching = set(queue_keys)
    edges = {k: v for k, v in edges.items() if set(k) & touching}
    out = run_dir / "graph"
    out.mkdir(parents=True, exist_ok=True)
    if not edges:
        (out / "NO_LINKS.txt").write_text(f"No {', '.join(relations)} links found for: {', '.join(queue_keys)}\n")
        return 0, 0
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t else ""
    nodes = sorted({n for k in edges for n in k})
    shared, partners = collections.Counter(), collections.Counter()
    for (a, b), e in edges.items():
        shared[a] += e["n"]; shared[b] += e["n"]; partners[a] += 1; partners[b] += 1
    with open(out / "edges.tsv", "w", encoding="utf-8") as fh:
        fh.write("a\tb\tposts\trelations\tfirst\tlast\texamples\n")
        for (a, b), e in sorted(edges.items(), key=lambda kv: -kv[1]["n"]):
            rels = ",".join(f"{k} {v}" for k, v in e["relations"].most_common())
            fh.write(f"{a}\t{b}\t{e['n']}\t{rels}\t{day(e['first'])}\t{day(e['last'])}\t{' '.join(e['codes'])}\n")
    with open(out / "nodes.tsv", "w", encoding="utf-8") as fh:
        fh.write("account\tname\tscraped\tpartners\tposts_linked\n")
        for n in sorted(nodes, key=lambda n: -shared[n]):
            fh.write(f"{n}\t{names.get(n, '')}\t{'y' if n in files else 'n'}\t{partners[n]}\t{shared[n]}\n")
    title = (f"Facebook links ({' / '.join(relations)}) — {len(touching)} accounts and their partners · "
             f"{len(nodes)} accounts, {len(edges)} links · {date.today().isoformat()}")
    label_names = {n: (names[n], "fb") for n in nodes if names.get(n)}
    cg.draw(edges, set(files), out / "collab_graph.png", 25, title, names=label_names, label_all=len(nodes) <= 40)

    import base64
    png64 = base64.b64encode((out / "collab_graph.png").read_bytes()).decode()

    def table(name):
        rows = (out / name).read_text(encoding="utf-8").splitlines()
        head, body = rows[0].split("\t"), [r.split("\t") for r in rows[1:]]
        return ("<table><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in head) + "</tr>" +
                "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in body) + "</table>")
    (out / "collab_graph.html").write_text(f"""<!doctype html><meta charset="utf-8"><title>FB collab graph</title>
<style>body{{background:#12151c;color:#e6e8ee;font:14px/1.4 system-ui,sans-serif;margin:24px}}
img{{max-width:100%}}table{{border-collapse:collapse;margin:12px 0 32px}}td,th{{border-bottom:1px solid #2e3544;padding:4px 10px;text-align:left}}
th{{color:#a2a9b8}}</style><h1>{html.escape(title)}</h1>
<p>Sources: {len(files)} scrapes in outputs/fb_timelines/ · {len(posts)} unique posts · bin/fb_collabnet.py.
A "post" on a line = one Facebook post where the two accounts are linked as {', '.join(relations)}.</p>
<img src="data:image/png;base64,{png64}"><h2>Accounts</h2>{table("nodes.tsv")}<h2>Links</h2>{table("edges.tsv")}""",
                                         encoding="utf-8")
    hist = out / "history"
    hist.mkdir(exist_ok=True)
    stamp = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{len(nodes)}a_{len(edges)}l"
    for name in ("collab_graph.png", "edges.tsv", "nodes.tsv"):
        shutil.copy2(out / name, hist / f"{stamp}_{name}")
    return len(nodes), len(edges)


# ---------- run ----------

class Log:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")

    def __call__(self, msg):
        line = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()


def existing(key):
    c = [p for p in TIMELINES.glob(f"{key}_*/{key}_posts.jsonl") if p.stat().st_size]
    return max(c, key=lambda p: p.stat().st_mtime) if c else None


def write_posts(key, posts):
    outdir = TIMELINES / f"{key}_{date.today().isoformat()}"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{key}_posts.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for r in sorted(posts.values(), key=lambda r: r["taken_at"]):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("queue", nargs="?")
    ap.add_argument("--cookies", default=str(REPO / "conf" / "facebook.justinriggs.cookies.txt"))
    ap.add_argument("--rounds", type=int, default=60, help="max scroll rounds per account (default 60)")
    ap.add_argument("--gap", type=float, nargs=2, default=[3, 6], metavar=("MIN", "MAX"))
    ap.add_argument("--pause", type=float, nargs=2, default=[3, 6], metavar=("MIN", "MAX"))
    ap.add_argument("--snowball", action="store_true")
    ap.add_argument("--max-accounts", type=int, default=10)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--mentions", action="store_true", help="also draw @-mention links on the graph")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--parse-capture", nargs=2, metavar=("DIR", "OWNER"), help="offline: parse saved responses, print posts")
    args = ap.parse_args(argv)

    if args.parse_capture:
        d, owner = args.parse_capture
        texts = [Path(f).read_text(encoding="utf-8") for f in sorted(glob.glob(f"{d}/*.json")) + sorted(glob.glob(f"{d}/*.html"))]
        posts = parse_texts(texts, owner.lower())
        for r in sorted(posts.values(), key=lambda r: r["taken_at"], reverse=True):
            links = ", ".join(f"{l['relation']}:{l['account']}({l['name']})" for l in r["links"])
            print(f"{datetime.fromtimestamp(r['taken_at'], timezone.utc):%Y-%m-%d %H:%M}Z  {r['shortcode']}  "
                  f"{r['title'] or r['author_name']!r}  {links}")
        print(f"{len(posts)} posts")
        return 0
    if not args.queue:
        ap.error("QUEUE is required")

    relations = GRAPH_RELATIONS + (("mention",) if args.mentions else ())
    word_sort = _load("ig_word_sort")
    queue_path = Path(args.queue).resolve()
    run_dir = Path.home() / "Desktop" / "claude" / date.today().isoformat() / f"fb_collabnet_{queue_path.stem}"
    log = Log(run_dir / f"run_{datetime.now().strftime('%H%M%S')}.log")
    log(f"fb_collabnet  queue {queue_path}")
    log(f"  run folder {run_dir}")
    log(f"  cookies {args.cookies}  rounds {args.rounds}  gap {args.gap} min  pause {args.pause} s  "
        f"snowball {args.snowball}  max {args.max_accounts}  graph relations {','.join(relations)}"
        f"{'  DRY RUN' if args.dry_run else ''}")
    scraped, i = 0, 0
    try:
        while True:
            queue = read_queue(queue_path)
            if i >= len(queue):
                break
            key, url = queue[i]
            i += 1
            tag = f"[{i}/{len(queue)}] {key}"
            timeline, n = existing(key), 0
            if timeline and not args.refresh:
                status, n = "had", sum(1 for _ in open(timeline, encoding="utf-8"))
                log(f"{tag}: have it ({timeline.relative_to(REPO)}, {n} posts)")
            elif scraped >= args.max_accounts:
                log(f"reached --max-accounts {args.max_accounts}; {len(queue) - i + 1} left in the queue")
                break
            elif args.dry_run:
                log(f"{tag}: would scrape {url}")
                continue
            else:
                if scraped:
                    wait = random.uniform(*args.gap) * 60
                    log(f"    waiting {wait / 60:.1f} min before {key}")
                    time.sleep(wait)
                log(f"{tag}: scraping {url}")
                try:
                    posts, ended, owner = scrape(url, key, args.cookies, args.rounds, args.pause, log)
                    if owner != key:
                        log(f"    (Facebook calls this account '{owner}'; saving under '{key}')")
                    status = ("empty" if not posts and ended in ("feed_end", "max_rounds") else
                              "complete" if ended == "feed_end" else "CAPPED" if ended == "max_rounds" else ended)
                    n = len(posts)
                    timeline = write_posts(key, posts) if posts else None
                except Exception as e:
                    timeline, n, status = None, 0, f"error: {e!r}"[:200]
                scraped += 1
                log(f"    {status}, {n} posts" + (f" -> {timeline.relative_to(REPO)}" if timeline else ""))
            ws = ""
            if timeline and n and not args.dry_run:
                ws = run_dir / "word_sorts" / f"{key}_word_sort.txt"
                ws.parent.mkdir(parents=True, exist_ok=True)
                ws.write_text(word_sort.render(key, timeline, word_sort.load_posts(timeline), 40) + "\n", encoding="utf-8")
                counts = collections.Counter()
                for line in open(timeline, encoding="utf-8"):
                    for l in json.loads(line)["links"]:
                        counts[(l["relation"], l["account"], l["name"])] += 1
                for (rel, acct, name), c in counts.most_common(15):
                    log(f"      {rel:<11} {acct:<30} {name}  ({c} posts)")
                if args.snowball:
                    have = {k for k, _ in read_queue(queue_path)}
                    new = collections.Counter()
                    for (rel, acct, name), c in counts.items():
                        if rel in GRAPH_RELATIONS and acct not in have:
                            new[(acct, name)] += c
                    if new:
                        with open(queue_path, "a", encoding="utf-8") as fh:
                            for (acct, name), c in new.most_common():
                                fh.write(f"{acct:<30}# {name}, from {key}, {c} posts\n")
                        log(f"    + {len(new)} new accounts queued: {', '.join(a for a, _ in new)}")
            with open(run_dir / "status.tsv", "a", encoding="utf-8") as fh:
                fh.write(f"{key}\t{status}\t{n}\t{timeline or ''}\t{ws}\t"
                         f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
    except KeyboardInterrupt:
        log("stopped (Ctrl-C). Run the same command again to carry on.")
        return 130
    if not args.dry_run:
        a, l = step_graph([k for k, _ in read_queue(queue_path)], run_dir, relations)
        log(f"graph: {a} accounts, {l} links -> {run_dir / 'graph' / 'collab_graph.html'}" if l
            else f"graph: no {'/'.join(relations)} links found, nothing drawn")
    log(f"finished: {scraped} scraped this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
