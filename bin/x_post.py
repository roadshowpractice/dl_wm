#!/usr/bin/env python3
"""Post a thread to X (Twitter), with an image on the first post and an "at list" of accounts to tag.

Same approach as bin/fb_post.py: headless Chromium + a Netscape cookies.txt for the account (x.com login
cookies auth_token + ct0). Dry run by default: fills the whole thread in the composer, screenshots it,
and stops. Add --post to click "Post all". Every step goes to <outdir>/x_post_<time>.jsonl.

    python bin/x_post.py --thread THREAD.txt --plan                       # no browser: show posts, lengths, tags
    python bin/x_post.py --cookies conf/x.cookies.txt --thread THREAD.txt --image card.png [--at ats.txt] [--post]

THREAD.txt: posts separated by a line "---", or by header lines like "1/5" (the headers are dropped).
--at FILE: one handle per line (@ optional, # comments ok). Where the tags go (--at-where):
    reply  (default) one extra post at the end of the thread: "cc @a @b ..."; keeps the thread itself clean
    first  appended to the first post        last   appended to the last post
  Handles are checked (1-15 letters, digits, _), de-duplicated, and every post is checked against the
  280-character limit (links count as 23, as X counts them; wide characters such as emoji count 2).
  If tags would push a post over the limit, the script stops and says so instead of trimming anything.

Cookies: export them from a Chrome profile that is logged into X (you log in yourself; this script never
handles passwords):  python bin/export_browser_cookies.py x.com conf/x.cookies.txt "~/.config/google-chrome/Profile 2"
Written 2026-10-06. Not yet run live (no X login on this machine at the time).
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
        await page.screenshot(path=str(p), full_page=True); self("screenshot", path=str(p))


async def run(a, posts):
    from playwright.async_api import async_playwright
    from igp.cookies import load_netscape_cookies
    log = Log(a.outdir)
    status_ids = []
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--disable-gpu"])
        c = await b.new_context(viewport={"width": 1358, "height": 1000}, user_agent=UA)
        cookies = load_netscape_cookies(Path(a.cookies), "x.com")
        if not any(ck["name"] == "auth_token" for ck in cookies):
            log("abort", reason="no auth_token cookie for x.com in the cookie file: not logged in")
            await b.close(); return 2
        await c.add_cookies(cookies)
        pg = await c.new_page()

        async def on_response(r):
            if "CreateTweet" not in r.url:
                return
            try:
                body = await r.text()
            except Exception:
                return
            m = re.search(r'"rest_id":"(\d+)"', body)
            if m:
                status_ids.append(m.group(1))
            log("create_tweet", status=r.status, body=body[:1500])
        pg.on("response", lambda r: asyncio.ensure_future(on_response(r)))

        await pg.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(6)
        if "/login" in pg.url or not await pg.locator('[data-testid="tweetTextarea_0"]').count():
            await log.shot(pg, "not_logged_in"); log("abort", reason="no composer: cookies expired or not logged in", url=pg.url)
            await b.close(); return 2

        for i, text in enumerate(posts):
            if i > 0:
                await pg.locator('[data-testid="addButton"]').last.click(); await asyncio.sleep(1.5)
            box = pg.locator(f'[data-testid="tweetTextarea_{i}"]')
            await box.click(); await pg.keyboard.insert_text(text); await asyncio.sleep(1)
            log("post_filled", n=i + 1, chars=x_length(text))
            if i == 0 and a.image:
                await pg.locator('input[data-testid="fileInput"]').first.set_input_files(str(Path(a.image).resolve()))
                await asyncio.sleep(5)
                ok = await pg.locator('[data-testid="attachments"] img, [data-testid="attachments"] video').count()
                log("image_attached", path=a.image, ok=bool(ok))
                if not ok:
                    await log.shot(pg, "no_image"); log("abort", reason="image never showed up in the composer")
                    await b.close(); return 3
        await log.shot(pg, "ready")
        if not a.post:
            log("dry_run", note="not posted; rerun with --post")
            await b.close(); return 0

        await pg.locator('[data-testid="tweetButton"]').last.click()
        log("post_clicked"); await asyncio.sleep(12)
        first = status_ids[0] if status_ids else None
        log("permalink", url=f"https://x.com/{a.profile}/status/{first}" if first else "NOT FOUND - check the profile",
            all_ids=status_ids)
        await log.shot(pg, "posted")
        await b.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--thread", required=True, help="thread text file")
    ap.add_argument("--image", help="image for the first post")
    ap.add_argument("--at", help="at list: file of handles to tag")
    ap.add_argument("--at-where", default="reply", choices=["reply", "first", "last"])
    ap.add_argument("--cookies", help="Netscape cookies.txt for the posting X account")
    ap.add_argument("--profile", default="i", help="X username, for the permalink")
    ap.add_argument("--plan", action="store_true", help="show the posts, lengths and tags; no browser")
    ap.add_argument("--post", action="store_true", help="actually post (default: dry run)")
    ap.add_argument("--outdir", default=str(Path.home() / "Desktop/claude" / time.strftime("%Y-%m-%d")))
    a = ap.parse_args(argv)
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
