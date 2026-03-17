#!/usr/bin/env bash
set -euo pipefail

JSONL="${1:-clips_collated_renumbered.jsonl}"
CLIP_DIR="${2:-clips}"

if [[ ! -f "$JSONL" ]]; then
  echo "ERROR: JSONL file not found: $JSONL" >&2
  exit 1
fi

mkdir -p "$CLIP_DIR"

SRC="$(find . -maxdepth 1 -type f -name '*_watermarked.mp4' | sort | head -n1)"

if [[ -z "${SRC:-}" ]]; then
  echo "ERROR: no *_watermarked.mp4 found in $(pwd)" >&2
  exit 1
fi

command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not found"; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "ERROR: ffmpeg not found"; exit 1; }

echo "Using source video: $SRC"
echo "Reading jobs from:   $JSONL"
echo "Writing clips to:    $CLIP_DIR"
echo

count=0
ok=0
fail=0

exec 3< "$JSONL"
while IFS= read -r line <&3 || [[ -n "$line" ]]; do
  [[ -z "${line//[[:space:]]/}" ]] && continue

  count=$((count + 1))

  id="$(printf '%s\n' "$line" | jq -r '.id // empty')"
  start="$(printf '%s\n' "$line" | jq -r '.start // empty')"
  end="$(printf '%s\n' "$line" | jq -r '.end // empty')"
  caption="$(printf '%s\n' "$line" | jq -r '.caption // empty')"

  if [[ -z "$id" || -z "$start" || -z "$end" ]]; then
    echo "[$count] SKIP: missing id/start/end"
    fail=$((fail + 1))
    continue
  fi

  safe_id="$(printf '%s' "$id" | tr ' /' '__' | tr -cd '[:alnum:]_.-')"
  outfile="$CLIP_DIR/${safe_id}.mp4"

  echo "[$count] Making $outfile"
  echo "      start=$start end=$end"
  [[ -n "$caption" ]] && echo "      caption=$caption"

  if ffmpeg -nostdin -y \
    -ss "$start" \
    -to "$end" \
    -i "$SRC" \
    -c:v libx264 -preset slow -crf 18 \
    -c:a aac -b:a 192k \
    -movflags +faststart \
    "$outfile" </dev/null
  then
    ok=$((ok + 1))
  else
    echo "[$count] FAILED: $id" >&2
    fail=$((fail + 1))
  fi

  echo
done

exec 3<&-

echo "Done."
echo "Total:   $count"
echo "Success: $ok"
echo "Failed:  $fail"
