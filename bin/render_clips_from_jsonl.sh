#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bin/render_clips_from_jsonl.sh outputs/2026-03-03/input.mp4 clips_first10min.jsonl
#
# Optional env vars:
#   OUTDIR=outputs/2026-03-03/clips
#   MODE=accurate|fast   (default: accurate)
#   VCODEC=libx264       (accurate mode only)
#   ACODEC=aac          (accurate mode only)
#   PRESET=veryfast     (accurate mode only)
#   CRF=20              (accurate mode only)

VIDEO="${1:-}"
JSONL="${2:-}"

if [[ -z "${VIDEO}" || -z "${JSONL}" ]]; then
  echo "Usage: $0 <video.mp4> <clips.jsonl>"
  exit 1
fi

if [[ ! -f "${VIDEO}" ]]; then
  echo "ERROR: video not found: ${VIDEO}"
  exit 2
fi
if [[ ! -f "${JSONL}" ]]; then
  echo "ERROR: jsonl not found: ${JSONL}"
  exit 3
fi

MODE="${MODE:-accurate}"

# Default OUTDIR next to the video: outputs/DATE/clips
VIDDIR="$(cd "$(dirname "${VIDEO}")" && pwd)"
OUTDIR="${OUTDIR:-${VIDDIR}/clips}"
mkdir -p "${OUTDIR}"

# Parse jsonl without jq (python is already in your world)
python - <<'PY' "${VIDEO}" "${JSONL}" "${OUTDIR}" "${MODE}"
import json, os, re, sys, subprocess, shlex

video, jsonl, outdir, mode = sys.argv[1:5]
vcodec  = os.environ.get("VCODEC", "libx264")
acodec  = os.environ.get("ACODEC", "aac")
preset  = os.environ.get("PRESET", "veryfast")
crf     = os.environ.get("CRF", "20")

def safe_slug(s: str, n=64) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^A-Za-z0-9._ -]+", "", s)
    s = s.replace(" ", "_")
    return s[:n].rstrip("_")

def run(cmd):
    print(" ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)

with open(jsonl, "r", encoding="utf-8") as f:
    clips = [json.loads(line) for line in f if line.strip()]

for c in clips:
    cid = c["clip_id"]
    start = float(c["start"])
    end = float(c["end"])
    q = c.get("question_text","")
    slug = safe_slug(q)
    # filename carries id + times + a bit of question text
    outname = f"{cid}_{start:.3f}-{end:.3f}_{slug}.mp4"
    outpath = os.path.join(outdir, outname)

    if os.path.exists(outpath) and os.path.getsize(outpath) > 0:
        print(f"# exists, skipping: {outpath}")
        continue

    if mode == "fast":
        # Fast copy (may cut only on keyframes; good for quick iteration)
        cmd = ["ffmpeg", "-hide_banner", "-y", "-ss", str(start), "-to", str(end),
               "-i", video, "-c", "copy", outpath]
    else:
        # Accurate re-encode (reliable cuts)
        cmd = ["ffmpeg", "-hide_banner", "-y", "-ss", str(start), "-to", str(end),
               "-i", video,
               "-c:v", vcodec, "-preset", preset, "-crf", crf,
               "-c:a", acodec, "-movflags", "+faststart",
               outpath]

    run(cmd)

print(f"\nWrote clips to: {outdir}")
PY

