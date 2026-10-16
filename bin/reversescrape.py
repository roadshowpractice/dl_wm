#!/usr/bin/env python3
"""reversescrape: an Instagram account's posts OLDEST FIRST, starting at its very first post.

collabnet / igp.profile_history start at today and scroll back, so a capped run never
reaches an old account's beginning. This goes the other way:

  1. FIRST POST. Instagram post ids carry their creation time ((id >> 23) + IG_EPOCH_MS),
     so "posts older than date T" is one request with a made-up cursor for T. A binary
     search on T (about 13 requests) finds the account's first post.
  2. FORWARD WALK. From there, window by window: ask for posts older than the window's
     end, page back until the window's start is reached, and write the new posts,
     oldest first, the moment they're found. The window grows or shrinks to keep about
     20 posts per window.

Each post also gets id_time (the time built into its id). A post whose taken_at is more
than an hour from its id_time is flagged DATE MISMATCH: the server stamps the id, the
poster can't set it.

Metadata only (no media). Headless Chromium with logged-in cookies, images blocked; the
requests are the web app's own timeline query (copied from one scroll of the profile page), replayed
from inside the logged-in page with our cursor. Between requests it acts like someone looking at the
page: mouse drifts, small scrolls, a random pause (--pause, default 3-7 s), and a 15-40 s "read"
every 10-20 requests.

Stuck logins: if a login hits an HTTP error, a login wall or a non-JSON answer, the tool moves
to the next cookie file (--cookies files first, in order, then conf/app_config.json's Instagram
cookie_hierarchy; logged-out files skipped) and carries on from where it stopped. The run.log
and summary.json name every login used (file + ds_user_id, never cookie values). If every login
is stuck, the run ends with "I NEED COOKIES" and the --from date to resume at.

Usage:
    reversescrape <username> [--cookies FILE ...] [--until YYYY-MM-DD] [--from YYYY-MM-DD]
                  [--pause 3 7] [--max-requests 800]

  --until   stop once the walk reaches this date (default: today)
  --from    skip the first-post search and start the walk here

Writes outputs/ig_timelines/<username>_<UTC date>_reverse[_HHMM]/ (never overwrites):
  <username>_timeline.jsonl   one post per line, oldest first. Incidence + origin only: shortcode,
                              taken_at, id_time, collaborators, credits (@handles named in the
                              caption; the caption itself is not kept), date_mismatch when set
  <username>_timeline.pages.jsonl  while running: every page as it arrives (cursor + posts); a killed run keeps it,
                              `--resume DIR` carries on from its last cursor; deleted when the walk finishes
  dropped.jsonl               items the owner filter left out: shortcode, time, user, coauthors (nothing else)
  errors.jsonl                only if a request fails: that response, cut to 2000 characters
  run.log                     console output
  summary.json                first post, counts, how the run ended, date mismatches
"""
import argparse
import asyncio
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from igp.cookies import load_netscape_cookies  # noqa: E402

IG_EPOCH_MS = 1314220021721            # checked 2026-10-16: B1/B6/B7 ids land within a minute of taken_at
APP_ID = "936619743392459"             # the web app's X-IG-App-ID
IG_LAUNCH = datetime(2010, 10, 6, tzinfo=timezone.utc).timestamp()
SHORTCODE_ABC = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
TARGET_PER_WINDOW = 20


def id_time(pk):
    return ((int(pk) >> 23) + IG_EPOCH_MS) / 1000


def shortcode_pk(code):
    n = 0
    for c in code[:11]:
        n = n * 64 + SHORTCODE_ABC.index(c)
    return n


def cursor_for(t, uid, style):
    pk = int(t * 1000 - IG_EPOCH_MS) << 23
    return f"{pk}_{uid}" if style == "pk_uid" else str(pk)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def credits_in(caption):
    """The @handles a caption names, in order (B7: "Cred: @king__mosiah @latterdayavenger")."""
    return list(dict.fromkeys(m.lower() for m in re.findall(r"(?<![\w.])@([A-Za-z0-9_.]*[A-Za-z0-9_])", caption or "")))


