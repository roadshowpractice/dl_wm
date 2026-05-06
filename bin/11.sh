#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/11.sh 'https://www.instagram.com/p/SHORTCODE/'}"
SHORTCODE_ARG="${2:-}"

SHORTCODE_AUTO="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"
SHORTCODE="${SHORTCODE_ARG:-${SHORTCODE:-$SHORTCODE_AUTO}}"

TODAY="$(date +%F)"
TS="$(date +%Y%m%d_%H%M%S)"
BASE_OUT="outputs/${TODAY}/instagram__${SHORTCODE}"
OUTDIR="${BASE_OUT}/browser_capture_${TS}"
PROFILE_DIR=".browser_profiles/instagram"

mkdir -p "$OUTDIR" "$PROFILE_DIR"

echo "URL: $URL"
echo "SHORTCODE: $SHORTCODE"
echo "OUTDIR: $OUTDIR"
echo "PROFILE_DIR: $PROFILE_DIR"
echo

python3 - "$URL" "$SHORTCODE" "$OUTDIR" "$PROFILE_DIR" <<'PY'
import asyncio
import json
import re
import sys
from pathlib import Path

url = sys.argv[1]
target = sys.argv[2]
outdir = Path(sys.argv[3])
profile_dir = sys.argv[4]

try:
    from playwright.async_api import async_playwright
except Exception:
    print("ERROR: Playwright not installed.")
    print("Run:")
    print("  pip install playwright")
    print("  python -m playwright install chromium")
    raise SystemExit(2)

captured = []
items = []

def best_image(obj):
    c = obj.get("image_versions2", {}).get("candidates", [])
    if not c:
        return None
    best = max(c, key=lambda x: (x.get("width", 0) or 0) * (x.get("height", 0) or 0))
    return best.get("url")

def best_video(obj):
    v = obj.get("video_versions", [])
    if not v:
        return None
    best = max(v, key=lambda x: (x.get("width", 0) or 0) * (x.get("height", 0) or 0))
    return best.get("url")

def add_media(obj):
    u = best_video(obj)
    if u:
        items.append(("video", u))
        return
    u = best_image(obj)
    if u:
        items.append(("image", u))

def handle_matching_post(obj):
    if not isinstance(obj, dict):
        return

    if obj.get("code") != target:
        return

    carousel = obj.get("carousel_media")
    if isinstance(carousel, list) and carousel:
        for child in carousel:
            if isinstance(child, dict):
                add_media(child)
    else:
        add_media(obj)

def walk(obj):
    if isinstance(obj, dict):
        handle_matching_post(obj)
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
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        async def on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                ru = response.url

                if not (
                    "graphql" in ru
                    or "api/" in ru
                    or "instagram.com" in ru
                    or "fbcdn.net" in ru
                ):
                    return

                text = await response.text()

                if target not in text and "image_versions2" not in text and "video_versions" not in text:
                    return

                rec = {
                    "url": ru,
                    "status": response.status,
                    "content_type": ct,
                    "text": text,
                }
                captured.append(rec)

                try:
                    walk(json.loads(text))
                except Exception:
                    walk(text)

            except Exception:
                return

        page.on("response", on_response)

        print("Opening page...")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        print()
        print("If Instagram asks you to log in, log in in the browser window.")
        print("Then wait for the post media to visibly load.")
        print("The script will keep probing for about 35 seconds.")
        print()

        # Give user/browser time. Also trigger lazy loads.
        for i in range(7):
            await page.wait_for_timeout(5000)
            try:
                await page.mouse.wheel(0, 700)
                await page.wait_for_timeout(800)
                await page.mouse.wheel(0, -700)
            except Exception:
                pass

            # Try carousel next button if present.
            for label in ["Next", "Go to next", "Next photo"]:
                try:
                    loc = page.get_by_label(label)
                    if await loc.count():
                        await loc.first.click(timeout=1000)
                        await page.wait_for_timeout(1200)
                except Exception:
                    pass

            print(f"probe_round={i+1} captured_responses={len(captured)} media_items={len(items)}")

        await context.close()

asyncio.run(main())

# Dedupe media
seen = set()
clean = []
for kind, media_url in items:
    if media_url in seen:
        continue
    seen.add(media_url)
    clean.append((kind, media_url))

(outdir / "captured_responses.jsonl").write_text(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in captured)
)

(outdir / "media_urls.txt").write_text(
    "\n".join(u for _, u in clean) + ("\n" if clean else "")
)

with (outdir / "selected_items.jsonl").open("w") as f:
    for i, (kind, media_url) in enumerate(clean, 1):
        f.write(json.dumps({
            "n": i,
            "shortcode": target,
            "kind": kind,
            "url": media_url,
        }, ensure_ascii=False) + "\n")

print()
print(f"clean_items={len(clean)}")
for i, (kind, media_url) in enumerate(clean, 1):
    print(f"{i:03d} {kind} {media_url[:160]}")
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

  case "$ext" in
    jpg|jpeg|png|webp|mp4) ;;
    *) ext="bin" ;;
  esac

  file="$(printf "%s/%03d.%s" "$OUTDIR" "$n" "$ext")"

  echo "[$n] $file"

  curl -L --silent --fail -A "Mozilla/5.0" "$url" -o "$file"

  sha="$(sha256sum "$file" | awk '{print $1}')"
  size="$(wc -c < "$file" | tr -d ' ')"
  mime="$(file -b --mime-type "$file" || true)"

  printf '{"n":%s,"shortcode":"%s","file":"%s","sha256":"%s","size":%s,"mime":"%s","url":"%s"}\n' \
    "$n" "$SHORTCODE" "$file" "$sha" "$size" "$mime" "$url" >> "$MANIFEST"

done < "$OUTDIR/media_urls.txt"

echo
echo "DONE:"
echo "$OUTDIR"
echo
echo "Key files:"
echo "  $OUTDIR/captured_responses.jsonl"
echo "  $OUTDIR/media_urls.txt"
echo "  $OUTDIR/selected_items.jsonl"
echo "  $OUTDIR/manifest.jsonl"
