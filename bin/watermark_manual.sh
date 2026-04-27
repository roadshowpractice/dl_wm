#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'HELP'
Usage:
  bin/watermark_manual.sh INPUT_VIDEO OUTPUT_VIDEO "Uploader Name" "2026-04-26" "Video title here"

Description:
  Apply a watermark to an existing local video without downloader metadata JSON.
  This wrapper forwards manual metadata values into bin/call_watermark.py.

Arguments:
  INPUT_VIDEO   Existing local video file to watermark.
  OUTPUT_VIDEO  Final watermarked output path.
  uploader      Uploader/source name used in the watermark label.
  upload-date   Upload date string shown in watermark label.
  title         Video title shown in watermark label.

Examples:
  bin/watermark_manual.sh \
    "clips/input clip.mp4" \
    "clips/input clip_wm.mp4" \
    "@some_uploader" \
    "2026-04-26" \
    "This is the video title"
HELP
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

if [[ "$#" -ne 5 ]]; then
  echo "ERROR: Expected exactly 5 arguments." >&2
  show_help >&2
  exit 1
fi

INPUT_VIDEO="$1"
OUTPUT_VIDEO="$2"
UPLOADER="$3"
UPLOAD_DATE="$4"
TITLE="$5"

if [[ ! -f "$INPUT_VIDEO" ]]; then
  echo "ERROR: Input video does not exist: $INPUT_VIDEO" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_VIDEO")"

python bin/call_watermark.py \
  --input "$INPUT_VIDEO" \
  --output "$OUTPUT_VIDEO" \
  --uploader "$UPLOADER" \
  --upload-date "$UPLOAD_DATE" \
  --title "$TITLE"

echo "Watermarked video written to: $OUTPUT_VIDEO"
