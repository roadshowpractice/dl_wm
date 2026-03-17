#!/usr/bin/env bash
set -euo pipefail

JSONL="${1:-clips1.jsonl}"
CLIP_DIR="${2:-clips}"

URL="${3:-https://www.youtube.com/watch?v=Jw0Snx7x_jI}"
UPLOAD_DATE="${4:-2026-01-07}"
UPLOADER="${5:-We Are The People Utah}"

FONT="${FONT:-$HOME/Desktop/dl_wm/fonts/Inter-Bold.otf}"
WIDTH="${WIDTH:-1920}"
HEIGHT="${HEIGHT:-1080}"
FPS="${FPS:-30}"
INTRO_SECONDS="${INTRO_SECONDS:-2}"
BLACK_SECONDS="${BLACK_SECONDS:-0.5}"

[[ -f "$JSONL" ]] || { echo "ERROR: JSONL file not found: $JSONL" >&2; exit 1; }
[[ -f "$FONT" ]] || { echo "ERROR: font not found: $FONT" >&2; exit 1; }

mkdir -p "$CLIP_DIR"

SRC="$(find . -maxdepth 1 -type f -name '*_watermarked.mp4' | sort | head -n1)"
[[ -n "${SRC:-}" ]] || { echo "ERROR: no *_watermarked.mp4 found in $(pwd)" >&2; exit 1; }

command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not found" >&2; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "ERROR: ffmpeg not found" >&2; exit 1; }

echo "Source video:  $SRC"
echo "Clip manifest: $JSONL"
echo "Output dir:    $CLIP_DIR"
echo "URL:           $URL"
echo "Uploader:      $UPLOADER"
echo "Upload date:   $UPLOAD_DATE"
echo "Font:          $FONT"
echo "Intro seconds: $INTRO_SECONDS"
echo "Black seconds: $BLACK_SECONDS"
echo

esc_drawtext() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//:/\\:}"
  s="${s//\'/\\\'}"
  s="${s//\[/\\[}"
  s="${s//\]/\\]}"
  s="${s//,/\\,}"
  s="${s//%/\\%}"
  printf '%s' "$s"
}

count=0
ok=0
fail=0

