#!/usr/bin/env bash
set -euo pipefail

JSONL="${1:-clips1.jsonl}"
CLIP_DIR="${2:-short1}"
OUT="${3:-final_film.mp4}"
TITLE_IMAGE="${4:-jane.png}"

WIDTH="${WIDTH:-}"
HEIGHT="${HEIGHT:-}"
FPS="${FPS:-30}"
TITLE_SECONDS="${TITLE_SECONDS:-2}"
AUDIO_RATE="${AUDIO_RATE:-48000}"
AUDIO_CHANNELS="${AUDIO_CHANNELS:-2}"
AUDIO_LAYOUT="${AUDIO_LAYOUT:-stereo}"

[[ -f "$JSONL" ]] || { echo "ERROR: JSONL not found: $JSONL" >&2; exit 1; }
[[ -d "$CLIP_DIR" ]] || { echo "ERROR: clip dir not found: $CLIP_DIR" >&2; exit 1; }
[[ -f "$TITLE_IMAGE" ]] || { echo "ERROR: title image not found: $TITLE_IMAGE" >&2; exit 1; }

command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not found" >&2; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "ERROR: ffmpeg not found" >&2; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo "ERROR: ffprobe not found" >&2; exit 1; }
command -v readlink >/dev/null 2>&1 || { echo "ERROR: readlink not found" >&2; exit 1; }

if [[ -z "$WIDTH" || -z "$HEIGHT" ]]; then
  FIRST_CLIP="$(find "$CLIP_DIR" -maxdepth 1 -type f -name '*.mp4' | sort | head -n 1)"
  [[ -n "$FIRST_CLIP" ]] || { echo "ERROR: unable to auto-detect WIDTH/HEIGHT; no clips found in $CLIP_DIR" >&2; exit 1; }

  CLIP_DIMENSIONS="$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$FIRST_CLIP" | head -n1)"
  CLIP_WIDTH="${CLIP_DIMENSIONS%x*}"
  CLIP_HEIGHT="${CLIP_DIMENSIONS#*x}"

  [[ "$CLIP_WIDTH" =~ ^[0-9]+$ ]] || { echo "ERROR: failed to detect clip width from $FIRST_CLIP ($CLIP_DIMENSIONS)" >&2; exit 1; }
  [[ "$CLIP_HEIGHT" =~ ^[0-9]+$ ]] || { echo "ERROR: failed to detect clip height from $FIRST_CLIP ($CLIP_DIMENSIONS)" >&2; exit 1; }

  WIDTH="${WIDTH:-$CLIP_WIDTH}"
  HEIGHT="${HEIGHT:-$CLIP_HEIGHT}"
fi

TMP_DIR="$(mktemp -d)"
TMP_LIST="$TMP_DIR/concat.txt"
TITLE_MP4="$TMP_DIR/title_card.mp4"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

count=0
missing=0

echo "JSONL:       $JSONL"
echo "CLIP DIR:    $CLIP_DIR"
echo "OUTPUT:      $OUT"
echo "TITLE IMAGE: $TITLE_IMAGE"
echo

# build the front title card
ffmpeg -nostdin -y \
  -loop 1 -i "$TITLE_IMAGE" \
  -f lavfi -i "anullsrc=r=${AUDIO_RATE}:cl=${AUDIO_LAYOUT}" \
  -t "$TITLE_SECONDS" \
  -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,fps=${FPS},format=yuv420p" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -r "$FPS" \
  -c:a aac -ar "$AUDIO_RATE" -ac "$AUDIO_CHANNELS" -b:a 192k \
  -shortest \
  -movflags +faststart \
  "$TITLE_MP4"

printf "file '%s'\n" "$(readlink -f "$TITLE_MP4")" > "$TMP_LIST"

while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "${line//[[:space:]]/}" ]] && continue

  if ! printf '%s\n' "$line" | jq . >/dev/null 2>&1; then
    echo "[SKIP] invalid JSON: $line" >&2
    continue
  fi

  clip_id="$(printf '%s\n' "$line" | jq -r '.clip_id // .id // empty')"
  [[ -n "$clip_id" ]] || {
    echo "[SKIP] missing clip_id/id"
    continue
  }

  count=$((count + 1))

  exact="$CLIP_DIR/${clip_id}.mp4"
  candidate=""

  if [[ -f "$exact" ]]; then
    candidate="$exact"
  else
    shopt -s nullglob
    matches=( "$CLIP_DIR/${clip_id}"_*.mp4 )
    shopt -u nullglob
    if [[ ${#matches[@]} -gt 0 ]]; then
      candidate="${matches[0]}"
    fi
  fi

  if [[ -z "$candidate" ]]; then
    echo "[$count] MISSING: $clip_id" >&2
    missing=$((missing + 1))
    continue
  fi

  abs_path="$(readlink -f "$candidate")"
  printf "file '%s'\n" "$abs_path" >> "$TMP_LIST"
  echo "[$count] + $(basename "$candidate")"
done < "$JSONL"

echo

if [[ ! -s "$TMP_LIST" ]]; then
  echo "ERROR: nothing to concatenate" >&2
  exit 1
fi

if [[ "$missing" -gt 0 ]]; then
  echo "WARNING: $missing clip(s) were missing" >&2
fi

ffmpeg -nostdin -y \
  -f concat -safe 0 \
  -i "$TMP_LIST" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -r "$FPS" \
  -c:a aac -ar "$AUDIO_RATE" -ac "$AUDIO_CHANNELS" \
  -af "aresample=${AUDIO_RATE},aresample=async=1" \
  -movflags +faststart \
  "$OUT"

echo
echo "Done: $OUT"
