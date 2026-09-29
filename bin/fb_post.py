#!/usr/bin/env python3
"""Post text + one image to your own Facebook timeline, the way we did it by hand
on 2026-09-29 (Isaiah card, Merrill P. Jensen account). Headless Chromium + a
Netscape cookies.txt for the account. Dry run by default: fills the composer,
screenshots it, and stops. Add --post to actually click Post.

Every step and every /api/graphql/ response (friendly name, status, first 4 KB of
the body) goes to <outdir>/fb_post_<time>.jsonl, plus screenshots.

Usage:
  fb_post.py --cookies conf/facebook.merrill.cookies.txt --text intro.txt --image card.png [--post] [--outdir DIR]

Lessons from the manual run (see ~/Desktop/claude/2026-09-29/2026-09-29_fb_post_isaiah_log.md):
  - a URL in the text makes FB build a link preview; attach the image AFTER the
    text so the photo replaces the preview
  - use the file input inside the composer, not the first one on the page
  - Post redirects back to the feed; the permalink (pfbid...) shows up in the
    graphql mutation response or on the timestamp link after hovering

Verified 2026-09-29 09:45 (dry run, Merrill cookies exported from Chrome Profile 2):
logged in, opened /post/create, inserted 1171 chars (emoji + line breaks intact),
attached the card as a photo (it replaced the link preview), stopped before Post.
Needs igp.cookies.load_netscape_cookies(path, "facebook.com") - before that fix the
loader kept only instagram.com cookies, so FB got none and showed the login page.

First live post 2026-09-29 10:01 ("The Good Guy Edit"):
https://www.facebook.com/merrill.p.jensen/posts/10234395772575750
Fixes from that run: a fresh URL's link preview can land after the photo and replace
it, so wait for the preview first; setting the hidden file input stopped taking, so
click "Add photos or videos" and answer the file chooser; verify a blob: thumbnail
(abort if none); permalink = post_id from ComposerStoryCreateMutation.
"""
import argparse, asyncio, json, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from igp.cookies import load_netscape_cookies

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


class Log:
    def __init__(self, outdir):
        self.dir = Path(outdir); self.dir.mkdir(parents=True, exist_ok=True)
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.f = open(self.dir / f"fb_post_{self.stamp}.jsonl", "a")

    def __call__(self, step, **kw):
        rec = {"t": time.strftime("%H:%M:%S"), "step": step, **kw}
        self.f.write(json.dumps(rec) + "\n"); self.f.flush()
        print(step, {k: (v[:120] if isinstance(v, str) else v) for k, v in kw.items()})

    async def shot(self, page, name):
        p = self.dir / f"fb_post_{self.stamp}_{name}.png"
        await page.screenshot(path=str(p)); self("screenshot", path=str(p))


async def main(a):
    from playwright.async_api import async_playwright
    log = Log(a.outdir)
    text = Path(a.text).read_text().strip()
    image = str(Path(a.image).resolve())
    permalink = None

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--disable-gpu", "--single-process", "--no-zygote"])
        c = await b.new_context(viewport={"width": 1358, "height": 900}, user_agent=UA)
        await c.add_cookies(load_netscape_cookies(Path(a.cookies), "facebook.com"))
        pg = await c.new_page()

        async def on_response(r):
            nonlocal permalink
            if "/api/graphql" not in r.url:
                return
            name = r.request.headers.get("x-fb-friendly-name", "")
            try:
                body = await r.text()
            except Exception as e:
                body = f"<unreadable: {e}>"
            m = re.search(r"https:\\?/\\?/www\.facebook\.com\\?/[^\"]*?pfbid\w+", body)
            if m and "Create" in name:
                permalink = m.group(0).replace("\\/", "/")
            m = re.search(r'"post_id":"(\d+)"', body)
            if m and name == "ComposerStoryCreateMutation" and not permalink:
                permalink = f"https://www.facebook.com/{a.profile}/posts/{m.group(1)}"
            log("graphql", name=name, status=r.status, body=body[:4096])
        pg.on("response", lambda r: asyncio.ensure_future(on_response(r)))

        await pg.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(6)
        box = pg.get_by_role("button", name=re.compile(r"What's on your mind"))
        if not await box.count():
            await log.shot(pg, "not_logged_in"); log("abort", reason="no 'What's on your mind' - cookies expired or blocked")
            return 2
        log("feed", url=pg.url)

        await box.first.click(); await asyncio.sleep(5)
        log("composer", url=pg.url)
        tb = pg.get_by_role("textbox").filter(has_not=pg.locator("input")).first
        await tb.click()
        await pg.keyboard.insert_text(text)       # insert_text keeps emoji and line breaks
        await asyncio.sleep(3)
        log("text_inserted", chars=len(text))

        # a URL in the text makes FB build a link preview (card showing the domain in
        # caps, e.g. ANTMERRILL.GITHUB.IO). Wait for it to land first: if it arrives
        # after the photo, it replaces the photo.
        if "http" in text:
            preview = pg.get_by_text(re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", re.I))   # shown in caps via CSS only
            for _ in range(20):
                if await preview.count():
                    break
                await asyncio.sleep(1)
            log("link_preview", found=bool(await preview.count()))

        # image last: click the composer's own "Add photos or videos" box and answer
        # the file chooser (setting the hidden input directly stopped taking), then
        # check it really attached (a blob: thumbnail shows up). Retry once.
        photo = pg.locator('img[src^="blob:"]')
        drop = pg.get_by_text("Add photos or videos")
        log("file_inputs", count=await pg.locator('input[type="file"]').count(), dropzone=await drop.count())
        for attempt in (1, 2):
            if await drop.count():
                async with pg.expect_file_chooser() as fc:
                    await drop.first.click()
                await (await fc.value).set_files(image)
            else:
                fi = pg.locator('input[type="file"]')
                await fi.nth(await fi.count() - 1).set_input_files(image)
            for _ in range(15):
                await asyncio.sleep(1)
                if await photo.count():
                    break
            ok = bool(await photo.count())
            log("image_attached", path=image, attempt=attempt, ok=ok, blob_imgs=await photo.count())
            if ok:
                break
        await log.shot(pg, "ready")
        if not ok:
            log("abort", reason="photo never showed up in the composer (link preview won?)")
            await b.close(); return 3

        if not a.post:
            log("dry_run", note="not posted; rerun with --post")
            await b.close(); return 0

        await pg.get_by_role("button", name="Post", exact=True).last.click()
        log("post_clicked")
        await asyncio.sleep(12)
        log("after_post", url=pg.url)
        if not permalink:
            ts = pg.locator('a[href*="pfbid"]').first
            if await ts.count():
                permalink = (await ts.get_attribute("href")).split("?")[0]
        log("permalink", url=permalink or "NOT FOUND - check the timeline")
        await log.shot(pg, "posted")
        await b.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cookies", required=True, help="Netscape cookies.txt for the posting account")
    ap.add_argument("--text", required=True, help="file with the post text")
    ap.add_argument("--image", required=True, help="image to attach")
    ap.add_argument("--post", action="store_true", help="actually click Post (default: dry run)")
    ap.add_argument("--profile", default="merrill.p.jensen", help="profile username for the permalink")
    ap.add_argument("--outdir", default=str(Path.home() / "Desktop/claude" / time.strftime("%Y-%m-%d")))
    sys.exit(asyncio.run(main(ap.parse_args())))
