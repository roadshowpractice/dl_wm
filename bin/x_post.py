#!/usr/bin/env python3
"""Post a thread to X (Twitter), with an image on the first post and an "at list" of accounts to tag.

Chromium + a Netscape cookies.txt for the account (x.com login cookies auth_token + ct0). Dry run by default:
fills the whole thread in the composer, screenshots it, and stops. Every step goes to <outdir>/x_post_<time>.jsonl;
any failure leaves a screenshot (x_post_<time>_failed.png).

    python bin/x_post.py --thread THREAD.txt --plan                       # no browser: show posts, lengths, tags
    python bin/x_post.py --cookies conf/x.cookies.txt --thread THREAD.txt --image card.png [--at ats.txt]
        --monkey              visible window; the script fills it all, a PERSON presses Post; permalink is logged
        --post                the script presses Post itself (headless X tends to block this; prefer --monkey)
        --watch-replies 5     after posting, keep every reply for 5 minutes (verbatim + sha256 in outdir)
    python bin/x_post.py --cookies conf/x.cookies.txt --replies-of https://x.com/<user>/status/<id> [--watch-replies 3]

Replies land in <outdir>/replies_<id>.jsonl (one record per reply: id, author, time, reply-to, full text, sha256)
and replies_<id>.txt (readable). 2026-10-08: --monkey, --watch-replies, --replies-of added after the headless
run of 10-07 timed out at the composer.

THREAD.txt: posts separated by a line "---", or by header lines like "1/5" (the headers are dropped).
--at FILE: one handle per line (@ optional, # comments ok). Where the tags go (--at-where):
    reply  (default) one extra post at the end of the thread: "cc @a @b ..."; keeps the thread itself clean
    first  appended to the first post        last   appended to the last post
  Handles are checked (1-15 letters, digits, _), de-duplicated, and every post is checked against the
  280-character limit (links count as 23, as X counts them; wide characters such as emoji count 2).
  If tags would push a post over the limit, the script stops and says so instead of trimming anything.

Cookies: export them from a Chrome profile that is logged into X (you log in yourself; this script never
handles passwords):  python bin/export_browser_cookies.py x.com conf/x.cookies.txt "~/.config/google-chrome/Profile 2"
Written 2026-10-06.
"""
import argparse, asyncio, json, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LIMIT = 280
URL_RE = re.compile(r"https?://\S+")
HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


def x_length(text):
    """Approximate X's weighted length: each link 23, wide characters (emoji, CJK) 2, everything else 1."""
    body = URL_RE.sub("", text)
    n = 23 * len(URL_RE.findall(text))
    for ch in body:
        n += 2 if ord(ch) >= 0x1100 else 1
    return n


def parse_thread(raw):
    raw = raw.strip()
    if re.search(r"^---\s*$", raw, re.M):
        parts = re.split(r"^---\s*$", raw, flags=re.M)
    else:
        parts = re.split(r"^\s*\d+/\d+\s*$", raw, flags=re.M)
    return [p.strip() for p in parts if p.strip()]


def read_ats(path):
    handles, bad = [], []
    for line in Path(path).read_text().splitlines():
        h = line.split("#", 1)[0].strip().lstrip("@")
        if not h:
            continue
        (handles if HANDLE_RE.match(h) else bad).append(h)
    if bad:
        raise SystemExit(f"Not valid X handles: {', '.join(bad)}")
    return list(dict.fromkeys(handles))


def apply_ats(posts, handles, where):
    posts = list(posts)
    if not handles:
        return posts
    tags = " ".join("@" + h for h in handles)
    if where == "reply":
        posts.append("cc " + tags)
    elif where == "first":
        posts[0] = posts[0] + "\n\n" + tags
    else:
        posts[-1] = posts[-1] + "\n\n" + tags
    return posts


def check(posts):
    over = [(i + 1, x_length(p)) for i, p in enumerate(posts) if x_length(p) > LIMIT]
    if over:
        raise SystemExit("Over 280 characters: " + ", ".join(f"post {i} ({n})" for i, n in over)
                         + ". Shorten the text, or use --at-where reply.")


