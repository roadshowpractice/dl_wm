#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# bin/15.sh
#
# Purpose:
#   One-command Instagram /p/ probe/downloader.
#
# What it does:
#   1. Takes an Instagram /p/ URL as $1.
#   2. Extracts the shortcode from the URL.
#   3. Opens Chromium through Playwright.
#   4. Loads your Netscape Instagram cookies into that browser context.
#   5. Captures Instagram JSON/API responses while the page loads.
#   6. Writes those responses to captured_responses.jsonl.
#   7. Extracts media URLs from the capture.
#   8. Filters obvious junk/profile thumbnails.
#   9. Attempts to download the media with browser-like curl headers.
#
# Why this exists:
#   Instagram no longer reliably exposes /p/ media in plain HTML.
#   curl HTML, saved HTML, and yt-dlp can all see partial structure but often miss
#   actual image/video URLs. The browser sees more because JavaScript makes hidden
#   API/GraphQL requests. This script captures those responses automatically.
#
# Important:
#   This is still a probe/off-pipeline script. It may grab extra media from the
#   session if Instagram preloads feed/ad/reel content. The output files let us
#   inspect and refine filters.
#
# Usage:
#   bash bin/15.sh "https://www.instagram.com/p/SHORTCODE/"
#
# Optional env vars:
#   COOKIE_FILE=conf/instagram.cookies.2.txt
#   HEADLESS=1
#   ROUNDS=12
#
###############################################################################

URL="${1:?Usage: bash bin/15.sh 'https://www.instagram.com/p/SHORTCODE/'}"

COOKIE_FILE="${COOKIE_FILE:-conf/instagram.cookies.txt}"
HEADLESS="${HEADLESS:-0}"
ROUNDS="${ROUNDS:-10}"

SHORTCODE="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"

if [ -z "$SHORTCODE" ] || [ "$SHORTCODE" = "$URL" ]; then
  echo "ERROR: could not extract shortcode from URL: $URL"
  exit 1
fi

TODAY="$(date +%F)"
TS="$(date +%Y%m%d_%H%M%S)"
OUTDIR="outputs/${TODAY}/instagram__${SHORTCODE}/browser_cookie_full_${TS}"

mkdir -p "$OUTDIR"

echo "URL:        $URL"
echo "SHORTCODE:  $SHORTCODE"
echo "COOKIE:     $COOKIE_FILE"
echo "HEADLESS:   $HEADLESS"
echo "ROUNDS:     $ROUNDS"
echo "OUTDIR:     $OUTDIR"
echo

python3 - "$URL" "$SHORTCODE" "$COOKIE_FILE" "$OUTDIR" "$HEADLESS" "$ROUNDS" <<'PY'
import asyncio
import json
import re
import sys
from pathlib import Path

url = sys.argv[1]
target = sys.argv[2]
cookie_file = Path(sys.argv[3])
outdir = Path(sys.argv[4])
headless = sys.argv[5] == "1"
rounds = int(sys.argv[6])

try:
    from playwright.async_api import async_playwright
except Exception:
    print("ERROR: Playwright not installed.")
    print("Install with:")
    print("  pip install playwright")
    print("  python -m playwright install chromium")
    raise SystemExit(2)

###############################################################################
# Cookie loader
#
# Your Instagram cookies are in Netscape format, the same style yt-dlp accepts.
# Playwright wants cookies as dictionaries:
#   name, value, domain, path, secure, httpOnly, expires, sameSite
#
# We only load instagram.com cookies.
###############################################################################

def load_netscape_cookies(path: Path):
    cookies = []
    if not path.exists():
        print(f"WARNING: missing cookie file: {path}")
        return cookies

    for line in path.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue

        http_only = False
        if line.startswith("#HttpOnly_"):
            line = line.replace("#HttpOnly_", "", 1)
            http_only = True
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
            "httpOnly": http_only,
            "expires": expires_i if expires_i > 0 else -1,
            "sameSite": "Lax",
        })

    return cookies

###############################################################################
# Media extraction helpers
#
# Instagram has had several shapes:
#
# Older-ish:
#   xdt_shortcode_media
#
# Current shape seen in your captures:
#   data.xdt_api__v1__media__shortcode__web_info.items[]
#
# Other times, the media URLs only appear as loose strings in escaped JSON.
#
# So we do BOTH:
#   A. structured extraction by shortcode/code
#   B. loose URL extraction from response text
###############################################################################

