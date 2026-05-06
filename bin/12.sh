#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/12.sh 'https://www.instagram.com/p/SHORTCODE/' [cookies.txt]}"
COOKIE_FILE="${2:-conf/instagram.cookies.txt}"

SHORTCODE="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"
TODAY="$(date +%F)"
TS="$(date +%Y%m%d_%H%M%S)"
OUTDIR="outputs/${TODAY}/instagram__${SHORTCODE}/cookie_browser_capture_${TS}"

mkdir -p "$OUTDIR"

echo "URL: $URL"
echo "SHORTCODE: $SHORTCODE"
echo "COOKIE_FILE: $COOKIE_FILE"
echo "OUTDIR: $OUTDIR"
echo

python3 - "$URL" "$SHORTCODE" "$COOKIE_FILE" "$OUTDIR" <<'PY'
import asyncio, json, sys
from pathlib import Path

url = sys.argv[1]
target = sys.argv[2]
cookie_file = Path(sys.argv[3])
outdir = Path(sys.argv[4])

from playwright.async_api import async_playwright

items = []
captured = []

def load_netscape_cookies(path):
    cookies = []
    if not path.exists():
        print(f"WARNING: missing cookie file: {path}")
        return cookies

    for line in path.read_text(errors="ignore").splitlines():
        if not line or line.startswith("#HttpOnly_"):
            line = line.replace("#HttpOnly_", "", 1)
        elif line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) != 7:
            continue

        domain, flag, path_, secure, expires, name, value = parts

        if "instagram.com" not in domain:
            continue

        try:
            expires_i = int(expires)
        except Exception:
            expires_i = -1

        cookies.append({
            "name": name,
            "value": value,
            "domain": domain,
            "path": path_ or "/",
            "secure": secure.upper() == "TRUE",
            "httpOnly": False,
            "expires": expires_i if expires_i > 0 else -1,
            "sameSite": "Lax",
        })

    return cookies

def best_image(obj):
    c = obj.get("image_versions2", {}).get("candidates", [])
    if not c:
        return None
    best = max(c, key=lambda x: (x.get("width",0) or 0) * (x.get("height",0) or 0))
    return best.get("url")

def best_video(obj):
    v = obj.get("video_versions", [])
    if not v:
        return None
    best = max(v, key=lambda x: (x.get("width",0) or 0) * (x.get("height",0) or 0))
    return best.get("url")

def add_media(obj):
    u = best_video(obj)
    if u:
        items.append(("video", u))
        return
    u = best_image(obj)
    if u:
        items.append(("image", u))

def handle(obj):
    if not isinstance(obj, dict):
        return

    if obj.get("code") == target:
        carousel = obj.get("carousel_media")
        if isinstance(carousel, list) and carousel:
            for child in carousel:
                add_media(child)
        else:
            add_media(obj)

def walk(obj):
    if isinstance(obj, dict):
        handle(obj)
        for v in obj.values():
            walk(v)
    elif isinstance(obj, list):
        for x in obj:
            walk(x)
    elif isinstance(obj, str):
        if obj.startswith("{") and target in obj:
            try:
                walk(json.loads(obj))
            except Exception:
                pass

async def main():
    cookies = load_netscape_cookies(cookie_file)
    print(f"loaded_instagram_cookies={len(cookies)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        )

        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        async def on_response(response):
            try:
                text = await response.text()
                if target not in text and "image_versions2" not in text and "video_versions" not in text:
                    return

                captured.append({
                    "url": response.url,
                    "status": response.status,
                    "text": text,
                })

                try:
                    walk(json.loads(text))
                except Exception:
                    walk(text)

            except Exception:
                return

        page.on("response", on_response)

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        for i in range(10):
            await page.wait_for_timeout(2500)
            try:
                await page.mouse.wheel(0, 800)
                await page.wait_for_timeout(500)
                await page.mouse.wheel(0, -800)
            except Exception:
                pass
            print(f"round={i+1} captured={len(captured)} items={len(items)}")

        await browser.close()

asyncio.run(main())

seen = set()
clean = []
for kind, u in items:
    if u in seen:
        continue
    seen.add(u)
    clean.append((kind, u))

(outdir / "captured_responses.jsonl").write_text(
    "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in captured)
)
(outdir / "media_urls.txt").write_text(
    "\n".join(u for _, u in clean) + ("\n" if clean else "")
)
with (outdir / "selected_items.jsonl").open("w") as f:
    for i, (kind, u) in enumerate(clean, 1):
        f.write(json.dumps({"n": i, "shortcode": target, "kind": kind, "url": u}) + "\n")

print(f"clean_items={len(clean)}")
for i, (kind, u) in enumerate(clean, 1):
    print(f"{i:03d} {kind} {u[:140]}")
PY

echo
echo "Downloading..."

MANIFEST="$OUTDIR/manifest.jsonl"
n=0

while IFS= read -r url; do
  [ -z "$url" ] && continue
  n=$((n+1))

  clean="${url%%\?*}"
  ext="${clean##*.}"
  ext="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"
  case "$ext" in jpg|jpeg|png|webp|mp4) ;; *) ext="bin" ;; esac

  file="$(printf "%s/%03d.%s" "$OUTDIR" "$n" "$ext")"
  echo "[$n] $file"

  curl -L --silent --fail \
    -A "Mozilla/5.0" \
    -b "$COOKIE_FILE" \
    "$url" \
    -o "$file"

  sha="$(sha256sum "$file" | awk '{print $1}')"
  size="$(wc -c < "$file" | tr -d ' ')"
  mime="$(file -b --mime-type "$file" || true)"

  printf '{"n":%s,"shortcode":"%s","file":"%s","sha256":"%s","size":%s,"mime":"%s","url":"%s"}\n' \
    "$n" "$SHORTCODE" "$file" "$sha" "$size" "$mime" "$url" >> "$MANIFEST"

done < "$OUTDIR/media_urls.txt"

echo
echo "DONE:"
echo "$OUTDIR"
