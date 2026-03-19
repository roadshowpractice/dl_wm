#!/usr/bin/env bash
set -euo pipefail

########################################
# CONFIG — EDIT THESE
########################################

BASE_DIR="${HOME}/Desktop/dl_wm"
WORK_DIR="${BASE_DIR}/outputs/2026-03-16"

VIDEO_BASENAME="youtube__9t4V6OfZO70_watermarked.mp4"
JSONL_BASENAME="clips2.jsonl"
FONT_PATH="${BASE_DIR}/fonts/Inter-Bold.otf"

RUN_NAME="redo_short2"

########################################
# STAGE TOGGLES — OVERRIDABLE VIA ENV
########################################

DO_EXTRACT="${DO_EXTRACT:-1}"
DO_SRT="${DO_SRT:-1}"
DO_BURN="${DO_BURN:-1}"
DO_INTRO="${DO_INTRO:-0}"
DO_RENDER="${DO_RENDER:-1}"

########################################
# DERIVED PATHS — DO NOT EDIT
########################################

VIDEO_PATH="${WORK_DIR}/${VIDEO_BASENAME}"
JSONL_PATH="${WORK_DIR}/${JSONL_BASENAME}"

RUN_DIR="${WORK_DIR}/${RUN_NAME}"
CLIPS_DIR="${RUN_DIR}/py_clips"
SUBTITLES_DIR="${RUN_DIR}/subtitles"
SUBBED_DIR="${RUN_DIR}/py_clips_subbed"
INTRO_DIR="${RUN_DIR}/intro"
MANIFEST_PATH="${RUN_DIR}/clips_manifest.json"
FINAL_VIDEO_PATH="${RUN_DIR}/final_video.mp4"

########################################
# HELPERS
########################################

die() {
  echo "❌ $*" >&2
  exit 1
}

log() {
  echo
  echo "== $* =="
}

need_file() {
  local path="$1"
  [[ -f "$path" ]] || die "Missing file: $path"
}

need_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || die "Missing command: $cmd"
}

########################################
# VALIDATION
########################################

need_cmd python
need_cmd ffmpeg

need_file "$VIDEO_PATH"
need_file "$JSONL_PATH"

mkdir -p "$RUN_DIR" "$CLIPS_DIR" "$SUBTITLES_DIR" "$SUBBED_DIR" "$INTRO_DIR"

echo "BASE_DIR:       $BASE_DIR"
echo "WORK_DIR:       $WORK_DIR"
echo "VIDEO_PATH:     $VIDEO_PATH"
echo "JSONL_PATH:     $JSONL_PATH"
echo "RUN_DIR:        $RUN_DIR"
echo "CLIPS_DIR:      $CLIPS_DIR"
echo "SUBTITLES_DIR:  $SUBTITLES_DIR"
echo "SUBBED_DIR:     $SUBBED_DIR"
echo "MANIFEST_PATH:  $MANIFEST_PATH"
echo "FINAL_VIDEO:    $FINAL_VIDEO_PATH"

########################################
# STAGE 1 — EXTRACT CLIPS
########################################

if [[ "$DO_EXTRACT" == "1" ]]; then
  log "STAGE 1 — EXTRACT"

  rm -rf "$CLIPS_DIR"
  mkdir -p "$CLIPS_DIR"

  python -m pipeline.extract \
    --source-video "$VIDEO_PATH" \
    --clips-jsonl "$JSONL_PATH" \
    --output-dir "$CLIPS_DIR" \
    --manifest-out "$MANIFEST_PATH"

  need_file "$MANIFEST_PATH"
fi

########################################
# STAGE 1.5 — GENERATE SRTS AND WRITE srt_path INTO MANIFEST
########################################

if [[ "$DO_SRT" == "1" ]]; then
  log "STAGE 1.5 — GENERATE SRTS"

  need_file "$MANIFEST_PATH"
  rm -rf "$SUBTITLES_DIR"
  mkdir -p "$SUBTITLES_DIR"

  python - <<'PY' "$MANIFEST_PATH" "$SUBTITLES_DIR"
import json
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
subtitles_dir = Path(sys.argv[2])

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips", [])
if not isinstance(clips, list):
    raise SystemExit("Manifest missing 'clips' list")

updated_clips = []

