#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/probe_insta_p.sh 'https://www.instagram.com/p/SHORTCODE/?img_index=2'}"

TS="$(date +%Y%m%d_%H%M%S)"
SHORTCODE="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"
OUTDIR="outputs/insta_probe_${SHORTCODE}_${TS}"
mkdir -p "$OUTDIR"

HTML="$OUTDIR/page.html"
CAND="$OUTDIR/candidates.txt"
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

echo "Extracting CDN media candidates..."

python3 - "$HTML" "$CAND" <<'PY'
import re, html, sys
from pathlib import Path

page = Path(sys.argv[1]).read_text(errors="ignore")
out = Path(sys.argv[2])

# Decode escaped JSON-ish junk
text = html.unescape(page)
text = text.replace("\\u0026", "&").replace("\\/", "/")

patterns = [
    r'https://[^"\']+?cdninstagram\.com/[^"\']+?\.(?:jpg|jpeg|png|webp|mp4)[^"\']*',
    r'https://[^"\']+?fbcdn\.net/[^"\']+?\.(?:jpg|jpeg|png|webp|mp4)[^"\']*',
]

seen = []
for pat in patterns:
    for m in re.findall(pat, text):
        m = m.replace("&amp;", "&")
        if m not in seen:
            seen.append(m)

out.write_text("\n".join(seen) + ("\n" if seen else ""))
print(f"candidates={len(seen)}")
for i, u in enumerate(seen, 1):
    print(f"{i:03d} {u[:220]}")
PY

echo
echo "Downloading candidates..."

n=0
while IFS= read -r media_url; do
  [ -z "$media_url" ] && continue
  n=$((n+1))

  ext="bin"
  case "$media_url" in
    *.mp4* ) ext="mp4" ;;
    *.jpg*|*.jpeg* ) ext="jpg" ;;
    *.png* ) ext="png" ;;
    *.webp* ) ext="webp" ;;
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
echo "Probing downloaded files..."
find "$OUTDIR" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.webp' -o -name '*.mp4' \) -print0 |
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
echo "Open:"
echo "xdg-open '$OUTDIR' 2>/dev/null || open '$OUTDIR'"