MASK = ("shortcode", "taken_at", "id_time", "collaborators", "credits", "date_mismatch")


def post_record(item, owner):
    """Incidence + origin only: shortcode, taken_at, id_time, collaborators, credits (@handles in the
    caption), date_mismatch when set. Nothing else is kept. None if the item isn't the owner's."""
    code = item.get("code")
    if not code or "taken_at" not in item:
        return None
    post_owner = (item.get("user") or item.get("owner") or {}).get("username")
    collabs = sorted({u.get("username") for k in ("coauthor_producers", "invited_coauthor_producers")
                      for u in (item.get(k) or []) if isinstance(u, dict) and u.get("username")})
    if post_owner and post_owner != owner and owner not in collabs:
        return None
    cap = item.get("caption")
    cap = cap.get("text", "") if isinstance(cap, dict) else (cap or "")
    pk = item.get("pk") or shortcode_pk(code)
    rec = {"shortcode": code, "taken_at": item["taken_at"], "id_time": round(id_time(pk)),
           "collaborators": collabs, "credits": credits_in(cap)}
    if abs(rec["taken_at"] - rec["id_time"]) > 3600:
        rec["date_mismatch"] = True
    return rec


TIMELINE_KEY = "xdt_api__v1__feed__user_timeline_graphql_connection"