for clip in clips:
    clip_id = str(clip["clip_id"])
    clip_path = Path(str(clip["path"]))
    if not clip_path.exists():
        raise SystemExit(f"Clip missing for SRT generation: {clip_path}")

    out_srt = subtitles_dir / f"{clip_id}.srt"

    cmd = [
        sys.executable,
        "bin/generate_clip_srts.py",
        "--clip-path",
        str(clip_path),
        "--output",
        str(out_srt),
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)

    updated = dict(clip)
    updated["srt_path"] = str(out_srt)
    updated_clips.append(updated)

manifest["clips"] = updated_clips
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"Wrote updated manifest with srt_path: {manifest_path}")
PY

  need_file "$MANIFEST_PATH"
fi

########################################
# STAGE 1.6 — BURN SUBTITLES
# Uses clip["srt_path"] if present, falls back to subtitles/<clip_id>.srt
########################################

if [[ "$DO_BURN" == "1" ]]; then
  log "STAGE 1.6 — BURN SUBTITLES"

  need_file "$MANIFEST_PATH"
  rm -rf "$SUBBED_DIR"
  mkdir -p "$SUBBED_DIR"

  python - <<'PY' "$MANIFEST_PATH" "$SUBTITLES_DIR" "$SUBBED_DIR" "$FONT_PATH"
import json
import shlex
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
subtitles_dir = Path(sys.argv[2])
subbed_dir = Path(sys.argv[3])
font_path = Path(sys.argv[4])

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips", [])
if not isinstance(clips, list):
    raise SystemExit("Manifest missing 'clips' list")

updated_clips = []

for clip in clips:
    clip_id = str(clip["clip_id"])
    clip_path = Path(str(clip["path"]))
    if not clip_path.exists():
        raise SystemExit(f"Clip missing for burn stage: {clip_path}")

    raw_srt_path = clip.get("srt_path")
    if raw_srt_path:
        subtitle_path = Path(str(raw_srt_path))
    else:
        subtitle_path = subtitles_dir / f"{clip_id}.srt"

    if not subtitle_path.exists():
        print(f"WARNING: subtitle missing for {clip_id}, leaving path unchanged: {subtitle_path}")
        updated_clips.append(dict(clip))
        continue

    out_path = subbed_dir / f"{clip_id}.mp4"

    subtitle_filter = f"subtitles={shlex.quote(str(subtitle_path))}"
    if font_path.exists():
        # Keep this conservative; exact styling can be tuned later.
        subtitle_filter += f":force_style='FontName=Inter,FontSize=22'"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(clip_path),
        "-vf",
        subtitle_filter,
        "-c:a",
        "copy",
        str(out_path),
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)

    updated = dict(clip)
    updated["path"] = str(out_path)
    updated_clips.append(updated)

manifest["clips"] = updated_clips
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"Wrote updated manifest after burn stage: {manifest_path}")
PY

  need_file "$MANIFEST_PATH"
fi

########################################
# STAGE 2 — INTRO
########################################

if [[ "$DO_INTRO" == "1" ]]; then
  log "STAGE 2 — INTRO"
  echo "⚠️ Intro stage not implemented yet."
fi

########################################
# STAGE 3 — RENDER FINAL
########################################

if [[ "$DO_RENDER" == "1" ]]; then
  log "STAGE 3 — RENDER FINAL"

  need_file "$MANIFEST_PATH"

  python - <<'PY' "$MANIFEST_PATH" "$RUN_DIR" "$FINAL_VIDEO_PATH"
import json
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
run_dir = Path(sys.argv[2])
final_video_path = Path(sys.argv[3])

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips", [])
if not isinstance(clips, list) or not clips:
    raise SystemExit("Manifest has no clips to render")

concat_list_path = run_dir / "concat_list.txt"
lines = []
for clip in clips:
    clip_path = Path(str(clip["path"]))
    if not clip_path.exists():
        raise SystemExit(f"Clip missing for final render: {clip_path}")
    lines.append(f"file '{clip_path}'")

concat_list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

cmd = [
    "ffmpeg",
    "-y",
    "-f",
    "concat",
    "-safe",
    "0",
    "-i",
    str(concat_list_path),
    "-c",
    "copy",
    str(final_video_path),
]
print(" ".join(cmd))
subprocess.run(cmd, check=True)
print(f"Final video written: {final_video_path}")
PY

  need_file "$FINAL_VIDEO_PATH"
fi

log "DONE"
