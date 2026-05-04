import asyncio, json, sys
from pathlib import Path
from igp.cookies import load_netscape_cookies


async def run(url, shortcode, cookie_file, outdir, headless, rounds):
    from playwright.async_api import async_playwright

    captured = []

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
                if not (shortcode in text or "image_versions2" in text or "video_versions" in text or "xdt_api__v1__media__shortcode__web_info" in text or ".mp4" in text or ".jpg" in text or ".webp" in text):
                    return
                captured.append({"url": ru, "status": response.status, "content_type": response.headers.get("content-type", ""), "text": text})
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

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "captured_responses.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in captured))


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] == "1", int(sys.argv[6])))
