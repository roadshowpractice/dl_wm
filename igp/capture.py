import asyncio, json, re, sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from igp.cookies import load_netscape_cookies


ALLOWED_MEDIA_HOSTS = {"instagram.fna.fbcdn.net", "scontent.cdninstagram.com"}
IMAGE_EXTS = {".jpg", ".jpeg", ".webp", ".png"}


def looks_like_junk(url):
    junk_bits = [
        "static.cdninstagram.com",
        "rsrc.php",
        "s150x150",
        "_s150x150",
        "profile_pic",
        "t51.2885-19",
        "t51.82787-19",
    ]
    return any(bit in url for bit in junk_bits)


def media_group_key(url):
    return Path(urlparse(url).path).name or url


def parse_stp(url):
    return parse_qs(urlparse(url).query).get("stp", [""])[0]


def is_cropped_variant(url):
    return bool(re.search(r"c\d+\.\d+\.\d+\.\d+a_", parse_stp(url)))


def parse_square_size(url):
    m = re.search(r"s(\d+)x(\d+)", parse_stp(url))
    if not m:
        return None
    return min(int(m.group(1)), int(m.group(2)))


def variant_score(url):
    path = urlparse(url).path.lower()
    base = 10000 if path.endswith(".mp4") else 0
    uncropped_score = 2000 if not is_cropped_variant(url) else 0
    size = parse_square_size(url)
    size_score = size if size is not None else 900
    return base + uncropped_score + size_score


def is_media_url(url):
    p = urlparse(url)
    if p.netloc.lower() not in ALLOWED_MEDIA_HOSTS:
        return False
    if looks_like_junk(url):
        return False
    ext = Path(p.path).suffix.lower()
    return ext in IMAGE_EXTS or ext == ".mp4"


async def run(url, shortcode, cookie_file, outdir, headless, rounds):
    from playwright.async_api import async_playwright

    captured = []
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    best_by_filename = {}
    order_by_filename = {}
    downloaded_filenames = set()
    next_index = 1

    manifest_path = out / "manifest.jsonl"
    manifest_fp = manifest_path.open("w", encoding="utf-8")

    async def maybe_download_best(response):
        nonlocal next_index
        ru = response.url
        if not is_media_url(ru):
            return

        filename = media_group_key(ru)
        if not filename:
            return

        if filename not in order_by_filename:
            order_by_filename[filename] = len(order_by_filename) + 1

        prev = best_by_filename.get(filename)
        if prev is None or variant_score(ru) > variant_score(prev):
            best_by_filename[filename] = ru

        if filename in downloaded_filenames:
            return

        if best_by_filename.get(filename) != ru:
            return

        try:
            body = await response.body()
        except Exception:
            return

        ext = Path(urlparse(ru).path).suffix.lower() or ".bin"
        dest = out / f"{next_index:03d}{ext}"
        dest.write_bytes(body)

        manifest_fp.write(
            json.dumps(
                {
                    "index": next_index,
                    "filename": filename,
                    "url": ru,
                    "path": dest.name,
                    "status": "ok",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        manifest_fp.flush()
        downloaded_filenames.add(filename)
        next_index += 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        )
        cookies = load_netscape_cookies(Path(cookie_file))
        if cookies:
            await context.add_cookies(cookies)
        page = await context.new_page()

        async def on_response(response):
            try:
                ru = response.url
                if not ("instagram.com" in ru or "fbcdn.net" in ru or "cdninstagram.com" in ru):
                    return
                text = await response.text()
                if not (
                    shortcode in text
                    or "image_versions2" in text
                    or "video_versions" in text
                    or "xdt_api__v1__media__shortcode__web_info" in text
                    or ".mp4" in text
                    or ".jpg" in text
                    or ".webp" in text
                ):
                    return
                captured.append({"url": ru, "status": response.status, "content_type": response.headers.get("content-type", ""), "text": text})
            except Exception:
                pass

            try:
                await maybe_download_best(response)
            except Exception:
                return

        page.on("response", on_response)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for _ in range(rounds):
            await page.wait_for_timeout(2500)
            try:
                await page.mouse.wheel(0, 700)
                await page.wait_for_timeout(500)
                await page.mouse.wheel(0, -700)
            except Exception:
                pass
            for label in ["Next", "Go to next", "Next photo"]:
                try:
                    loc = page.get_by_label(label)
                    if await loc.count():
                        await loc.first.click(timeout=1000)
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass
        await browser.close()

    manifest_fp.close()
    (out / "captured_responses.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in captured), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] == "1", int(sys.argv[6])))
