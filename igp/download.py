import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from igp.cookies import load_netscape_cookies
from playwright.sync_api import sync_playwright


EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "video/mp4": "mp4",
}
ALLOWED_EXTS = {"jpg", "jpeg", "png", "webp", "mp4"}


def _ext_from_url(url: str) -> str | None:
    path = urlparse(url).path
    name = Path(path).name
    if "." not in name:
        return None
    ext = name.rsplit(".", 1)[-1].lower()
    return ext if ext in ALLOWED_EXTS else None


def _ext_from_content_type(content_type: str) -> str:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    return EXT_BY_CONTENT_TYPE.get(ctype, "bin")


def download_with_playwright(media_urls_path, shortcode, cookie_file, outdir):
    media_urls_file = Path(media_urls_path)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.jsonl"

    urls = [u.strip() for u in media_urls_file.read_text(errors="ignore").splitlines() if u.strip()]

    cookies = load_netscape_cookies(Path(cookie_file))
    ok = 0
    failed = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        )
        if cookies:
            context.add_cookies(cookies)

        with manifest.open("a", encoding="utf-8") as mf:
            for i, url in enumerate(urls, start=1):
                status = "failed"
                rel_path = ""
                for attempt in range(3):
                    try:
                        resp = context.request.get(url)
                        if resp.ok:
                            data = resp.body()
                            ext = _ext_from_url(url) or _ext_from_content_type(resp.headers.get("content-type", ""))
                            file_path = out / f"{i:03d}.{ext}"
                            file_path.write_bytes(data)
                            status = "ok"
                            rel_path = file_path.name
                            ok += 1
                            break
                    except Exception:
                        pass

                    if attempt < 2:
                        time.sleep(0.7)

                if status != "ok":
                    failed += 1

                mf.write(
                    json.dumps(
                        {
                            "index": i,
                            "url": url,
                            "path": rel_path,
                            "status": status,
                            "shortcode": shortcode,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        context.close()
        browser.close()

    print(f"download_ok={ok}")
    print(f"download_failed={failed}")


def run(outdir, shortcode, cookie_file):
    media_urls_path = Path(outdir) / "media_urls.txt"
    download_with_playwright(media_urls_path, shortcode, cookie_file, outdir)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3])
