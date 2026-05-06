#!/usr/bin/env bash
set -euo pipefail

HAR="${1:?Usage: bash bin/9.sh file.har SHORTCODE}"
SHORTCODE="${2:-unknown}"

TODAY="$(date +%F)"
TS="$(date +%Y%m%d_%H%M%S)"
BASE_OUT="outputs/${TODAY}/instagram__${SHORTCODE}"
OUTDIR="${BASE_OUT}/har_extract_${TS}"

mkdir -p "$OUTDIR"

echo "HAR: $HAR"
echo "SHORTCODE: $SHORTCODE"
echo "OUTDIR: $OUTDIR"
echo

echo "Extracting media URLs from HAR..."

python3 - "$HAR" "$OUTDIR" <<'PY'
import json
import re
import sys
from pathlib import Path

har_path = Path(sys.argv[1])
outdir = Path(sys.argv[2])

data = json.loads(har_path.read_text(errors="ignore"))

urls = []

def collect(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            collect(v)
    elif isinstance(obj, list):
        for item in obj:
            collect(item)
    elif isinstance(obj, str):
        if (
            "cdninstagram.com" in obj
            or "fbcdn.net" in obj
        ):
            if re.search(r'\.(jpg|jpeg|png|webp|mp4)', obj):
                urls.append(obj)

collect(data)

# dedupe
seen = set()
clean = []
for u in urls:
    if u in seen:
        continue
    seen.add(u)
    clean.append(u)

(outdir / "raw_urls.txt").write_text("\n".join(clean) + "\n")

print(f"found_urls={len(clean)}")
for i,u in enumerate(clean[:20],1):
    print(f"{i:03d} {u[:200]}")
PY

echo
echo "Filtering real media (drop UI junk)..."

grep -E 'scontent|fbcdn.*mp4' "$OUTDIR/raw_urls.txt" > "$OUTDIR/media_urls.txt" || true

echo "Filtered URLs:"
cat "$OUTDIR/media_urls.txt"

echo
echo "Downloading media..."

MANIFEST="$OUTDIR/manifest.jsonl"
n=0

while IFS= read -r url; do
  [ -z "$url" ] && continue
  n=$((n+1))

  clean="${url%%\?*}"
  ext="${clean##*.}"
  ext="$(echo "$ext" | tr '[:upper:]' '[:lower:]')"

  case "$ext" in
    jpg|jpeg|png|webp|mp4) ;;
    *) ext="bin" ;;
  esac

  file="$(printf "%s/%03d.%s" "$OUTDIR" "$n" "$ext")"

  echo "[$n] $file"

  curl -L --silent --fail \
    -A "Mozilla/5.0" \
    "$url" \
    -o "$file" || {
      echo "fail: $url"
      continue
    }

  sha="$(sha256sum "$file" | awk '{print $1}')"
  size="$(wc -c < "$file")"
  mime="$(file -b --mime-type "$file")"

  printf '{"n":%s,"file":"%s","sha256":"%s","size":%s,"mime":"%s","url":"%s"}\n' \
    "$n" "$file" "$sha" "$size" "$mime" "$url" >> "$MANIFEST"

done < "$OUTDIR/media_urls.txt"

echo
echo "DONE:"
echo "$OUTDIR"
echo
echo "Files:"
echo "  $OUTDIR/media_urls.txt"
echo "  $OUTDIR/manifest.jsonl"