structured_items = []
loose_urls = []
captured = []

def best_image(obj):
    candidates = obj.get("image_versions2", {}).get("candidates", [])
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda x: (x.get("width", 0) or 0) * (x.get("height", 0) or 0),
    )
    return best.get("url")

def best_video(obj):
    versions = obj.get("video_versions", [])
    if not versions:
        return None
    best = max(
        versions,
        key=lambda x: (x.get("width", 0) or 0) * (x.get("height", 0) or 0),
    )
    return best.get("url")

def add_structured_media(obj):
    u = best_video(obj)
    if u:
        structured_items.append(("video", u))
        return
    u = best_image(obj)
    if u:
        structured_items.append(("image", u))

def handle_item(item):
    if not isinstance(item, dict):
        return

    if item.get("code") != target:
        return

    carousel = item.get("carousel_media")
    if isinstance(carousel, list) and carousel:
        for child in carousel:
            if isinstance(child, dict):
                add_structured_media(child)
    else:
        add_structured_media(item)

def structured_extract(obj):
    if isinstance(obj, dict):
        if "xdt_api__v1__media__shortcode__web_info" in obj:
            info = obj["xdt_api__v1__media__shortcode__web_info"]
            for item in info.get("items", []):
                handle_item(item)

        if "xdt_shortcode_media" in obj:
            handle_item(obj["xdt_shortcode_media"])

        handle_item(obj)

        for v in obj.values():
            structured_extract(v)

    elif isinstance(obj, list):
        for x in obj:
            structured_extract(x)

    elif isinstance(obj, str):
        if obj.startswith("{") and (
            target in obj
            or "image_versions2" in obj
            or "video_versions" in obj
            or "xdt_api__v1__media__shortcode__web_info" in obj
        ):
            try:
                structured_extract(json.loads(obj))
            except Exception:
                pass

def loose_extract_from_text(text: str):
    # Capture direct CDN URLs that are visible in response text.
    # Then decode common JS/JSON escapes.
    pat = r'https://[^"\\\s<>]+?\.(?:jpg|jpeg|webp|png|mp4)[^"\\\s<>]*'
    for u in re.findall(pat, text):
        u = (
            u.replace("\\u0026", "&")
             .replace("\\/", "/")
             .replace("&amp;", "&")
        )
        if "cdninstagram" in u or "fbcdn" in u:
            loose_urls.append(u)

def dedupe_pairs(pairs):
    seen = set()
    out = []
    for kind, u in pairs:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append((kind, u))
    return out

def dedupe_urls(urls):
    seen = set()
    out = []
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out

def looks_like_junk(u: str):
    # Obvious junk/profile thumbnails/UI assets.
    junk_bits = [
        "static.cdninstagram.com",
        "rsrc.php",
        "s150x150",
        "_s150x150",
        "profile_pic",
        "t51.2885-19",   # profile pics
        "t51.82787-19",  # profile pics
    ]
    return any(bit in u for bit in junk_bits)

async def main():
    cookies = load_netscape_cookies(cookie_file)
    print(f"loaded_instagram_cookies={len(cookies)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124 Safari/537.36"
            ),
        )

        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        async def on_response(response):
            try:
                ru = response.url
                if not (
                    "instagram.com" in ru
                    or "fbcdn.net" in ru
                    or "cdninstagram.com" in ru
                ):
                    return

                text = await response.text()

                if not (
                    target in text
                    or "image_versions2" in text
                    or "video_versions" in text
                    or "xdt_api__v1__media__shortcode__web_info" in text
                    or ".mp4" in text
                    or ".jpg" in text
                    or ".webp" in text
                ):
                    return

                captured.append({
                    "url": ru,
                    "status": response.status,
                    "content_type": response.headers.get("content-type", ""),
                    "text": text,
                })

                loose_extract_from_text(text)

                try:
                    structured_extract(json.loads(text))
                except Exception:
                    structured_extract(text)

            except Exception:
                return

        page.on("response", on_response)

        print("Opening page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # If headless=0, the window is visible. You can manually scroll/click while
        # this loop runs. The script also nudges the page to trigger lazy loading.
        for i in range(rounds):
            await page.wait_for_timeout(2500)

            try:
                await page.mouse.wheel(0, 700)
                await page.wait_for_timeout(500)
                await page.mouse.wheel(0, -700)
            except Exception:
                pass

            # Try common carousel buttons.
            for label in ["Next", "Go to next", "Next photo"]:
                try:
                    loc = page.get_by_label(label)
                    if await loc.count():
                        await loc.first.click(timeout=1000)
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

            print(
                f"round={i+1} "
                f"captured={len(captured)} "
                f"structured={len(structured_items)} "
                f"loose={len(loose_urls)}"
            )

        await browser.close()

asyncio.run(main())

# Write capture.
(outdir / "captured_responses.jsonl").write_text(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in captured)
)

