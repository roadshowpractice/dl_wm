#!/usr/bin/env bash
set -euo pipefail

HAR="${1:?Usage: bash bin/10.sh file.har [SHORTCODE]}"
SHORTCODE="${2:-${SHORTCODE:-DXpRfxKEzmE}}"

TODAY="$(date +%F)"
TS="$(date +%Y%m%d_%H%M%S)"
OUTDIR="outputs/${TODAY}/instagram__${SHORTCODE}/har_filtered_${TS}"

mkdir -p "$OUTDIR"

echo "HAR: $HAR"
echo "SHORTCODE: $SHORTCODE"
echo "OUTDIR: $OUTDIR"
echo

python3 - "$HAR" "$OUTDIR" "$SHORTCODE" <<'PY'
import json, sys
from pathlib import Path

har = json.loads(Path(sys.argv[1]).read_text(errors="ignore"))
outdir = Path(sys.argv[2])
target = sys.argv[3]

items = []

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

def handle_matching_post(obj):
    if not isinstance(obj, dict):
        return

    if obj.get("code") != target:
        return

    # If this is a carousel, use its children in order.
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
        # HAR response bodies are often escaped JSON strings.
        if obj.startswith("{") and target in obj:
            try:
                walk(json.loads(obj))
            except Exception:
                pass

walk(har)

# dedupe
seen = set()
clean = []
for kind, url in items:
    if url in seen:
        continue
    seen.add(url)
    clean.append((kind, url))

(outdir / "media_urls.txt").write_text("\n".join(u for _, u in clean) + ("\n" if clean else ""))

with (outdir / "selected_items.jsonl").open("w") as f:
    for i, (kind, url) in enumerate(clean, 1):
        f.write(json.dumps({
            "n": i,
            "shortcode": target,
            "kind": kind,
            "url": url
        }) + "\n")

print(f"clean_items={len(clean)}")
for i, (kind, url) in enumerate(clean, 1):
    print(f"{i:03d} {kind} {url[:140]}")
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
echo "  $OUTDIR/media_urls.txt"
echo "  $OUTDIR/selected_items.jsonl"
echo "  $OUTDIR/manifest.jsonl"
