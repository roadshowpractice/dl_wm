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
SUBTITLE_STYLE="Alignment=2,FontSize=20,MarginV=32,Outline=2,Shadow=1"

########################################
# DERIVED PATHS (do not edit)
########################################
RUN_DIR="$WORK_DIR/$RUN_NAME"

VIDEO_PATH="$WORK_DIR/$VIDEO"
JSONL_PATH="$WORK_DIR/$JSONL"

CLIPS_DIR="$RUN_DIR/py_clips"
SUBTITLES_DIR="$RUN_DIR/subtitles"
SUBBED_DIR="$RUN_DIR/py_clips_subbed"
INTRO_DIR="$RUN_DIR/clips_intro"

MANIFEST_STAGE1="$RUN_DIR/clips_manifest.json"
MANIFEST_STAGE1_SUBBED="$RUN_DIR/clips_subbed_manifest.json"
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

command -v ffmpeg >/dev/null 2>&1 || { echo "❌ ffmpeg not found on PATH"; exit 1; }

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

echo "== Stage 1.5: Transcribe each clip to its own SRT =="
mkdir -p "$SUBTITLES_DIR"
python - "$MANIFEST_STAGE1" "$SUBTITLES_DIR" "$BASE_DIR" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
subtitles_dir = Path(sys.argv[2])
repo_root = Path(sys.argv[3]).resolve()

sys.path.insert(0, str(repo_root / "lib"))

from transcription_caller import run_transcription  # noqa: E402

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips")
if not isinstance(clips, list):
    raise SystemExit("Manifest clips list is missing or invalid")

subtitles_dir.mkdir(parents=True, exist_ok=True)
for clip in clips:
    clip_id = str(clip["clip_id"])
    input_path = Path(str(clip["path"]))
    if not input_path.is_file():
        raise SystemExit(f"Missing extracted clip: {input_path}")

    output_path = subtitles_dir / f"{clip_id}.srt"
    print(f"$ transcribe {input_path} -> {output_path}")
    if not run_transcription(str(input_path), str(output_path), "srt"):
        raise SystemExit(f"Failed to generate subtitles for clip {clip_id}: {input_path}")
PY

echo "== Stage 1.6: Burn subtitles onto extracted clips =="
mkdir -p "$SUBBED_DIR"
python - "$MANIFEST_STAGE1" "$SUBTITLES_DIR" "$SUBBED_DIR" "$MANIFEST_STAGE1_SUBBED" "$SUBTITLE_STYLE" "$CRF" <<'PY'
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
subtitles_dir = Path(sys.argv[2])
out_dir = Path(sys.argv[3])
out_manifest_path = Path(sys.argv[4])
subtitle_style = sys.argv[5]
crf = sys.argv[6]

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips")
if not isinstance(clips, list):
    raise SystemExit("Manifest clips list is missing or invalid")

out_dir.mkdir(parents=True, exist_ok=True)
updated_clips = []

for clip in clips:
    clip_id = str(clip["clip_id"])
    input_path = Path(str(clip["path"]))
    if not input_path.is_file():
        raise SystemExit(f"Missing extracted clip: {input_path}")

    subtitle_path = subtitles_dir / f"{clip_id}.srt"
    if not subtitle_path.is_file():
        raise SystemExit(f"Missing subtitle for clip {clip_id}: {subtitle_path}")

    output_path = out_dir / input_path.name
    escaped_subtitle_path = str(subtitle_path.resolve()).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")
    vf = f"subtitles='{escaped_subtitle_path}':force_style='{subtitle_style}'"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)

    updated = dict(clip)
    updated["path"] = str(output_path)
    updated_clips.append(updated)

manifest["clips"] = updated_clips
out_manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

echo "== Stage 2: Intro =="
python -m pipeline.intro \
  --manifest "$MANIFEST_STAGE1_SUBBED" \
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
