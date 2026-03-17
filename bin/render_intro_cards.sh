#!/usr/bin/env bash
set -euo pipefail

JSONL="${1:-intro_cards.jsonl}"
OUTDIR="${2:-clips/intros}"
WIDTH="${3:-1920}"
HEIGHT="${4:-1080}"
FPS="${5:-30}"
FONT="${6:-/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf}"

if [[ ! -f "$JSONL" ]]; then
  echo "ERROR: JSONL not found: $JSONL" >&2
  exit 1
fi

if [[ ! -f "$FONT" ]]; then
  echo "ERROR: font not found: $FONT" >&2
  exit 1
fi

mkdir -p "$OUTDIR"

esc() {
  printf '%s' "$1" \
  | sed 's/\\/\\\\/g' \
  | sed "s/'/\\\\'/g" \
  | sed 's/:/\\:/g'
}

while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "${line//[[:space:]]/}" ]] && continue

  id="$(printf '%s\n' "$line" | jq -r '.id // empty')"
  clip_id="$(printf '%s\n' "$line" | jq -r '.clip_id // empty')"
  url="$(printf '%s\n' "$line" | jq -r '.url // empty')"
  upload_date="$(printf '%s\n' "$line" | jq -r '.upload_date // empty')"
  uploader="$(printf '%s\n' "$line" | jq -r '.uploader // empty')"
  title="$(printf '%s\n' "$line" | jq -r '.title // empty')"
  start="$(printf '%s\n' "$line" | jq -r '.segment_start // empty')"
  end="$(printf '%s\n' "$line" | jq -r '.segment_end // empty')"
  dur="$(printf '%s\n' "$line" | jq -r '.intro_duration // "00:00:02"')"

  [[ -z "$id" || -z "$clip_id" || -z "$url" || -z "$start" || -z "$end" ]] && continue

  outfile="$OUTDIR/${clip_id}_intro.mp4"

  line1="$(esc "Source URL: $url")"
  line2="$(esc "Uploader: $uploader")"
  line3="$(esc "Upload date: $upload_date")"
  line4="$(esc "Segment: $start - $end")"
  line5="$(esc "Title: $title")"

  ffmpeg -nostdin -y \
    -f lavfi -i "color=c=white:s=${WIDTH}x${HEIGHT}:d=2:r=${FPS}" \
    -vf "drawtext=fontfile=${FONT}:text='${line1}':fontcolor=black:fontsize=34:x=80:y=180,\
drawtext=fontfile=${FONT}:text='${line2}':fontcolor=black:fontsize=34:x=80:y=280,\
drawtext=fontfile=${FONT}:text='${line3}':fontcolor=black:fontsize=34:x=80:y=380,\
drawtext=fontfile=${FONT}:text='${line4}':fontcolor=black:fontsize=40:x=80:y=500,\
drawtext=fontfile=${FONT}:text='${line5}':fontcolor=black:fontsize=30:x=80:y=640" \
    -c:v libx264 -pix_fmt yuv420p -t "$dur" \
    "$outfile"

  echo "Made $outfile"
done < "$JSONL"