# Prefer structured shortcode-matching items when available.
structured_clean = dedupe_pairs(structured_items)

# Loose fallback: filter out obvious junk, keep CDN media.
loose_clean_urls = [
    u for u in dedupe_urls(loose_urls)
    if not looks_like_junk(u)
]

(outdir / "structured_media_urls.txt").write_text(
    "\n".join(u for _, u in structured_clean) + ("\n" if structured_clean else "")
)

(outdir / "loose_media_urls.txt").write_text(
    "\n".join(loose_clean_urls) + ("\n" if loose_clean_urls else "")
)

# Final candidate list:
#   if structured worked, use only structured
#   else use loose fallback
if structured_clean:
    final = structured_clean
    mode = "structured"
else:
    final = [
        ("video" if ".mp4" in u.split("?")[0].lower() else "image", u)
        for u in loose_clean_urls
    ]
    mode = "loose"

(outdir / "media_urls.txt").write_text(
    "\n".join(u for _, u in final) + ("\n" if final else "")
)

with (outdir / "selected_items.jsonl").open("w") as f:
    for i, (kind, u) in enumerate(final, 1):
        f.write(json.dumps({
            "n": i,
            "shortcode": target,
            "kind": kind,
            "mode": mode,
            "url": u,
        }, ensure_ascii=False) + "\n")

print()
print(f"mode={mode}")
print(f"captured_responses={len(captured)}")
print(f"structured_items={len(structured_clean)}")
print(f"loose_items={len(loose_clean_urls)}")
print(f"final_items={len(final)}")
for i, (kind, u) in enumerate(final[:25], 1):
    print(f"{i:03d} {kind} {u[:160]}")
PY

echo
echo "Downloading..."

MANIFEST="$OUTDIR/manifest.jsonl"
n=0
ok=0
fail=0

while IFS= read -r url; do
  [ -z "$url" ] && continue
  n=$((n+1))

  clean="${url%%\?*}"
  ext="${clean##*.}"
  ext="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"

  case "$ext" in
    jpg|jpeg|png|webp|mp4) ;;
    *) ext="bin" ;;
  esac

  file="$(printf "%s/%03d.%s" "$OUTDIR" "$n" "$ext")"

  echo "[$n] $file"

  if ! curl -L --silent --show-error --fail \
    -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36" \
    -e "https://www.instagram.com/" \
    -H "Referer: https://www.instagram.com/" \
    -H "Origin: https://www.instagram.com" \
    -H "Accept: */*" \
    -b "$COOKIE_FILE" \
    "$url" \
    -o "$file"; then
      echo "SKIP failed: $url" >&2
      rm -f "$file"
      fail=$((fail+1))
      continue
  fi

  sha="$(sha256sum "$file" | awk '{print $1}')"
  size="$(wc -c < "$file" | tr -d ' ')"
  mime="$(file -b --mime-type "$file" || true)"

  printf '{"n":%s,"shortcode":"%s","file":"%s","sha256":"%s","size":%s,"mime":"%s","url":"%s"}\n' \
    "$n" "$SHORTCODE" "$file" "$sha" "$size" "$mime" "$url" >> "$MANIFEST"

  ok=$((ok+1))

done < "$OUTDIR/media_urls.txt"

echo
echo "DONE:"
echo "$OUTDIR"
echo
echo "download_ok=$ok"
echo "download_failed=$fail"
echo
echo "Key files:"
echo "  $OUTDIR/captured_responses.jsonl"
echo "  $OUTDIR/structured_media_urls.txt"
echo "  $OUTDIR/loose_media_urls.txt"
echo "  $OUTDIR/media_urls.txt"
echo "  $OUTDIR/selected_items.jsonl"
echo "  $OUTDIR/manifest.jsonl"
