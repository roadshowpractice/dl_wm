#!/usr/bin/env bash
set -euo pipefail

# Wrapper around bin/render_clips.py
#
# Usage:
#   bin/render_clips_from_jsonl.sh [clips.jsonl] [--video <video.mp4>] [--outdir <dir>] [--mode accurate|fast]
#
# Environment "envelope" defaults (all optional):
#   MODE=accurate
#   VCODEC=libx264
#   ACODEC=aac
#   PRESET=veryfast
#   CRF=20
#   FFMPEG_BIN=ffmpeg
#
# Examples:
#   MODE=fast bin/render_clips_from_jsonl.sh outputs/2026-03-04/clips/clips.jsonl
#   bin/render_clips_from_jsonl.sh outputs/2026-03-04/clips/clips.jsonl --video outputs/2026-03-04/input.mp4

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<EOF
Usage: $0 [clips.jsonl] [--video <video.mp4>] [--outdir <dir>] [--mode accurate|fast]

Envelope values (env defaults):
  MODE=${MODE:-accurate}
  VCODEC=${VCODEC:-libx264}
  ACODEC=${ACODEC:-aac}
  PRESET=${PRESET:-veryfast}
  CRF=${CRF:-20}
  FFMPEG_BIN=${FFMPEG_BIN:-ffmpeg}
EOF
  exit 0
fi

python bin/render_clips.py "$@"
