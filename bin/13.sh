#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/13.sh 'https://www.instagram.com/p/SHORTCODE/'}"

# 🔥 COOKIE: env override OR default
COOKIE_FILE="${COOKIE_FILE:-conf/instagram.cookies.txt}"

SHORTCODE="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"

if [ -z "$SHORTCODE" ] || [ "$SHORTCODE" = "$URL" ]; then
  echo "ERROR: could not extract shortcode from URL: $URL"
  exit 1
fi

TODAY="$(date +%F)"

CAPTURE="$(
  ls -td "outputs/${TODAY}/instagram__${SHORTCODE}"/cookie_browser_capture_*/captured_responses.jsonl 2>/dev/null | head -1 || true
)"

if [ -z "$CAPTURE" ]; then
  echo "ERROR: no captured_responses.jsonl found for shortcode: $SHORTCODE"
  exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"
OUTDIR="outputs/${TODAY}/instagram__${SHORTCODE}/capture_extract_${TS}"

mkdir -p "$OUTDIR"

echo "URL:        $URL"
echo "SHORTCODE:  $SHORTCODE"
echo "CAPTURE:    $CAPTURE"
echo "COOKIE:     $COOKIE_FILE"
echo "OUTDIR:     $OUTDIR"
echo

python3 - "$CAPTURE" "$SHORTCODE" "$OUTDIR" <<'PY'
import json, sys
from pathlib import Path

capture = Path(sys.argv[1])
target = sys.argv[2]
outdir = Path(sys.argv[3])

items = []

def best_image(obj):
    c = obj.get("image_versions2", {}).get("candidates", [])
    if not c:
        return None
    return max(c, key=lambda x: (x.get("width",0) or 0)*(x.get("height",0) or 0)).get("url")

def best_video(obj):
    v = obj.get("video_versions", [])
    if not v:
        return None
    return max(v, key=lambda x: (x.get("width",0) or 0)*(x.get("height",0) or 0)).get("url")

def add_media(obj):
    u = best_video(obj)
    if u:
        items.append(("video", u))
        return
    u = best_image(obj)
    if u:
        items.append(("image", u))

def handle_item(item):
    if not isinstance(item, dict):
        return
    if item.get("code") != target:
        return
    carousel = item.get("carousel_media")
    if isinstance(carousel, list):
        for c in carousel:
            add_media(c)
    else:
        add_media(item)

def extract(obj):
    if isinstance(obj, dict):

        # 🔥 NEW IG API
        if "xdt_api__v1__media__shortcode__web_info" in obj:
            info = obj["xdt_api__v1__media__shortcode__web_info"]
            for item in info.get("items", []):
                handle_item(item)

        handle_item(obj)

        for v in obj.values():
            extract(v)

    elif isinstance(obj, list):
        for x in obj:
            extract(x)

    elif isinstance(obj, str):
        if obj.startswith("{") and target in obj:
            try:
                extract(json.loads(obj))
            except:
                pass

with capture.open(errors="ignore") as f:
    for line in f:
        try:
            extract(json.loads(line))
        except:
            pass

seen = set()
clean = []
for k,u in items:
    if u not in seen:
        seen.add(u)
        clean.append((k,u))

(outdir/"media_urls.txt").write_text("\n".join(u for _,u in clean)+"\n")

with (outdir/"selected_items.jsonl").open("w") as f:
    for i,(k,u) in enumerate(clean,1):
        f.write(json.dumps({
            "n":i,
            "shortcode":target,
            "kind":k,
            "url":u
        })+"\n")

print("clean_items=",len(clean))
for i,(k,u) in enumerate(clean,1):
    print(f"{i:03d}",k,u[:120])
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
  ext="$(echo "$ext" | tr '[:upper:]' '[:lower:]')"

  case "$ext" in jpg|jpeg|png|webp|mp4) ;; *) ext="bin" ;; esac

  file="$(printf "%s/%03d.%s" "$OUTDIR" "$n" "$ext")"

  echo "[$n] $file"

  curl -L --silent --fail \
    -A "Mozilla/5.0" \
    -b "$COOKIE_FILE" \
    "$url" \
    -o "$file"

  sha=$(sha256sum "$file" | awk '{print $1}')
  size=$(wc -c < "$file")

  printf '{"n":%s,"shortcode":"%s","file":"%s","sha256":"%s","size":%s,"url":"%s"}\n' \
    "$n" "$SHORTCODE" "$file" "$sha" "$size" "$url" >> "$MANIFEST"

done < "$OUTDIR/media_urls.txt"

echo
echo "DONE:"
echo "$OUTDIR"
