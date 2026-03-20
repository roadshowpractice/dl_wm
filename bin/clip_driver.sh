#!/usr/bin/env bash
set -euo pipefail

########################################
# CONFIG — EDIT THESE
########################################

BASE_DIR="${HOME}/Desktop/dl_wm"
WORK_DIR="${BASE_DIR}/outputs/2026-03-19"

VIDEO_BASENAME="youtube__sIhu0UO99wQ_watermarked.mp4"
JSONL_BASENAME="absurd.jsonl"
FONT_PATH="${BASE_DIR}/fonts/Inter-Bold.otf"
TITLE_IMAGE_PATH="${TITLE_IMAGE_PATH:-${WORK_DIR}/child.png}"

RUN_NAME="redo_short7"

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

  python - <<'PY' "$MANIFEST_PATH" "$SUBTITLES_DIR" "$DO_SHORT_SRT" "$JSONL_PATH" "$RUN_DIR" "$CLIPS_DIR"
import json
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
subtitles_dir = Path(sys.argv[2])
do_short_srt = sys.argv[3] == "1"
clips_jsonl = Path(sys.argv[4])
run_dir = Path(sys.argv[5])
clips_dir = Path(sys.argv[6])

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips", [])
if not isinstance(clips, list):
    raise SystemExit("Manifest missing 'clips' list")

updated_clips = []

transcript_json_path = None
if clips_jsonl.exists():
    transcript_candidates = []
    with clips_jsonl.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            candidate = row.get("source_whisper_json")
            if isinstance(candidate, str) and candidate.strip():
                transcript_candidates.append(candidate.strip())
    unique_candidates = sorted(set(transcript_candidates))
    if len(unique_candidates) == 1:
        candidate_path = Path(unique_candidates[0]).expanduser()
        if not candidate_path.is_absolute():
            candidate_path = Path.cwd() / candidate_path
        if candidate_path.exists():
            transcript_json_path = candidate_path.resolve()
            cmd = [
                sys.executable,
                "bin/generate_clip_srts.py",
                "--clips-jsonl",
                str(clips_jsonl),
                "--transcript-json",
                str(transcript_json_path),
                "--output-dir",
                str(run_dir),
            ]
            print(" ".join(cmd))
            subprocess.run(cmd, check=True)
            print(f"Subtitle generation source: transcript_json={transcript_json_path}")
        else:
            print(f"WARNING: source_whisper_json not found, falling back to per-clip transcription: {candidate_path}")
    elif len(unique_candidates) > 1:
        print("WARNING: multiple source_whisper_json values detected; falling back to per-clip transcription.")

if do_short_srt:
    print("WARNING: DO_SHORT_SRT=1 ignored because equal-time SRT slicing was removed to preserve true timing.")

for clip in clips:
    clip_id = str(clip["clip_id"])
    clip_path = Path(str(clip["path"]))
    if not clip_path.exists():
        raise SystemExit(f"Clip missing for SRT generation: {clip_path}")

    out_srt = subtitles_dir / f"{clip_id}.srt"

    if transcript_json_path is None:
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
        print(f"Subtitle generation source for {clip_id}: fresh_clip_transcription")
    elif not out_srt.exists():
        raise SystemExit(f"Expected batch-generated subtitle missing for {clip_id}: {out_srt}")

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

  python - <<'PY' "$MANIFEST_PATH" "$SUBTITLES_DIR" "$SUBBED_DIR" "$FONT_PATH" "$CLIPS_DIR"
import json
import shlex
import subprocess
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
subtitles_dir = Path(sys.argv[2])
subbed_dir = Path(sys.argv[3])
font_path = Path(sys.argv[4])
clips_dir = Path(sys.argv[5])

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
clips = manifest.get("clips", [])
if not isinstance(clips, list):
    raise SystemExit("Manifest missing 'clips' list")

updated_clips = []

for clip in clips:
    clip_id = str(clip["clip_id"])
    canonical_clip_path = clips_dir / f"{clip_id}.mp4"
    clip_path = canonical_clip_path if canonical_clip_path.exists() else Path(str(clip["path"]))
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

  python -m pipeline.intro \
    --manifest "$MANIFEST_PATH" \
    --output-dir "$INTRO_DIR" \
    --manifest-out "$MANIFEST_PATH" \
    --font "$FONT_PATH" \
    --intro-seconds 2.0

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
import sys
from pathlib import Path

from pipeline.render import prepare_make_final_film_inputs

prepare_make_final_film_inputs(
    Path(sys.argv[1]),
    Path(sys.argv[2]),
    Path(sys.argv[3]),
)
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
