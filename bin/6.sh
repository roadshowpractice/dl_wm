#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/6.sh 'https://www.instagram.com/p/SHORTCODE/?img_index=2'}"
COOKIE_FILE="${2:-conf/instagram.cookies.txt}"

TODAY="$(date +%F)"
TS="$(date +%Y%m%d_%H%M%S)"
SHORTCODE="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"

BASE_OUT="outputs/${TODAY}/instagram__${SHORTCODE}"
OUTDIR="${BASE_OUT}/probes/html_json_${TS}"

mkdir -p "$OUTDIR"

HTML_NOCOOKIE="$OUTDIR/page_nocookie.html"
HTML_COOKIE="$OUTDIR/page_cookie.html"
REPORT="$OUTDIR/report.txt"

echo "URL: $URL"
echo "SHORTCODE: $SHORTCODE"
echo "BASE_OUT: $BASE_OUT"
echo "OUTDIR: $OUTDIR"
echo "COOKIE_FILE: $COOKIE_FILE"
echo

echo "Fetching no-cookie HTML..."
curl -L \
  -A "Mozilla/5.0" \
  -H "Accept-Language: en-US,en;q=0.9" \
  "$URL" > "$HTML_NOCOOKIE"

echo "Fetching cookie HTML..."
if [ -s "$COOKIE_FILE" ]; then
  curl -L \
    -A "Mozilla/5.0" \
    -H "Accept-Language: en-US,en;q=0.9" \
    -b "$COOKIE_FILE" \
    "$URL" > "$HTML_COOKIE"
else
  echo "WARNING: cookie file missing or empty: $COOKIE_FILE"
  cp "$HTML_NOCOOKIE" "$HTML_COOKIE"
fi

echo
echo "Analyzing HTML payloads..."

python3 - "$HTML_NOCOOKIE" "$HTML_COOKIE" "$OUTDIR" "$REPORT" <<'PY'
import re
import html
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

nocookie = Path(sys.argv[1])
cookie = Path(sys.argv[2])
outdir = Path(sys.argv[3])
report = Path(sys.argv[4])

def load(p):
    text = p.read_text(errors="ignore")
    text = html.unescape(text)
    text = (
        text.replace("\\u0026", "&")
            .replace("\\/", "/")
            .replace("&amp;", "&")
    )
    return text

def urls_from(text):
    pat = r'https://[^"\']+?(?:cdninstagram\.com|fbcdn\.net)/[^"\']+?\.(?:jpg|jpeg|png|webp|mp4)[^"\']*'
    seen = []
    for u in re.findall(pat, text):
        if u not in seen:
            seen.append(u)
    return seen

def real_media(urls):
    real = []
    junk = []
    for u in urls:
        host = urlparse(u).netloc.lower()
        if "static.cdninstagram.com" in host:
            junk.append(u)
        elif "scontent.cdninstagram.com" in host:
            real.append(u)
        elif "fbcdn.net" in host and ".mp4" in u.lower():
            real.append(u)
        else:
            junk.append(u)
    return real, junk

def keyword_hits(text):
    keys = [
        "carousel_media",
        "edge_sidecar_to_children",
        "GraphSidecar",
        "shortcode_media",
        "display_url",
        "video_url",
        "is_video",
        "__additionalDataLoaded",
        "window._sharedData",
        "xdt_shortcode_media",
    ]
    return {k: text.count(k) for k in keys}

def write_list(path, items):
    Path(path).write_text("\n".join(items) + ("\n" if items else ""))

texts = {
    "nocookie": load(nocookie),
    "cookie": load(cookie),
}

lines = []

for label, text in texts.items():
    urls = urls_from(text)
    real, junk = real_media(urls)

    write_list(outdir / f"{label}_raw_candidates.txt", urls)
    write_list(outdir / f"{label}_real_media_candidates.txt", real)
    write_list(outdir / f"{label}_junk_candidates.txt", junk)

    hits = keyword_hits(text)

    lines.append(f"== {label} ==")
    lines.append(f"bytes={len(text)}")
    lines.append(f"raw_candidates={len(urls)}")
    lines.append(f"real_media_candidates={len(real)}")
    lines.append(f"junk_candidates={len(junk)}")
    for k, v in hits.items():
        lines.append(f"{k}={v}")

    lines.append("")
    lines.append("real media:")
    for i, u in enumerate(real, 1):
        lines.append(f"{i:03d} {u[:260]}")
    lines.append("")

    # Save small context snippets around promising JSON words.
    snip_dir = outdir / f"{label}_snippets"
    snip_dir.mkdir(exist_ok=True)

    for key in hits:
        if hits[key] <= 0:
            continue
        idx = 0
        n = 0
        while True:
            pos = text.find(key, idx)
            if pos < 0:
                break
            n += 1
            start = max(0, pos - 3000)
            end = min(len(text), pos + 3000)
            (snip_dir / f"{key}_{n:03d}.txt").write_text(text[start:end])
            idx = pos + len(key)
            if n >= 10:
                break

report.write_text("\n".join(lines) + "\n")
print(report.read_text())
PY

echo
echo "Downloading cookie real-media candidates, if any..."

CAND="$OUTDIR/cookie_real_media_candidates.txt"
MANIFEST="$OUTDIR/manifest.jsonl"

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
  sha="$(sha256sum "$file" | awk '{print $1}')"
  dims="$(identify "$file" 2>/dev/null | awk '{print $3}' || true)"

  printf '{"n":%s,"file":"%s","bytes":%s,"mime":"%s","sha256":"%s","dims":"%s","url":"%s"}\n' \
    "$n" "$file" "$bytes" "$mime" "$sha" "$dims" "$media_url" >> "$MANIFEST"

done < "$CAND"

echo
echo "DONE:"
echo "$OUTDIR"
echo
echo "Key files:"
echo "  $REPORT"
echo "  $OUTDIR/cookie_real_media_candidates.txt"
echo "  $OUTDIR/cookie_snippets/"
echo "  $MANIFEST"
echo
echo "Open:"
echo "xdg-open '$OUTDIR' 2>/dev/null || open '$OUTDIR'"
