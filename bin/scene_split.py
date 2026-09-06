#!/usr/bin/env python3
"""Split a video into scenes by pixel-difference, not ffmpeg's select='scene' filter.

Authored by John (hogan) with Claude Sonnet 5 riding shotgun, 2026-09-05.

ffmpeg's own select=gt(scene\\,X) comparison proved unreliable on some
Instagram-sourced files (silently returns zero matches on files whose video
stream came through as ffmpeg's `wrapped_avframe` pseudo-codec, and was
non-deterministic even after re-encoding to a clean h264 stream - two
separate runs of the identical command gave different frame counts). This
tool instead samples frames at a fixed rate and diffs them directly in
Python (downscaled grayscale, mean absolute difference), which is fully
inspectable and has been stable across repeated runs.

How the diff score works: each sampled frame is shrunk to 64x64 grayscale,
which is really just a vector of 4,096 numbers (one brightness value per
pixel). Subtracting two frames gives a 4,096-dimensional difference vector.
The diff score is the mean of the absolute values of that vector's
entries - a normalized L1 (taxicab/Manhattan) distance between the two
frames, as opposed to the more familiar L2/Euclidean distance (sqrt of
summed squares). Dividing by the pixel count keeps the score comparable
regardless of the resize dimensions chosen. Measured on real footage: an
actual scene cut scores ~60-83, ordinary within-scene motion scores ~20-30
(median ~28.6) - the default --threshold of 50 sits in that gap.

Usage:
    python3 bin/scene_split.py outputs/<run>/<file>.mp4
    python3 bin/scene_split.py outputs/<run>/<file>.mp4 --threshold 50 --fps 5
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


def detect_repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(proc.stdout.strip()).resolve()


def resolve_input_path(raw: str, repo_root: Path) -> Path:
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def ffprobe_duration(video: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(proc.stdout.strip())


def extract_sample_frames(video: Path, frames_dir: Path, fps: float) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vf", f"fps={fps}", "-q:v", "4",
         str(frames_dir / "f_%05d.jpg"), "-loglevel", "error"],
        check=True,
    )
    return sorted(frames_dir.glob("f_*.jpg"))


def frame_diff_scores(frames: list[Path], fps: float) -> list[tuple[float, float]]:
    """Return (timestamp, diff_score) for each frame after the first."""
    scores = []
    prev = None
    for i, f in enumerate(frames):
        im = np.asarray(Image.open(f).convert("L").resize((64, 64)), dtype=np.float32)
        if prev is not None:
            scores.append((i / fps, float(np.mean(np.abs(im - prev)))))
        prev = im
    return scores


def find_cut_bounds(scores: list[tuple[float, float]], duration: float, threshold: float, min_gap: float) -> list[float]:
    cuts = [t for t, s in scores if s > threshold]
    bounds = [0.0] + cuts + [duration]
    merged = [bounds[0]]
    for b in bounds[1:]:
        if b - merged[-1] >= min_gap:
            merged.append(b)
        else:
            merged[-1] = b
    return merged


def extract_segment(video: Path, start: float, end: float, out_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", str(video),
         "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
         "-avoid_negative_ts", "make_zero", str(out_path), "-loglevel", "error"],
        check=True,
    )


def extract_screenshot(video: Path, timestamp: float, out_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(timestamp), "-i", str(video), "-frames:v", "1",
         "-q:v", "2", str(out_path), "-loglevel", "error"],
        check=True,
    )


def write_gallery(screenshots_dir: Path, title: str) -> Path:
    files = sorted(screenshots_dir.glob("clip_*.jpg"))
    cells = "".join(
        f'<div class="cell"><img src="file://{f}" loading="lazy"><div class="cap">{f.name}</div></div>'
        for f in files
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title>
<style>
body{{background:#111;color:#eee;font-family:sans-serif;margin:0;padding:12px}}
.grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}}
.cell img{{width:100%;display:block;border:1px solid #333}}
.cap{{font-size:12px;text-align:center;padding:2px}}
</style></head><body>
<h3>{title} &mdash; {len(files)} scene(s)</h3>
<div class="grid">{cells}</div>
</body></html>"""
    out = screenshots_dir / "gallery.html"
    out.write_text(html)
    return out


@dataclass
class SceneSplitResult:
    segments: list[tuple[float, float]]
    clips_dir: Path
    screenshots_dir: Path
    gallery: Path


def run(video: Path, out_dir: Path, fps: float, threshold: float, min_gap: float) -> SceneSplitResult:
    duration = ffprobe_duration(video)
    frames_dir = out_dir / "_diff_frames"
    frames = extract_sample_frames(video, frames_dir, fps)
    scores = frame_diff_scores(frames, fps)
    bounds = find_cut_bounds(scores, duration, threshold, min_gap)

    clips_dir = out_dir / "clips"
    screenshots_dir = out_dir / "screenshots"
    clips_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    segments = list(zip(bounds[:-1], bounds[1:]))
    for i, (s, e) in enumerate(segments, start=1):
        idx = f"{i:02d}"
        mid = (s + e) / 2
        extract_segment(video, s, e, clips_dir / f"clip_{idx}.mp4")
        extract_screenshot(video, mid, screenshots_dir / f"clip_{idx}.jpg")

    gallery = write_gallery(screenshots_dir, video.name)

    segments_json = out_dir / "segments.json"
    segments_json.write_text(json.dumps(
        [{"clip_id": f"clip_{i:02d}", "start": s, "end": e} for i, (s, e) in enumerate(segments, start=1)],
        indent=2,
    ))

    # frames_dir is scratch, not a deliverable - clean it up
    for f in frames_dir.glob("*"):
        f.unlink()
    frames_dir.rmdir()

    return SceneSplitResult(segments, clips_dir, screenshots_dir, gallery)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="Video path (abs or repo-root-relative)")
    parser.add_argument("--out-dir", default=None, help="Output dir (default: <video_dir>/scene_clips)")
    parser.add_argument("--fps", type=float, default=5.0, help="Sampling rate for diffing (default: 5)")
    parser.add_argument("--threshold", type=float, default=50.0, help="Mean-abs-diff cut threshold on a 0-255 scale, 64x64 grayscale (default: 50)")
    parser.add_argument("--min-gap", type=float, default=1.0, help="Merge cuts closer than this many seconds (default: 1.0)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = detect_repo_root()
    video = resolve_input_path(args.video, repo_root)
    if not video.exists():
        print(f"Video not found: {video}", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else video.parent / "scene_clips"

    result = run(video, out_dir, args.fps, args.threshold, args.min_gap)
    print(f"segments: {len(result.segments)}")
    print(f"clips: {result.clips_dir}")
    print(f"screenshots: {result.screenshots_dir}")
    print(f"gallery: {result.gallery}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
