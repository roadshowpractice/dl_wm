#!/usr/bin/env bash
set -euo pipefail

########################################
# CONFIG (edit these only)
########################################
BASE_DIR="$HOME/Desktop/dl_wm"
WORK_DIR="$BASE_DIR/outputs/2026-03-16"

VIDEO="youtube__9t4V6OfZO70_watermarked.mp4"
JSONL="clips2.jsonl"
FONT="./fonts/Inter-Bold.otf"

RUN_NAME="redo_short2"

FPS=30
CRF=18
INTRO_SECONDS=2
BLACK_SECONDS=0.5

########################################
# DERIVED PATHS (do not edit)
########################################
RUN_DIR="$WORK_DIR/$RUN_NAME"

VIDEO_PATH="$WORK_DIR/$VIDEO"
JSONL_PATH="$WORK_DIR/$JSONL"

CLIPS_DIR="$RUN_DIR/py_clips"
INTRO_DIR="$RUN_DIR/clips_intro"

MANIFEST_STAGE1="$RUN_DIR/clips_manifest.json"
MANIFEST_STAGE2="$RUN_DIR/clips_intro_manifest.json"

FINAL_OUTPUT="$RUN_DIR/final_video.mp4"

########################################
# VALIDATION
########################################
echo "== Validating inputs =="

[[ -d "$BASE_DIR/pipeline" ]] || { echo "❌ Missing pipeline dir: $BASE_DIR/pipeline"; exit 1; }
[[ -d "$WORK_DIR" ]] || { echo "❌ Missing work dir: $WORK_DIR"; exit 1; }

[[ -f "$VIDEO_PATH" ]] || { echo "❌ Missing video: $VIDEO_PATH"; exit 1; }
[[ -f "$JSONL_PATH" ]] || { echo "❌ Missing JSONL: $JSONL_PATH"; exit 1; }
[[ -f "$FONT" ]] || { echo "❌ Missing font: $FONT"; exit 1; }

echo "== Inputs OK =="

########################################
# EXECUTION
########################################
cd "$WORK_DIR" || exit 1
export PYTHONPATH="$BASE_DIR"

echo "== Cleaning previous run =="
rm -rf "$RUN_DIR"
mkdir -p "$RUN_DIR"

echo "== Stage 1: Extract =="
python -m pipeline.extract \
  --source-video "$VIDEO_PATH" \
  --clips-jsonl "$JSONL_PATH" \
  --output-dir "$CLIPS_DIR" \
  --manifest-out "$MANIFEST_STAGE1" \
  --fps "$FPS" \
  --crf "$CRF"

echo "== Stage 2: Intro =="
python -m pipeline.intro \
  --manifest "$MANIFEST_STAGE1" \
  --output-dir "$INTRO_DIR" \
  --manifest-out "$MANIFEST_STAGE2" \
  --font "$FONT" \
  --intro-seconds "$INTRO_SECONDS" \
  --black-seconds "$BLACK_SECONDS"

echo "== Stage 3: Render =="
python -m pipeline.render \
  --manifest "$MANIFEST_STAGE2" \
  --output "$FINAL_OUTPUT"

########################################
# FINAL CHECK
########################################
echo "== DONE =="
[[ -f "$FINAL_OUTPUT" ]] && ls -lh "$FINAL_OUTPUT" || { echo "❌ Final video missing"; exit 1; }
