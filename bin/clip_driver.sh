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
TITLE_IMAGE_PATH="${TITLE_IMAGE_PATH:-${WORK_DIR}/monarch.png}"

RUN_NAME="redo_short3"

########################################
# STAGE TOGGLES — OVERRIDABLE VIA ENV
########################################

DO_EXTRACT="${DO_EXTRACT:-1}"
DO_SRT="${DO_SRT:-1}"
DO_SHORT_SRT="${DO_SHORT_SRT:-0}"
DO_BURN="${DO_BURN:-1}"
DO_INTRO="${DO_INTRO:-1}"
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

need_dir() {
  local path="$1"
  [[ -d "$path" ]] || die "Missing directory: $path"
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
echo "TITLE_IMAGE:    $TITLE_IMAGE_PATH"
echo "RUN_DIR:        $RUN_DIR"
echo "CLIPS_DIR:      $CLIPS_DIR"
echo "SUBTITLES_DIR:  $SUBTITLES_DIR"
echo "SUBBED_DIR:     $SUBBED_DIR"
echo "INTRO_DIR:      $INTRO_DIR"
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

  python - <<'PY' "$MANIFEST_PATH" "$SUBTITLES_DIR" "$DO_SHORT_SRT"
import json
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
subtitles_dir = Path(sys.argv[2])
do_short_srt = sys.argv[3] == "1"

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

    if do_short_srt:
        tmp_srt = subtitles_dir / f"{clip_id}.short.srt"
        short_cmd = [
            sys.executable,
            "bin/short_srt.py",
            str(out_srt),
            str(tmp_srt),
        ]
        print(" ".join(short_cmd))
        subprocess.run(short_cmd, check=True)
        tmp_srt.replace(out_srt)

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
        subtitle_filter += ":force_style='FontName=Inter,FontSize=22'"

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
# Build per-clip break cards using each clip's "comment",
# prepend the card to the current clip, and advance path.
########################################

if [[ "$DO_INTRO" == "1" ]]; then
  log "STAGE 2 — INTRO"

  need_file "$MANIFEST_PATH"
  rm -rf "$INTRO_DIR"
  mkdir -p "$INTRO_DIR"

  python - <<'PY' "$MANIFEST_PATH" "$INTRO_DIR" "$FONT_PATH"
import json
import subprocess
import sys
import tempfile
from pathlib import Path

manifest_path = Path(sys.argv[1])
intro_dir = Path(sys.argv[2])
font_path = Path(sys.argv[3])

WIDTH = 1920
HEIGHT = 1080
FPS = 30
CARD_SECONDS = 2

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips", [])
if not isinstance(clips, list):
    raise SystemExit("Manifest missing 'clips' list")

updated_clips = []

def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", r"\'")
            .replace("%", r"\%")
            .replace(",", r"\,")
            .replace("[", r"\[")
            .replace("]", r"\]")
    )

for clip in clips:
    clip_id = str(clip["clip_id"])
    clip_path = Path(str(clip["path"]))
    if not clip_path.exists():
        raise SystemExit(f"Clip missing for intro stage: {clip_path}")

    comment = str(clip.get("comment", "")).strip()
    if not comment:
        comment = clip_id

    comment_escaped = escape_drawtext(comment)

    card_mp4 = intro_dir / f"{clip_id}.card.mp4"
    out_path = intro_dir / f"{clip_id}.mp4"

    vf = (
        f"color=c=white:s={WIDTH}x{HEIGHT}:r={FPS},"
        f"drawtext="
        f"fontfile='{font_path}':"
        f"text='{comment_escaped}':"
        f"fontcolor=black:"
        f"fontsize=54:"
        f"line_spacing=12:"
        f"box=0:"
        f"x=(w-text_w)/2:"
        f"y=(h-text_h)/2,"
        f"format=yuv420p"
    )

    cmd_card = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", vf,
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(CARD_SECONDS),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(card_mp4),
    ]
    print(" ".join(cmd_card))
    subprocess.run(cmd_card, check=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        concat_list = Path(tmpdir) / "concat.txt"
        concat_list.write_text(
            f"file '{card_mp4.resolve()}'\n"
            f"file '{clip_path.resolve()}'\n",
            encoding="utf-8",
        )

        cmd_concat = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path),
        ]
        print(" ".join(cmd_concat))
        subprocess.run(cmd_concat, check=True)

    updated = dict(clip)
    updated["path"] = str(out_path)
    updated_clips.append(updated)

manifest["clips"] = updated_clips
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"Wrote updated manifest after intro stage: {manifest_path}")
PY

  need_file "$MANIFEST_PATH"
fi

########################################
# STAGE 3 — RENDER FINAL
# Keep monarch.png front intro, then render current manifest paths
########################################

if [[ "$DO_RENDER" == "1" ]]; then
  log "STAGE 3 — RENDER FINAL"

  need_file "$MANIFEST_PATH"
  need_file "$TITLE_IMAGE_PATH"
  need_cmd jq
  need_cmd readlink

  CLIPS_JSONL_FOR_FILM="${RUN_DIR}/clips_for_film.jsonl"
  FILM_CLIP_DIR="${RUN_DIR}/film_clips"

  rm -rf "$FILM_CLIP_DIR"
  mkdir -p "$FILM_CLIP_DIR"

  python - <<'PY' "$MANIFEST_PATH" "$CLIPS_JSONL_FOR_FILM" "$FILM_CLIP_DIR"
import json
import os
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
jsonl_path = Path(sys.argv[2])
film_clip_dir = Path(sys.argv[3])

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips", [])
if not isinstance(clips, list) or not clips:
    raise SystemExit("Manifest has no clips to render")

jsonl_lines = []

for clip in clips:
    clip_id = clip.get("clip_id")
    clip_path = clip.get("path")
    if not clip_id:
        raise SystemExit(f"Clip missing clip_id: {clip}")
    if not clip_path:
        raise SystemExit(f"Clip missing path: {clip}")

    src = Path(str(clip_path))
    if not src.exists():
        raise SystemExit(f"Clip path missing for final render: {src}")

    dst = film_clip_dir / f"{clip_id}.mp4"
    if dst.exists() or dst.is_symlink():
        dst.unlink()

    os.symlink(src.resolve(), dst)
    jsonl_lines.append(json.dumps({"clip_id": clip_id}, ensure_ascii=False))

jsonl_path.write_text("\n".join(jsonl_lines) + "\n", encoding="utf-8")
print(f"Wrote film JSONL: {jsonl_path}")
print(f"Prepared film clip dir: {film_clip_dir}")
PY

  need_file "$CLIPS_JSONL_FOR_FILM"
  need_dir "$FILM_CLIP_DIR"

  bash bin/make_final_film.sh \
    "$CLIPS_JSONL_FOR_FILM" \
    "$FILM_CLIP_DIR" \
    "$FINAL_VIDEO_PATH" \
    "$TITLE_IMAGE_PATH"

  need_file "$FINAL_VIDEO_PATH"
fi

log "DONE"