class Session:
    """Replays the web app's own timeline query (captured from one scroll of the profile page) with
    our cursor in `after`. The REST endpoints (api/v1/users/web_profile_info, feed/user) answer 429
    to this login; the web app's GraphQL query is what the scroll scraper reads, and it works."""

    def __init__(self, page, username, errors, say, pause, max_requests):
        self.page, self.username, self.errors, self.say = page, username, errors, say
        self.pause, self.max_requests, self.n = pause, max_requests, 0
        self.uid = self.style = self.template = None

    async def capture_template(self):
        """Scroll the profile until the page itself asks for a page of the timeline; keep that request."""
        seen = {}

        async def on_response(resp):
            try:
                if "/graphql/query" in resp.url and resp.request.method == "POST":
                    text = await resp.text()
                    if TIMELINE_KEY in text:
                        req = resp.request
                        seen.setdefault("all", []).append((req.post_data or "", await req.all_headers(), text))
            except Exception:
                pass
        self.page.on("response", on_response)
        for _ in range(8):
            if any("after" in v for v, _, _ in [(pd, h, t) for pd, h, t in seen.get("all", [])]):
                break
            await self.page.mouse.wheel(0, 3000)
            await asyncio.sleep(random.uniform(*self.pause))
        self.page.remove_listener("response", on_response)
        caps = seen.get("all", [])
        if not caps:
            raise Stuck("the profile page never asked for its timeline (login wall or block?)")
        pd, headers, text = next(((pd, h, t) for pd, h, t in caps if "after" in pd), caps[0])
        from urllib.parse import parse_qsl
        form = dict(parse_qsl(pd, keep_blank_values=True))
        self.template = {"form": form, "variables": json.loads(form["variables"]),
                         "headers": {k: v for k, v in headers.items()
                                     if not k.startswith(":") and k.lower() not in ("cookie", "content-length", "host")}}
        recs, nxt, uid = self.parse(json.loads(text))
        self.uid = uid
        self.real_next = nxt
        self.say(f"  page cursor looks like {str(nxt)[:12]}...{str(nxt)[-14:]} (len {len(str(nxt))}); "
                 f"variables keys {sorted(self.template['variables'])}")
        self.say(f"timeline query captured ({form.get('fb_api_req_friendly_name', '?')}), user id {uid}")
        return recs

    def parse(self, d):
        conn = (d.get("data") or {}).get(TIMELINE_KEY) or {}
        items = [e.get("node") or {} for e in conn.get("edges") or []]
        recs = []
        for i in items:
            r = post_record(i, self.username)
            if r:
                recs.append(r)
            elif i.get("code") and getattr(self, "dropped_file", None):   # say what the owner filter dropped
                with open(self.dropped_file, "a") as f:
                    f.write(json.dumps({"shortcode": i.get("code"), "taken_at": i.get("taken_at"),
                                        "user": (i.get("user") or i.get("owner") or {}).get("username"),
                                        "coauthors": sorted({u.get("username") for k in ("coauthor_producers", "invited_coauthor_producers")
                                                             for u in (i.get(k) or []) if isinstance(u, dict)} - {None})}) + "\n")
        info = conn.get("page_info") or {}
        nxt = info.get("end_cursor") if info.get("has_next_page") else None
        uid = next((str((i.get("user") or {}).get("pk") or (i.get("user") or {}).get("id")) for i in items
                    if (i.get("user") or {}).get("username") == self.username), None)
        if not uid and info.get("end_cursor") and "_" in info["end_cursor"]:
            uid = info["end_cursor"].split("_", 1)[1]
        return recs, nxt, uid

    async def look(self):
        """Act like someone looking at the page between requests: drift the mouse, scroll a little
        (now and then back up), wait --pause, and every 10-20 requests stop to 'read' for 15-40 s."""
        if self.n >= getattr(self, "next_read", 0):
            if self.n:
                await asyncio.sleep(random.uniform(15, 40))
            self.next_read = self.n + random.randint(10, 20)
        try:
            for _ in range(random.randint(1, 3)):
                await self.page.mouse.move(random.uniform(150, 870), random.uniform(120, 700), steps=random.randint(5, 15))
                await asyncio.sleep(random.uniform(0.2, 0.9))
            await self.page.mouse.wheel(0, random.choice([1, 1, 1, -1]) * random.uniform(200, 900))
        except Exception:
            pass
        await asyncio.sleep(random.uniform(*self.pause))

    async def fetch_page(self, cursor):
        if self.n >= self.max_requests:
            raise RuntimeError(f"hit --max-requests {self.max_requests}")
        if self.n:
            await self.look()
        self.n += 1
        from urllib.parse import urlencode
        v = dict(self.template["variables"]); v["after"] = cursor
        v.pop("before", None); v["first"] = v.get("first") or 12
        body = urlencode({**self.template["form"], "variables": json.dumps(v, separators=(",", ":"))})
        r = await self.page.evaluate("""async ([body, headers]) => {
            const r = await fetch("/graphql/query", {method: "POST", credentials: "include", headers, body});
            return {status: r.status, ctype: r.headers.get("content-type") || "", text: await r.text()};
        }""", [body, self.template["headers"]])
        try:
            if r["status"] != 200:
                raise Stuck(f"HTTP {r['status']}")
            d = json.loads(r["text"].removeprefix("for (;;);"))
            if d.get("status") == "fail" or (d.get("errors") and not d.get("data")):
                raise Stuck(f"Instagram said: {str(d.get('message') or d.get('errors'))[:200]}")
            return d
        except Exception as e:                       # keep only what a failure needs for offline debugging
            with open(self.errors, "a") as f:
                f.write(json.dumps({"seq": self.n, "at_utc": iso(time.time()), "cursor": cursor, "status": r["status"],
                                    "ctype": r["ctype"], "text": r["text"][:2000]}, ensure_ascii=False) + "\n")
            raise e if isinstance(e, Stuck) else Stuck(f"{e}: {r['text'][:200]!r}")

    async def fetch_rest(self, max_id):
        """The old feed endpoint, which takes post-id cursors (so a made-up date cursor works there)."""
        if self.n >= self.max_requests:
            raise RuntimeError(f"hit --max-requests {self.max_requests}")
        await self.look(); self.n += 1
        url = f"/api/v1/feed/user/{self.uid}/?count=12" + (f"&max_id={max_id}" if max_id else "")
        r = await self.page.evaluate("""async ([url, app]) => {
            const r = await fetch(url, {credentials: "include", headers: {"X-IG-App-ID": app, "X-Requested-With": "XMLHttpRequest"}});
            return {status: r.status, ctype: r.headers.get("content-type") || "", text: await r.text()};
        }""", [url, APP_ID])
        try:
            if r["status"] != 200:
                raise Stuck(f"HTTP {r['status']} on the feed endpoint")
            d = json.loads(r["text"])
        except Exception as e:
            with open(self.errors, "a") as f:
                f.write(json.dumps({"seq": self.n, "at_utc": iso(time.time()), "url": url, "status": r["status"],
                                    "ctype": r["ctype"], "text": r["text"][:2000]}, ensure_ascii=False) + "\n")
            raise e if isinstance(e, Stuck) else Stuck(f"feed endpoint answered {r['ctype'] or 'no type'}, not JSON")
        recs = [x for x in (post_record(i, self.username) for i in d.get("items") or []) if x]
        return recs, (d.get("next_max_id") if d.get("more_available") else None)

    async def older_than(self, t=None, max_id=None):
        """One page of the owner's posts older than time t (or than a real cursor), newest first."""
        if self.style == "rest":
            return await self.fetch_rest(max_id or (cursor_for(t, self.uid, "pk_uid") if t is not None else None))
        cursor = max_id if max_id else (cursor_for(t, self.uid, self.style) if t is not None else None)
        recs, nxt, _ = self.parse(await self.fetch_page(cursor))
        return recs, nxt


