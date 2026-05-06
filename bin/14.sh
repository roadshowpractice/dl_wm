#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/14.sh 'https://www.instagram.com/p/SHORTCODE/'}"

COOKIE_FILE="${COOKIE_FILE:-conf/instagram.cookies.txt}"

SHORTCODE="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"

TODAY="$(date +%F)"

CAPTURE="$(ls -td outputs/${TODAY}/instagram__${SHORTCODE}/cookie_browser_capture_*/captured_responses.jsonl 2>/dev/null | head -1 || true)"

if [ -z "$CAPTURE" ]; then
  echo "ERROR: no capture found"
  exit 1
fi

OUTDIR="outputs/${TODAY}/instagram__${SHORTCODE}/loose_extract_$(date +%H%M%S)"
mkdir -p "$OUTDIR"

echo "CAPTURE: $CAPTURE"
echo "OUTDIR:  $OUTDIR"

# 🔥 extract all media urls
grep -o 'https://[^"\\]*\(jpg\|jpeg\|webp\|mp4\)[^"\\]*' "$CAPTURE" \
  | sed 's/\\u0026/\&/g; s/\\\//\//g' \
  | grep -E 'cdninstagram|fbcdn' \
  | sort -u \
  > "$OUTDIR/all_urls.txt"

# 🔥 filter junk (small thumbs, profile pics)
grep -Ev 's150x150|_s150x150|profile_pic' "$OUTDIR/all_urls.txt" \
  > "$OUTDIR/filtered_urls.txt"

echo
echo "ALL URLS:"
wc -l "$OUTDIR/all_urls.txt"

echo "FILTERED URLS:"
wc -l "$OUTDIR/filtered_urls.txt"

echo
echo "Preview:"
head "$OUTDIR/filtered_urls.txt"

# 🔥 download
echo
echo "Downloading..."

n=0
while read -r url; do
  [ -z "$url" ] && continue
  n=$((n+1))

  clean="${url%%\?*}"
  ext="${clean##*.}"

  file=$(printf "%s/%03d.%s" "$OUTDIR" "$n" "$ext")

  echo "[$n] $file"

  if ! curl -L --silent --show-error --fail \
    -A "Mozilla/5.0" \
    -b "$COOKIE_FILE" \
    "$url" \
    -o "$file"; then
    echo "SKIP failed: $url" >&2
    rm -f "$file"
    continue
  fi

done < "$OUTDIR/filtered_urls.txt"

echo
echo "DONE:"
echo "$OUTDIR"
