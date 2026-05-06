#!/usr/bin/env bash
set -euo pipefail

URL="${1:?Usage: bash bin/8.sh 'https://www.instagram.com/p/SHORTCODE/'}"
COOKIE_FILE="${2:-conf/instagram.cookies.txt}"

TODAY="$(date +%F)"
TS="$(date +%Y%m%d_%H%M%S)"
SHORTCODE="$(printf '%s\n' "$URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"

BASE_OUT="outputs/${TODAY}/instagram__${SHORTCODE}"
OUTDIR="${BASE_OUT}/probes/ytdlp_info_${TS}"
mkdir -p "$OUTDIR"

echo "URL: $URL"
echo "SHORTCODE: $SHORTCODE"
echo "OUTDIR: $OUTDIR"
echo "COOKIE_FILE: $COOKIE_FILE"
echo

echo "Running yt-dlp metadata probe..."
yt-dlp \
  --cookies "$COOKIE_FILE" \
  --skip-download \
  --write-info-json \
  --ignore-errors \
  --no-warnings \
  -o "${OUTDIR}/%(playlist_index,NA)s__%(id)s.%(ext)s" \
  "$URL" \
  > "$OUTDIR/ytdlp.stdout.log" \
  2> "$OUTDIR/ytdlp.stderr.log" || true

echo
echo "yt-dlp stderr:"
cat "$OUTDIR/ytdlp.stderr.log"

echo
echo "Info JSON files found:"
find "$OUTDIR" -maxdepth 1 -name "*.info.json" -print | sort | tee "$OUTDIR/info_files.txt"

echo
echo "Extracting likely media URLs from info JSON..."

python3 - "$OUTDIR" <<'PY'
import json
import sys
from pathlib import Path

outdir = Path(sys.argv[1])
manifest = outdir / "extracted_media_urls.jsonl"
summary = outdir / "summary.tsv"

keys_to_check = [
    "url",
    "webpage_url",
    "thumbnail",
    "display_url",
    "original_url",
]

def walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk(item)

rows = []

for p in sorted(outdir.glob("*.info.json")):
    try:
        data = json.loads(p.read_text(errors="ignore"))
    except Exception as e:
        rows.append({
            "file": str(p),
            "error": str(e),
        })
        continue

    found = []
    for k, v in walk(data):
        if isinstance(v, str) and (
            "cdninstagram.com" in v
            or "fbcdn.net" in v
            or ".jpg" in v
            or ".mp4" in v
        ):
            found.append((k, v))

    # de-dupe while preserving order
    seen = set()
    deduped = []
    for k, v in found:
        if v in seen:
            continue
        seen.add(v)
        deduped.append((k, v))

    item = {
        "info_json": str(p),
        "id": data.get("id"),
        "title": data.get("title"),
        "extractor": data.get("extractor"),
        "playlist_index": data.get("playlist_index"),
        "ext": data.get("ext"),
        "url": data.get("url"),
        "thumbnail": data.get("thumbnail"),
        "candidate_count": len(deduped),
        "candidates": [{"key": k, "url": v} for k, v in deduped],
    }

    rows.append(item)

with manifest.open("w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

with summary.open("w") as f:
    f.write("info_json\tid\tplaylist_index\text\tcandidate_count\turl\tthumbnail\n")
    for r in rows:
        f.write(
            f"{r.get('info_json','')}\t"
            f"{r.get('id','')}\t"
            f"{r.get('playlist_index','')}\t"
            f"{r.get('ext','')}\t"
            f"{r.get('candidate_count','')}\t"
            f"{r.get('url','')}\t"
            f"{r.get('thumbnail','')}\n"
        )

print(f"Wrote: {manifest}")
print(f"Wrote: {summary}")
PY

echo
echo "SUMMARY:"
column -t -s $'\t' "$OUTDIR/summary.tsv" || cat "$OUTDIR/summary.tsv"

echo
echo "Candidate media URLs:"
jq -r '.candidates[]?.url' "$OUTDIR/extracted_media_urls.jsonl" 2>/dev/null \
  | grep -E 'cdninstagram|fbcdn|\.jpg|\.mp4' \
  | sort -u \
  | tee "$OUTDIR/unique_candidate_urls.txt" || true

echo
echo "DONE:"
echo "$OUTDIR"
echo
echo "Key files:"
echo "  $OUTDIR/ytdlp.stderr.log"
echo "  $OUTDIR/info_files.txt"
echo "  $OUTDIR/summary.tsv"
echo "  $OUTDIR/extracted_media_urls.jsonl"
echo "  $OUTDIR/unique_candidate_urls.txt"
