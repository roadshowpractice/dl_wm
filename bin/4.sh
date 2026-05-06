#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/4.sh 'https://www.instagram.com/p/SHORTCODE/?img_index=2'}"

TS="$(date +%Y%m%d_%H%M%S)"
SHORTCODE="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"
OUTDIR="outputs/insta_probe_${SHORTCODE}_${TS}"

mkdir -p "$OUTDIR"

HTML="$OUTDIR/page.html"
RAW="$OUTDIR/raw_candidates.txt"
CAND="$OUTDIR/real_media_candidates.txt"
MANIFEST="$OUTDIR/manifest.jsonl"

echo "URL: $URL"
echo "SHORTCODE: $SHORTCODE"
echo "OUTDIR: $OUTDIR"
echo

echo "Fetching HTML..."
curl -L \
  -A "Mozilla/5.0" \
  -H "Accept-Language: en-US,en;q=0.9" \
  "$URL" > "$HTML"

echo
echo "Extracting and filtering REAL Instagram media candidates..."

python3 - "$HTML" "$RAW" "$CAND" <<'PY'
import re
import html
import sys
from pathlib import Path
from urllib.parse import urlparse

html_path = Path(sys.argv[1])
raw_path = Path(sys.argv[2])
cand_path = Path(sys.argv[3])

page = html_path.read_text(errors="ignore")

# Instagram often hides useful URLs behind JSON/HTML escaping.
text = html.unescape(page)
text = (
    text.replace("\\u0026", "&")
        .replace("\\/", "/")
        .replace("&amp;", "&")
)

# First collect broadly, so we can see what the page contains.
patterns = [
    r'https://[^"\']+?(?:cdninstagram\.com|fbcdn\.net)/[^"\']+?\.(?:jpg|jpeg|png|webp|mp4)[^"\']*',
]

seen = []
for pat in patterns:
    for u in re.findall(pat, text):
        u = u.replace("\\u0026", "&").replace("\\/", "/").replace("&amp;", "&")
        if u not in seen:
            seen.append(u)

raw_path.write_text("\n".join(seen) + ("\n" if seen else ""))

def is_real_media(u: str) -> bool:
    host = urlparse(u).netloc.lower()

    # Drop Instagram UI sprites/icons/app chrome.
    if "static.cdninstagram.com" in host:
        return False

    # Keep the actual post media CDN.
    if "scontent.cdninstagram.com" in host:
        return True

    # Keep fbcdn mp4s only; fbcdn images are usually noisier in probes.
    if "fbcdn.net" in host and ".mp4" in u.lower():
        return True

    return False

real = [u for u in seen if is_real_media(u)]
cand_path.write_text("\n".join(real) + ("\n" if real else ""))

print(f"raw_candidates={len(seen)}")
print(f"real_media_candidates={len(real)}")
for i, u in enumerate(real, 1):
    print(f"{i:03d} {u[:260]}")
PY

echo
echo "Downloading REAL media candidates..."

n=0
while IFS= read -r media_url; do
  [ -z "$media_url" ] && continue
  n=$((n+1))

  clean="${media_url%%\?*}"
  ext="${clean##*.}"
  ext="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"

  case "$ext" in
    jpg|jpeg|png|webp|mp4) ;;
    *) ext="bin" ;;
  esac

  file="$(printf "%s/%03d.%s" "$OUTDIR" "$n" "$ext")"

  echo "[$n] $file"
  curl -L --fail --silent --show-error \
    -A "Mozilla/5.0" \
    "$media_url" \
    -o "$file" || {
      echo "download_failed $media_url" >&2
      rm -f "$file"
      continue
    }

  bytes="$(wc -c < "$file" | tr -d ' ')"
  mime="$(file -b --mime-type "$file" || true)"

  printf '{"n":%s,"file":"%s","bytes":%s,"mime":"%s","url":"%s"}\n' \
    "$n" "$file" "$bytes" "$mime" "$media_url" >> "$MANIFEST"

done < "$CAND"

echo
echo "Probing downloaded REAL media..."
find "$OUTDIR" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.jpeg' -o -name '*.png' -o -name '*.webp' -o -name '*.mp4' \) -print0 |
while IFS= read -r -d '' f; do
  echo
  echo "== $f =="
  file "$f"

  if command -v identify >/dev/null 2>&1; then
    identify "$f" 2>/dev/null || true
  fi

  if command -v ffprobe >/dev/null 2>&1 && [[ "$f" == *.mp4 ]]; then
    ffprobe -hide_banner "$f" 2>&1 | sed 's/^/  /'
  fi
done

echo
echo "DONE:"
echo "$OUTDIR"
echo
echo "Files:"
echo "  HTML:      $HTML"
echo "  raw:       $RAW"
echo "  filtered:  $CAND"
echo "  manifest:  $MANIFEST"
echo
echo "Open:"
echo "xdg-open '$OUTDIR' 2>/dev/null || open '$OUTDIR'"