class Log:
    def __init__(self, outdir):
        self.dir = Path(outdir); self.dir.mkdir(parents=True, exist_ok=True)
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.f = open(self.dir / f"x_post_{self.stamp}.jsonl", "a")

    def __call__(self, step, **kw):
        rec = {"t": time.strftime("%H:%M:%S"), "step": step, **kw}
        self.f.write(json.dumps(rec) + "\n"); self.f.flush()
        print(step, {k: (v[:120] if isinstance(v, str) else v) for k, v in kw.items()})

    async def shot(self, page, name):
        p = self.dir / f"x_post_{self.stamp}_{name}.png"
        try:  # a frozen page must not hide the real error
            await page.screenshot(path=str(p), full_page=False, timeout=10000); self("screenshot", path=str(p))
        except Exception as e:
            self("screenshot_failed", name=name, error=str(e)[:200])


def tweets_in(obj, out=None):
    """every tweet in an X GraphQL response (TweetDetail etc.): id, author, time, reply-to, full text"""
    out = {} if out is None else out
    if isinstance(obj, dict):
        leg = obj.get("legacy")
        if obj.get("rest_id") and isinstance(leg, dict) and "full_text" in leg:
            u = ((obj.get("core") or {}).get("user_results") or {}).get("result") or {}
            name = (u.get("core") or {}).get("screen_name") or (u.get("legacy") or {}).get("screen_name")
            note = (((obj.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}).get("text")
            out[obj["rest_id"]] = {"id": obj["rest_id"], "author": name, "created_at": leg.get("created_at"),
                                   "in_reply_to": leg.get("in_reply_to_status_id_str"), "text": note or leg["full_text"]}
        for v in obj.values():
            tweets_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            tweets_in(v, out)
    return out


def save_replies(outdir, status_id, tweets, seen, log):
    """append tweets not seen before, verbatim, with a sha256 of each record, to replies_<id>.jsonl/.txt"""
    import hashlib
    new = [t for k, t in sorted(tweets.items()) if k not in seen and k != status_id]
    with open(Path(outdir) / f"replies_{status_id}.jsonl", "a") as jf, open(Path(outdir) / f"replies_{status_id}.txt", "a") as tf:
        for t in new:
            seen.add(t["id"])
            rec = json.dumps(t, ensure_ascii=False, sort_keys=True)
            t_hash = hashlib.sha256(rec.encode()).hexdigest()
            jf.write(json.dumps({**t, "sha256": t_hash, "captured": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, ensure_ascii=False) + "\n")
            tf.write(f"--- @{t['author']} {t['created_at']} https://x.com/{t['author']}/status/{t['id']}"
                     f" (reply to {t['in_reply_to']}) sha256 {t_hash}\n{t['text']}\n\n")
            log("reply", author=t["author"], id=t["id"], text=t["text"])
    return len(new)


async def open_x(p, a, log):
    """browser + context with the account's cookies; headed when a person may need to act (--monkey/--headed)"""
    from igp.cookies import load_netscape_cookies
    headed = a.monkey or a.headed
    args = ["--disable-gpu", "--disable-blink-features=AutomationControlled"]
    if headed:  # fit the person's screen (a fixed 1000 px tall page hid the Post button on a 768 px laptop screen)
        b = await p.chromium.launch(headless=False, args=args + ["--start-maximized"])
        c = await b.new_context(no_viewport=True, user_agent=UA)
    else:
        b = await p.chromium.launch(headless=True, args=args)
        c = await b.new_context(viewport={"width": 1358, "height": 1000}, user_agent=UA)
    cookies = load_netscape_cookies(Path(a.cookies), "x.com")
    if not any(ck["name"] == "auth_token" for ck in cookies):
        log("abort", reason="no auth_token cookie for x.com in the cookie file: not logged in")
        await b.close(); return None, None
    await c.add_cookies(cookies)
    return b, c


async def watch_replies(c, a, log, status_id, minutes):
    """open the post every 60 s for `minutes`, keep every reply X sends in TweetDetail"""
    pg = await c.new_page(); seen = set(); found = {}

    async def on_resp(r):
        if "TweetDetail" in r.url:
            try:
                tweets_in(json.loads(await r.text()), found)
            except Exception:
                pass
    pg.on("response", lambda r: asyncio.ensure_future(on_resp(r)))
    url = f"https://x.com/i/status/{status_id}"
    t_end = time.time() + 60 * minutes
    while True:
        await pg.goto(url, wait_until="domcontentloaded", timeout=60000); await asyncio.sleep(8)
        for _ in range(3):
            await pg.mouse.wheel(0, 2500); await asyncio.sleep(2)
        n = save_replies(a.outdir, status_id, found, seen, log)
        log("replies_checked", url=url, new=n, total=len(seen))
        if time.time() >= t_end:
            break
        await asyncio.sleep(max(0, min(60, t_end - time.time())))
    await log.shot(pg, f"replies_{status_id}")


async def run_replies(a):
    """--replies-of URL: scrape the replies to any post, no posting"""
    from playwright.async_api import async_playwright
    m = re.search(r"status/(\d+)", a.replies_of)
    if not m:
        raise SystemExit("--replies-of needs a post URL with /status/<id>")
    log = Log(a.outdir)
    async with async_playwright() as p:
        b, c = await open_x(p, a, log)
        if not b:
            return 2
        await watch_replies(c, a, log, m.group(1), a.watch_replies)
        await b.close()
    return 0


async def run(a, posts):
    from playwright.async_api import async_playwright
    log = Log(a.outdir)
    status_ids = []
    async with async_playwright() as p:
        b, c = await open_x(p, a, log)
        if not b:
            return 2
        pg = await c.new_page()

        async def on_response(r):
            if "CreateTweet" not in r.url:
                return
            try:
                body = await r.text()
            except Exception:
                return
            # the POST's id is data.create_tweet.tweet_results.result.rest_id; the first "rest_id" in the
            # body is the author's user id (10-08: that mix-up sent --watch-replies to the wrong page)
            try:
                res = json.loads(body)["data"]["create_tweet"]["tweet_results"]["result"]
                tid = res.get("rest_id") or (res.get("tweet") or {}).get("rest_id")
            except Exception:
                tid = None
            if tid:
                status_ids.append(tid)
            log("create_tweet", status=r.status, body=body[:1500])
        pg.on("response", lambda r: asyncio.ensure_future(on_response(r)))

        try:
            await pg.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=60000)
            if "/login" in pg.url or "/i/flow/login" in pg.url:
                raise RuntimeError(f"X sent the login page ({pg.url}): cookies expired, export them again")
            # /compose/post shows TWO composers (the pop-up and the home timeline's); work only inside the pop-up
            dlg = pg.locator('[role="dialog"]').filter(has=pg.locator('[data-testid="tweetTextarea_0"]')).first
            await dlg.locator('[data-testid="tweetTextarea_0"]').wait_for(timeout=a.composer_wait * 1000)

            for i, text in enumerate(posts):
                if i > 0:
                    await dlg.locator('[data-testid="addButton"]').last.click(); await asyncio.sleep(1.5)
                box = dlg.locator(f'[data-testid="tweetTextarea_{i}"]')
                await box.click(); await pg.keyboard.insert_text(text); await asyncio.sleep(1)
                got = (await box.inner_text()).replace("\n", "")
                log("post_filled", n=i + 1, chars=x_length(text), box_ok=text.replace("\n", "")[:40] in got)
                if i == 0 and a.image:
                    await dlg.locator('input[data-testid="fileInput"]').first.set_input_files(str(Path(a.image).resolve()))
                    await dlg.locator('[data-testid="attachments"] img, [data-testid="attachments"] video').first.wait_for(timeout=30000)
                    log("image_attached", path=a.image, ok=True)
        except Exception as e:
            log("abort", reason=str(e)[:500], url=pg.url); await log.shot(pg, "failed")
            await b.close(); return 3
        await log.shot(pg, "ready")

        if a.monkey:
            await dlg.locator('[data-testid="tweetButton"]').last.scroll_into_view_if_needed()
            # the person presses Post in the open window; the script only watches for X's CreateTweet answer
            print("\n>>> MONKEY: check the window, then press Post (or Post all) yourself. Waiting "
                  f"{a.monkey_wait} min. Close the window to cancel. <<<\n", flush=True)
            log("waiting_for_person", minutes=a.monkey_wait)
            t_end = time.time() + 60 * a.monkey_wait
            while not status_ids and time.time() < t_end and not pg.is_closed():
                await asyncio.sleep(2)
            if not status_ids:
                log("abort", reason="no post seen (window closed or time ran out); nothing was posted by the script")
                await b.close(); return 4
            await asyncio.sleep(6)
        elif a.post:
            await dlg.locator('[data-testid="tweetButton"]').last.click()
            log("post_clicked"); await asyncio.sleep(12)
        else:
            log("dry_run", note="not posted; rerun with --monkey (you press Post) or --post")
            await b.close(); return 0

        first = status_ids[0] if status_ids else None
        log("permalink", url=f"https://x.com/{a.profile}/status/{first}" if first else "NOT FOUND - check the profile",
            all_ids=status_ids)
        if not pg.is_closed():
            await log.shot(pg, "posted")
        if first and a.watch_replies:
            await watch_replies(c, a, log, first, a.watch_replies)
        await b.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--thread", help="thread text file")
    ap.add_argument("--image", help="image for the first post")
    ap.add_argument("--at", help="at list: file of handles to tag")
    ap.add_argument("--at-where", default="reply", choices=["reply", "first", "last"])
    ap.add_argument("--cookies", help="Netscape cookies.txt for the posting X account")
    ap.add_argument("--profile", default="i", help="X username, for the permalink")
    ap.add_argument("--plan", action="store_true", help="show the posts, lengths and tags; no browser")
    ap.add_argument("--post", action="store_true", help="the script clicks Post itself (default: dry run)")
    ap.add_argument("--monkey", action="store_true",
                    help="visible window; the script fills everything, YOU press Post; it logs the permalink")
    ap.add_argument("--monkey-wait", type=float, default=10, help="minutes to wait for you to press Post (default 10)")
    ap.add_argument("--headed", action="store_true", help="show the browser window (implied by --monkey)")
    ap.add_argument("--composer-wait", type=int, default=60, help="seconds to wait for the composer (default 60)")
    ap.add_argument("--watch-replies", type=float, default=0, metavar="MIN",
                    help="after posting, collect replies for MIN minutes (verbatim + sha256 into outdir)")
    ap.add_argument("--replies-of", metavar="URL", help="only collect the replies to this post (no posting)")
    ap.add_argument("--outdir", default=str(Path.home() / "Desktop/claude" / time.strftime("%Y-%m-%d")))
    a = ap.parse_args(argv)
    if a.replies_of:
        if not a.cookies:
            raise SystemExit("--cookies is needed to open X.")
        a.watch_replies = a.watch_replies or 0.01
        return asyncio.run(run_replies(a))
    if not a.thread:
        raise SystemExit("--thread is needed (or --replies-of URL).")
    posts = parse_thread(Path(a.thread).read_text())
    if not posts:
        raise SystemExit("The thread file has no posts.")
    posts = apply_ats(posts, read_ats(a.at) if a.at else [], a.at_where)
    check(posts)
    if a.plan:
        for i, p in enumerate(posts, 1):
            print(f"--- post {i}/{len(posts)} · {x_length(p)}/280 chars{' · + image' if i == 1 and a.image else ''}\n{p}\n")
        return 0
    if not a.cookies:
        raise SystemExit("--cookies is needed to open X (or use --plan).")
    return asyncio.run(run(a, posts))


if __name__ == "__main__":
    sys.exit(main())