class Stuck(RuntimeError):
    """This login can't go on (HTTP error, login wall, not JSON): try the next cookie file."""


async def walk(s, st, args, say, write, summary):
    """Steps 1 and 2, resumable: everything learned so far is kept in st, so after a cookie
    switch the walk picks up where it stopped. Returns when it reaches st['until']."""
    newest = await s.capture_template()              # a fresh copy of the web app's query for this login
    st.setdefault("uid", s.uid); s.uid = st["uid"]
    if st.get("back", {}).get("resumed"):
        if not st["back"]["cursor"]:
            await walk_back(s, st, say, write, summary, []); return
        s.real_next = st["back"]["cursor"]
    if not st.get("style"):                          # which made-up cursor form does Instagram take?
        if not newest:
            raise RuntimeError("the feed came back empty")
        st["newest_oldest"] = min(r["taken_at"] for r in newest)
        def rng(rs):
            return f"{len(rs)} posts {iso(min(r['taken_at'] for r in rs))[:10]}..{iso(max(r['taken_at'] for r in rs))[:10]}" if rs else "0 posts"
        say(f"  newest page: {rng(newest)}")
        if getattr(s, "real_next", None):             # does a replay with a REAL cursor go back in time?
            got, _ = await s.older_than(max_id=s.real_next)
            say(f"  replay with the page's own cursor: {rng(got)}")
        probe_t = sorted(r["taken_at"] for r in newest)[len(newest) // 2]
        styles = ["pk_uid", "pk"] if len(str(getattr(s, "real_next", "") or "")) < 40 or "_" in str(s.real_next) else []
        if not styles:
            say("  the page cursor is an opaque token, so no made-up cursor on this route")
        for style in styles + ["rest"]:
            s.style = style
            try:
                got, _ = await s.older_than(probe_t)
            except Stuck as e:
                say(f"  made-up cursor '{style}': {e}")
                continue
            say(f"  made-up cursor '{style}' for {iso(probe_t)[:16]}: {rng(got)}")
            if got and all(r["taken_at"] < probe_t for r in got):
                say(f"cursor form '{style}' works: jumping by date")
                st["style"] = style
                break
        else:
            say("no way to jump by date for this login: paging back from the newest post instead "
                "(Instagram's own cursors), then writing oldest first")
            st["style"] = "back"
    s.style = st["style"]
    if st["style"] == "back":
        await walk_back(s, st, say, write, summary, newest)
        return

    if st.get("done_to") is None:
        if args.from_:
            st["done_to"] = datetime.strptime(args.from_, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
            say(f"starting the walk at {args.from_} (--from)")
        else:
            # 1. FIRST POST: smallest T with posts older than T, to within a day
            st.setdefault("lo", IG_LAUNCH); st.setdefault("hi", st["newest_oldest"])
            say(f"looking for the first post between {iso(st['lo'])[:10]} and {iso(st['hi'])[:10]}")
            while st["hi"] - st["lo"] > 86400:
                mid = (st["lo"] + st["hi"]) / 2
                got, _ = await s.older_than(mid)
                say(f"  posts before {iso(mid)[:10]}? {'yes' if got else 'no'}")
                if got:
                    st["hi"] = mid
                else:
                    st["lo"] = mid
            first, nxt = await s.older_than(st["hi"])
            while nxt:                                # everything before hi, back to the start
                more, nxt = await s.older_than(max_id=nxt)
                first += more
            if not first:
                raise RuntimeError("binary search ended on an empty page")
            f0 = min(first, key=lambda r: r["taken_at"])
            summary["first_post"] = {**f0, "url": f"https://www.instagram.com/p/{f0['shortcode']}/",
                                     "posted_utc": iso(f0["taken_at"])}
            say(f"FIRST POST: {iso(f0['taken_at'])} UTC  https://www.instagram.com/p/{f0['shortcode']}/")
            say(f"  collaborators: {f0['collaborators']}  credits: {f0['credits']}")
            write(first)
            st["done_to"] = st["hi"]

    # 2. FORWARD WALK
    st.setdefault("step", 7 * 86400)
    while st["done_to"] < st["until"]:
        done_to = st["done_to"]; end = min(done_to + st["step"], st["until"])
        got, nxt = await s.older_than(end)
        while nxt and got and min(r["taken_at"] for r in got) > done_to:
            more, nxt = await s.older_than(max_id=nxt)
            got += more
        new = [r for r in got if done_to < r["taken_at"] < end]
        write(new)
        say(f"{iso(done_to)[:16]} -> {iso(end)[:16]}: +{len(new)} (total {summary['posts']}, requests {s.n})")
        st["done_to"] = end
        st["step"] = min(365 * 86400, max(3600, st["step"] * (TARGET_PER_WINDOW / len(new) if new else 2)))


async def walk_back(s, st, say, write, summary, newest):
    """No date jump available: follow Instagram's own cursors from the newest page to the end of the
    feed (collabnet's direction, but by replaying the query, no scrolling), keeping the mask in memory;
    then write everything oldest first. Resumable: st['back'] holds the cursor and what's collected."""
    b = st.setdefault("back", {"cursor": None, "posts": {}, "pages": 0})
    for r in newest:
        b["posts"].setdefault(r["shortcode"], r)
    s.style = None
    if b["cursor"] is None:
        b["cursor"] = s.real_next
        top, _ = await s.older_than()                # the captured page is usually page 2: get page 1 too
        for r in top:
            b["posts"].setdefault(r["shortcode"], r)
    pages = getattr(s, "pages_file", None)
    def save(recs, cursor):                          # a killed run keeps every page so far (--resume reads it)
        if pages:
            with open(pages, "a") as f:
                f.write(json.dumps({"cursor": cursor, "posts": recs}, ensure_ascii=False) + "\n")
    if b["pages"] == 0 and not b.get("resumed"):
        save(list(b["posts"].values()), b["cursor"])
    while b["cursor"]:
        got, b["cursor"] = await s.older_than(max_id=b["cursor"])
        for r in got:
            b["posts"].setdefault(r["shortcode"], r)
        b["pages"] += 1
        save(got, b["cursor"])
        oldest = min(r["taken_at"] for r in b["posts"].values())
        if b["pages"] % 10 == 0 or not b["cursor"]:
            say(f"  paged back to {iso(oldest)[:10]}: {len(b['posts'])} posts, requests {s.n}")
        if not got and b["cursor"]:
            raise Stuck("an empty page with more to come")
    allp = sorted(b["posts"].values(), key=lambda r: r["taken_at"])
    f0 = allp[0]
    summary["first_post"] = {**f0, "url": f"https://www.instagram.com/p/{f0['shortcode']}/", "posted_utc": iso(f0["taken_at"])}
    say(f"FIRST POST: {iso(f0['taken_at'])} UTC  https://www.instagram.com/p/{f0['shortcode']}/")
    say(f"  collaborators: {f0['collaborators']}  credits: {f0['credits']}")
    write(allp)
    st["done_to"] = time.time()
    if pages and Path(pages).exists():
        Path(pages).unlink()                         # the finished timeline replaces it


def load_resume(pages_file):
    """State for walk_back from a saved pages file: every post so far and the last cursor."""
    b = {"cursor": None, "posts": {}, "pages": 0, "resumed": True}
    for line in open(pages_file):
        rec = json.loads(line)
        for r in rec["posts"]:
            b["posts"].setdefault(r["shortcode"], r)
        b["cursor"] = rec["cursor"]; b["pages"] += 1
    return {"back": b, "style": "back"}


def cookie_candidates(args):
    """--cookies first (in the order given), then dl_wm's Instagram cookie hierarchy. Logged-out files are skipped."""
    files = list(args.cookies or [])
    try:
        cfg = json.loads((REPO / "conf/app_config.json").read_text())
        files += [str(REPO / f) for f in cfg["video_download"]["cookie_hierarchy"]["instagram"]]
    except Exception:
        files.append(str(REPO / "conf/instagram.cookies.haddamgoel.txt"))
    out, seen = [], set()
    for f in files:
        f = Path(f).expanduser()
        real = f.resolve()
        if real in seen or not f.exists():
            continue
        seen.add(real)
        if not any(c["name"] == "ds_user_id" and c["value"] for c in load_netscape_cookies(f)):
            continue                                  # logged out: no use here
        out.append(f)
    return out


def account_of(f):
    uid = next((c["value"] for c in load_netscape_cookies(f) if c["name"] == "ds_user_id"), "?")
    return f"{f.name} (ds_user_id {uid})"


async def main_async(args, out, say):
    from playwright.async_api import async_playwright
    tl = open(out / f"{args.username}_timeline.jsonl", "w", encoding="utf-8")
    summary = {"username": args.username, "started_utc": iso(time.time()), "end": None,
               "first_post": None, "posts": 0, "date_mismatches": [], "cookies_used": []}
    seen = set()
    st = {"until": datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
          if args.until else time.time()}
    pages_file = out / f"{args.username}_timeline.pages.jsonl"
    if pages_file.exists():                          # --resume: pick up the saved pages and the last cursor
        st.update(load_resume(pages_file))
        b = st["back"]
        say(f"resuming: {len(b['posts'])} posts from {b['pages']} saved pages" + ("" if b["cursor"] else " (walk had finished)"))

    def write(recs):
        for r in sorted(recs, key=lambda r: r["taken_at"]):
            if r["shortcode"] in seen:
                continue
            seen.add(r["shortcode"])
            tl.write(json.dumps(r, ensure_ascii=False) + "\n"); tl.flush()
            summary["posts"] += 1
            if r.get("date_mismatch"):
                summary["date_mismatches"].append(r["shortcode"])
                say(f"  DATE MISMATCH {r['shortcode']}: taken_at {iso(r['taken_at'])}, id says {iso(r['id_time'])}")

    cands = cookie_candidates(args)
    if not cands:
        say("no logged-in Instagram cookie file found")
    requests = 0
    async with async_playwright() as p:
        for k, cf in enumerate(cands):
            # one browser per login: with --single-process, closing a context takes the browser with it
            browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--single-process", "--no-zygote"])
            say(f"login {k + 1}/{len(cands)}: {account_of(cf)}")
            summary["cookies_used"].append(account_of(cf))
            ctx = await browser.new_context(viewport={"width": 1024, "height": 800},
                                            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
            await ctx.route(re.compile(r".*\.(png|jpg|jpeg|webp|gif|svg|woff2?|ttf|mp4|css)(\?.*)?$"), lambda r: r.abort())
            await ctx.add_cookies(load_netscape_cookies(cf))
            page = await ctx.new_page()
            s = Session(page, args.username, out / "errors.jsonl", say, args.pause, args.max_requests - requests)
            s.pages_file, s.dropped_file = pages_file, out / "dropped.jsonl"
            try:
                await page.goto(f"https://www.instagram.com/{args.username}/", wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(4)
                if "/accounts/login" in page.url:
                    raise Stuck("login wall: this cookie file is logged out or expired")
                m = re.search(r'content="([\d.,KM]+) Posts', await page.content())
                if m and "profile_post_count" not in summary:
                    summary["profile_post_count"] = m.group(1)
                    say(f"{args.username}: {m.group(1)} posts on the profile")
                await walk(s, st, args, say, write, summary)
                summary["end"] = "reached_until"
            except Stuck as e:
                summary["end"] = f"stuck: {e}"
                say(f"STUCK on this login: {e}" + ("  -> next cookie file" if k + 1 < len(cands) else ""))
            except Exception as e:
                summary["end"] = f"stopped: {e}"
                say(f"STOPPED: {e}")
            requests += s.n
            await browser.close()
            if not summary["end"].startswith("stuck"):
                break
    if summary["end"] and summary["end"].startswith("stuck") or not cands:
        summary["end"] = "I NEED COOKIES: every login is stuck. " + (summary["end"] or "")
        say("I NEED COOKIES: every login got stuck. Export a fresh one, e.g. "
            "bin/export_browser_cookies.py instagram.com conf/instagram.cookies.haddamgoel.txt ~/.config/google-chrome-goel/Default, "
            f"then re-run with --from {iso(st['done_to'])[:10] if st.get('done_to') else '(none yet)'}")
    tl.close()
    summary.update({"finished_utc": iso(time.time()), "requests": requests,
                    "walked_to": iso(st["done_to"]) if st.get("done_to") else None})
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("username")
    ap.add_argument("--cookies", action="append", metavar="FILE",
                    help="cookie file to try first (repeatable); then conf/app_config.json's Instagram hierarchy")
    ap.add_argument("--until", help="stop at this date, YYYY-MM-DD (default today)")
    ap.add_argument("--from", dest="from_", help="skip the first-post search; walk forward from YYYY-MM-DD")
    ap.add_argument("--pause", type=float, nargs=2, default=(3, 7), metavar=("MIN", "MAX"))
    ap.add_argument("--max-requests", type=int, default=800)
    ap.add_argument("--resume", metavar="DIR", help="carry on a killed/stuck run in DIR (reads its *_timeline.pages.jsonl)")
    args = ap.parse_args()

    base = REPO / "outputs/ig_timelines" / f"{args.username}_{datetime.now(timezone.utc):%Y-%m-%d}_reverse"
    if args.resume:
        out = Path(args.resume).expanduser()
        if not (out / f"{args.username}_timeline.pages.jsonl").exists():
            sys.exit(f"--resume: no {args.username}_timeline.pages.jsonl in {out}")
    else:
        out = base if not base.exists() else Path(f"{base}_{datetime.now():%H%M}")
        out.mkdir(parents=True)
    log = open(out / "run.log", "a" if args.resume else "w")

    def say(msg):
        line = f"{datetime.now():%H:%M:%S}  {msg}"
        print(line, flush=True); log.write(line + "\n"); log.flush()

    say(f"reversescrape {args.username} -> {out}  (pause {args.pause[0]:g}-{args.pause[1]:g}s, max {args.max_requests} requests)")
    summary = asyncio.run(main_async(args, out, say))
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    say(f"done: {summary['posts']} posts, {summary['requests']} requests, {summary['end']}; "
        f"{len(summary['date_mismatches'])} date mismatches")


if __name__ == "__main__":
    main()
