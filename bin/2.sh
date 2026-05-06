#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/ig_carousel_candidates.sh INSTAGRAM_URL [OUTDIR]}"
OUTDIR="${2:-outputs/ig_candidates_$(date +%Y%m%d_%H%M%S)}"
COOKIE="${COOKIE:-conf/instagram.cookies.txt}"

mkdir -p "$OUTDIR"

echo "Fetching HTML..."
curl -L -s \
  -A "Mozilla/5.0" \
  -b "$COOKIE" \
  "$URL" > "$OUTDIR/page.html"

echo "Extracting Instagram CDN jpg candidates..."
python - "$OUTDIR/page.html" "$OUTDIR/urls.txt" <<'PY'
import re, sys, html
from pathlib import Path

html_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = html.unescape(html_path.read_text(errors="ignore"))

urls = re.findall(r'https://scontent[^"\'\\<>\s]+', text)
clean = []
seen = set()

for u in urls:
    u = u.replace("\\u0026", "&").replace("\\/", "/")
    if not any(x in u for x in [".jpg", ".jpeg", "t51.82787", "t51.29350"]):
        continue
    if "profile" in u.lower():
        continue
    key = u.split("?")[0]
    if key in seen:
        continue
    seen.add(key)
    clean.append(u)

out_path.write_text("\n".join(clean) + "\n")
print(f"candidates={len(clean)}")
for i, u in enumerate(clean[:30], 1):
    print(f"{i:03d} {u[:140]}")
PY

echo "Downloading first 30 candidates..."
n=0
while IFS= read -r img; do
  n=$((n+1))
  [ "$n" -gt 30 ] && break
  printf -v num "%03d" "$n"
  curl -L -s "$img" -o "$OUTDIR/candidate_${num}.jpg" || true
done < "$OUTDIR/urls.txt"

echo
echo "Done:"
echo "$OUTDIR"
echo
echo "Open candidates:"
echo "xdg-open '$OUTDIR' 2>/dev/null || open '$OUTDIR'"

