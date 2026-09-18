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


def raw_segments_from_scores(scores: list[tuple[float, float]], duration: float, threshold: float) -> list[tuple[float, float]]:
    cuts = [t for t, s in scores if s > threshold]
    bounds = [0.0] + cuts + [duration]
    return list(zip(bounds[:-1], bounds[1:]))


def merge_flicker_runs(
    segments: list[tuple[float, float]], flicker_threshold: float
) -> list[tuple[float, float, list[int]]]:
    """Collapse runs of consecutive short segments (e.g. a title card whose
    text fades in over several rapid sub-cuts, each scoring above the diff
    threshold on its own) into one segment per run.

    A segment only joins the current run if it AND its immediate predecessor
    are both shorter than flicker_threshold - so an isolated short segment
    sandwiched between two long ones (a brief but real cutaway: a screenshot
    insert, a quick B-roll photo) has no short neighbor on at least one side
    and is left standing on its own, not merged away. This is what a single
    "merge anything closer than min_gap to the last kept boundary" rule
    (the previous approach) got wrong - it could absorb a real 1-4s cutaway
    into a neighboring talking-head segment with no way to tell afterward
    that it had ever been its own scene.

    Returns (start, end, raw_indices) per merged group - raw_indices lets
    the caller still take one screenshot per ORIGINAL raw segment even
    inside a merged group, so nothing that was its own segment pre-merge
    ever loses its own screenshot.
    """
    groups: list[list[int]] = [[0]]
    for i in range(1, len(segments)):
        prev_dur = segments[i - 1][1] - segments[i - 1][0]
        this_dur = segments[i][1] - segments[i][0]
        if prev_dur < flicker_threshold and this_dur < flicker_threshold:
            groups[-1].append(i)
        else:
            groups.append([i])
    return [(segments[g[0]][0], segments[g[-1]][1], g) for g in groups]


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


def format_timestamp(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:05.2f}"


def sub_label(i: int) -> str:
    """0 -> '', 1 -> 'a', 2 -> 'b', ... for naming raw sub-segments within a merged clip."""
    return "" if i == 0 else chr(ord("a") + i - 1)


def write_gallery(
    screenshots_dir: Path,
    title: str,
    raw_segments: list[tuple[float, float]],
    groups: list[tuple[float, float, list[int]]],
) -> Path:
    group_html = []
    for gi, (gs, ge, raw_indices) in enumerate(groups, start=1):
        clip_id = f"clip_{gi:02d}"
        flicker_note = f" &mdash; {len(raw_indices)} sub-frames (merged, likely one animated card)" if len(raw_indices) > 1 else ""
        cells = []
        for k, ri in enumerate(raw_indices):
            rs, re_ = raw_segments[ri]
            fname = f"{clip_id}{sub_label(k)}.jpg"
            f = screenshots_dir / fname
            cells.append(
                f'<div class="cell"><img src="file://{f}" loading="lazy">'
                f'<div class="cap">{fname} &mdash; {format_timestamp(rs)}-{format_timestamp(re_)}</div></div>'
            )
        group_html.append(
            f'<div class="group"><h4>{clip_id} &mdash; {format_timestamp(gs)}-{format_timestamp(ge)}{flicker_note}</h4>'
            f'<div class="grid">{"".join(cells)}</div></div>'
        )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title>
<style>
body{{background:#111;color:#eee;font-family:sans-serif;margin:0;padding:12px}}
.group{{margin-bottom:18px;border-top:1px solid #333;padding-top:8px}}
.group h4{{margin:0 0 6px 0;font-size:14px;color:#9cf}}
.grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}}
.cell img{{width:100%;display:block;border:1px solid #333}}
.cap{{font-size:12px;text-align:center;padding:2px}}
</style></head><body>
<h3>{title} &mdash; {len(groups)} scene(s), {len(raw_segments)} raw sub-frame(s)</h3>
{"".join(group_html)}
</body></html>"""
    out = screenshots_dir / "gallery.html"
    out.write_text(html)
    return out


@dataclass
class SceneSplitResult:
    groups: list[tuple[float, float, list[int]]]
    raw_segments: list[tuple[float, float]]
    clips_dir: Path
    screenshots_dir: Path
    gallery: Path


def run(video: Path, out_dir: Path, fps: float, threshold: float, flicker_threshold: float) -> SceneSplitResult:
    duration = ffprobe_duration(video)
    frames_dir = out_dir / "_diff_frames"
    frames = extract_sample_frames(video, frames_dir, fps)
    scores = frame_diff_scores(frames, fps)
    raw_segments = raw_segments_from_scores(scores, duration, threshold)
    groups = merge_flicker_runs(raw_segments, flicker_threshold)

    clips_dir = out_dir / "clips"
    screenshots_dir = out_dir / "screenshots"
    clips_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    for gi, (gs, ge, raw_indices) in enumerate(groups, start=1):
        clip_id = f"clip_{gi:02d}"
        extract_segment(video, gs, ge, clips_dir / f"{clip_id}.mp4")
        # One screenshot per RAW sub-segment, not per merged group - a real
        # cutaway that got merged into a flicker run (see merge_flicker_runs)
        # still gets its own screenshot instead of being hidden behind the
        # group's single midpoint frame.
        for k, ri in enumerate(raw_indices):
            rs, re_ = raw_segments[ri]
            mid = (rs + re_) / 2
            extract_screenshot(video, mid, screenshots_dir / f"{clip_id}{sub_label(k)}.jpg")

    gallery = write_gallery(screenshots_dir, video.name, raw_segments, groups)

    segments_json = out_dir / "segments.json"
    segments_json.write_text(json.dumps(
        [
            {
                "clip_id": f"clip_{gi:02d}",
                "start": gs,
                "end": ge,
                "raw": [
                    {"screenshot": f"clip_{gi:02d}{sub_label(k)}.jpg", "start": raw_segments[ri][0], "end": raw_segments[ri][1]}
                    for k, ri in enumerate(raw_indices)
                ],
            }
            for gi, (gs, ge, raw_indices) in enumerate(groups, start=1)
        ],
        indent=2,
    ))

    # frames_dir is scratch, not a deliverable - clean it up
    for f in frames_dir.glob("*"):
        f.unlink()
    frames_dir.rmdir()

    return SceneSplitResult(groups, raw_segments, clips_dir, screenshots_dir, gallery)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", help="Video path (abs or repo-root-relative)")
    parser.add_argument("--out-dir", default=None, help="Output dir (default: <video_dir>/scene_clips)")
    parser.add_argument("--fps", type=float, default=5.0, help="Sampling rate for diffing (default: 5)")
    parser.add_argument("--threshold", type=float, default=50.0, help="Mean-abs-diff cut threshold on a 0-255 scale, 64x64 grayscale (default: 50)")
    parser.add_argument(
        "--flicker-threshold", type=float, default=2.0,
        help="Segments shorter than this many seconds only merge with an equally-short neighbor "
             "(collapses a title card's multi-cut fade-in animation into one clip) - an isolated "
             "short segment between two longer ones (a real brief cutaway) is left standing on its "
             "own and still gets its own screenshot either way (default: 2.0)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = detect_repo_root()
    video = resolve_input_path(args.video, repo_root)
    if not video.exists():
        print(f"Video not found: {video}", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else video.parent / "scene_clips"

    result = run(video, out_dir, args.fps, args.threshold, args.flicker_threshold)
    print(f"scenes: {len(result.groups)} (from {len(result.raw_segments)} raw sub-frames)")
    print(f"clips: {result.clips_dir}")
    print(f"screenshots: {result.screenshots_dir}")
    print(f"gallery: {result.gallery}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
