#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:?Usage: bash bin/5.sh 'https://www.instagram.com/p/SHORTCODE/'}"
MAX="${2:-10}"

SHORTCODE="$(printf '%s\n' "$BASE_URL" | sed -E 's#.*instagram.com/p/([^/?#]+).*#\1#')"
TS="$(date +%Y%m%d_%H%M%S)"
OUTDIR="outputs/insta_index_probe_${SHORTCODE}_${TS}"
mkdir -p "$OUTDIR"

echo "BASE_URL: $BASE_URL"
echo "SHORTCODE: $SHORTCODE"
echo "MAX: $MAX"
echo "OUTDIR: $OUTDIR"
echo

for i in $(seq 1 "$MAX"); do
  URL="https://www.instagram.com/p/${SHORTCODE}/?img_index=${i}"
  RUN="$OUTDIR/img_index_${i}"
  mkdir -p "$RUN"

  echo
  echo "===== img_index=$i ====="

  bash bin/4.sh "$URL" | tee "$RUN/run.log"

  FOUND_DIR="$(grep '^DONE:' -A1 "$RUN/run.log" | tail -n1 | tr -d '\r')"

  if [ -d "$FOUND_DIR" ]; then
    cp -a "$FOUND_DIR"/. "$RUN"/
  fi

  img="$(find "$RUN" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.jpeg' -o -name '*.png' -o -name '*.webp' -o -name '*.mp4' \) | head -n1 || true)"

  if [ -n "$img" ]; then
    sha="$(sha256sum "$img" | awk '{print $1}')"
    mime="$(file -b --mime-type "$img" || true)"
    size="$(wc -c < "$img" | tr -d ' ')"
    dims="$(identify "$img" 2>/dev/null | awk '{print $3}' || true)"

    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$i" "$sha" "$mime" "$size" "$dims" "$img" >> "$OUTDIR/summary.tsv"

    echo "sha=$sha"
    echo "mime=$mime size=$size dims=$dims"
  else
    printf '%s\tNO_MEDIA\n' "$i" >> "$OUTDIR/summary.tsv"
    echo "NO_MEDIA"
  fi
done

echo
echo "===== SUMMARY ====="
column -t -s $'\t' "$OUTDIR/summary.tsv" || cat "$OUTDIR/summary.tsv"

echo
echo "Unique hashes:"
awk -F '\t' 'NF >= 2 {print $2}' "$OUTDIR/summary.tsv" | sort | uniq -c

echo
echo "DONE:"
echo "$OUTDIR"