exec 3< "$JSONL"
while IFS= read -r line <&3 || [[ -n "$line" ]]; do
  [[ -z "${line//[[:space:]]/}" ]] && continue

  if ! printf '%s\n' "$line" | jq . >/dev/null 2>&1; then
    echo "[SKIP] invalid JSON: $line" >&2
    fail=$((fail + 1))
    continue
  fi

  count=$((count + 1))

  id="$(printf '%s\n' "$line" | jq -r '.clip_id // .id // empty')"
  start="$(printf '%s\n' "$line" | jq -r '.start // empty')"
  end="$(printf '%s\n' "$line" | jq -r '.end // empty')"
  caption="$(printf '%s\n' "$line" | jq -r '.comment // .caption // empty')"

  if [[ -z "$id" || -z "$start" || -z "$end" ]]; then
    echo "[$count] SKIP: missing clip_id/id or start/end"
    fail=$((fail + 1))
    continue
  fi

  safe_id="$(printf '%s' "$id" | tr ' /' '__' | tr -cd '[:alnum:]_.-')"

  clip_raw="$CLIP_DIR/${safe_id}__clip_raw.mp4"
  intro_raw="$CLIP_DIR/${safe_id}__intro_raw.mp4"
  black_raw="$CLIP_DIR/${safe_id}__black_raw.mp4"
  clip_norm="$CLIP_DIR/${safe_id}__clip_norm.mp4"
  intro_norm="$CLIP_DIR/${safe_id}__intro_norm.mp4"
  black_norm="$CLIP_DIR/${safe_id}__black_norm.mp4"
  concat_list="$CLIP_DIR/${safe_id}__concat.txt"
  final="$CLIP_DIR/${safe_id}.mp4"

  echo "[$count] Processing $safe_id"
  echo "      start=$start end=$end"
  [[ -n "$caption" ]] && echo "      comment=$caption"

  rm -f "$clip_raw" "$intro_raw" "$black_raw" "$clip_norm" "$intro_norm" "$black_norm" "$concat_list" "$final"

  if ! ffmpeg -nostdin -y \
    -ss "$start" \
    -to "$end" \
    -i "$SRC" \
    -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -movflags +faststart \
    "$clip_raw" </dev/null
  then
    echo "[$count] FAILED cutting clip: $safe_id" >&2
    fail=$((fail + 1))
    echo
    continue
  fi

  seg_text="$(esc_drawtext "SOURCE VIDEO SEGMENT")"
  seg_val="$(esc_drawtext "$start - $end")"
  url_text="$(esc_drawtext "SOURCE URL")"
  url_val="$(esc_drawtext "$URL")"
  up_text="$(esc_drawtext "UPLOADER")"
  up_val="$(esc_drawtext "$UPLOADER")"
  date_text="$(esc_drawtext "UPLOAD DATE")"
  date_val="$(esc_drawtext "$UPLOAD_DATE")"
  cap_val="$(esc_drawtext "$caption")"

  vf="drawtext=fontfile=${FONT}:text='${seg_text}':fontcolor=black:fontsize=42:x=(w-text_w)/2:y=95,\
drawtext=fontfile=${FONT}:text='${seg_val}':fontcolor=black:fontsize=58:x=(w-text_w)/2:y=150,\
drawtext=fontfile=${FONT}:text='${url_text}':fontcolor=black:fontsize=30:x=110:y=300,\
drawtext=fontfile=${FONT}:text='${url_val}':fontcolor=black:fontsize=26:x=110:y=345,\
drawtext=fontfile=${FONT}:text='${up_text}':fontcolor=black:fontsize=30:x=110:y=460,\
drawtext=fontfile=${FONT}:text='${up_val}':fontcolor=black:fontsize=34:x=110:y=505,\
drawtext=fontfile=${FONT}:text='${date_text}':fontcolor=black:fontsize=30:x=110:y=620,\
drawtext=fontfile=${FONT}:text='${date_val}':fontcolor=black:fontsize=34:x=110:y=665"

  if [[ -n "$caption" ]]; then
    vf+=",drawtext=fontfile=${FONT}:text='${cap_val}':fontcolor=black:fontsize=58:x=(w-text_w)/2:y=860:box=1:boxcolor=white@0.85:boxborderw=24"
  fi

  if ! ffmpeg -nostdin -y \
    -f lavfi -i "color=c=white:s=${WIDTH}x${HEIGHT}:r=${FPS}:d=${INTRO_SECONDS}" \
    -f lavfi -i "anullsrc=r=44100:cl=stereo" \
    -vf "$vf" \
    -c:v libx264 -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -shortest \
    "$intro_raw" </dev/null
  then
    echo "[$count] FAILED rendering intro: $safe_id" >&2
    fail=$((fail + 1))
    echo
    continue
  fi

  if ! ffmpeg -nostdin -y \
    -f lavfi -i "color=c=black:s=${WIDTH}x${HEIGHT}:r=${FPS}:d=${BLACK_SECONDS}" \
    -f lavfi -i "anullsrc=r=44100:cl=stereo" \
    -c:v libx264 -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -shortest \
    "$black_raw" </dev/null
  then
    echo "[$count] FAILED rendering black spacer: $safe_id" >&2
    fail=$((fail + 1))
    echo
    continue
  fi

  if ! ffmpeg -nostdin -y \
    -i "$intro_raw" \
    -r "$FPS" \
    -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -movflags +faststart \
    "$intro_norm" </dev/null
  then
    echo "[$count] FAILED normalizing intro: $safe_id" >&2
    fail=$((fail + 1))
    echo
    continue
  fi

  if ! ffmpeg -nostdin -y \
    -i "$black_raw" \
    -r "$FPS" \
    -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -movflags +faststart \
    "$black_norm" </dev/null
  then
    echo "[$count] FAILED normalizing black spacer: $safe_id" >&2
    fail=$((fail + 1))
    echo
    continue
  fi

  if ! ffmpeg -nostdin -y \
    -i "$clip_raw" \
    -r "$FPS" \
    -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -movflags +faststart \
    "$clip_norm" </dev/null
  then
    echo "[$count] FAILED normalizing clip: $safe_id" >&2
    fail=$((fail + 1))
    echo
    continue
  fi

  printf "file '%s'\nfile '%s'\nfile '%s'\n" \
    "$(basename "$intro_norm")" \
    "$(basename "$black_norm")" \
    "$(basename "$clip_norm")" \
    > "$concat_list"

  if ffmpeg -nostdin -y \
    -f concat -safe 0 \
    -i "$concat_list" \
    -c copy \
    -movflags +faststart \
    "$final" </dev/null
  then
    rm -f "$clip_raw" "$intro_raw" "$black_raw" "$clip_norm" "$intro_norm" "$black_norm" "$concat_list"
    ok=$((ok + 1))
    echo "      ✔ made $final"
  else
    echo "[$count] FAILED concatenating: $safe_id" >&2
    echo "      kept temp files for debugging in $CLIP_DIR"
    fail=$((fail + 1))
  fi

  echo
done

exec 3<&-

echo "Done."
echo "Total:   $count"
echo "Success: $ok"
echo "Failed:  $fail"
