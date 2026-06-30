#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from dl_wm.teton_utils import load_config, resolve_repo_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render screenshots from a screenshots.jsonl using ffmpeg.")
    p.add_argument("screenshots_jsonl", help="Path to screenshots.jsonl")
    p.add_argument("video", help="Path to source video")
    p.add_argument("--outdir", default=None, help="Base output directory for screenshots (default: <run-dir>/screenshots/)")
    p.add_argument("--ffmpeg-bin", default=os.environ.get("FFMPEG_BIN", "ffmpeg"))
    return p.parse_args(argv)



def frame_timestamps(start: float, end: float, granularity: float) -> list[float]:
    times = []
    ts = start
    while ts <= end + 1e-9:
        times.append(ts)
        ts += granularity
    return times


def frame_filename(clip_id: str, ts: float) -> str:
    ts_ms = int(round(ts * 1000))
    return f"{clip_id}_{ts_ms:09d}.png"


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    platform_config = load_config()
    output_dir = Path(resolve_repo_path(platform_config.get("output_dir", "./outputs/")))

    jsonl_path = Path(resolve_repo_path(args.screenshots_jsonl))
    if not jsonl_path.exists():
        raise FileNotFoundError(f"screenshots jsonl not found: {jsonl_path}")

    video = Path(resolve_repo_path(args.video))
    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")

    raw_lines = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    lines = [re.sub(r'(?<![0-9])\.(\d)', r'0.\1', ln) for ln in raw_lines]
    entries: list[dict[str, Any]] = [json.loads(ln) for ln in lines]
    if not entries:
        raise ValueError("screenshots jsonl is empty")

    base_outdir = Path(resolve_repo_path(args.outdir)) if args.outdir else jsonl_path.parent / "screenshots"

    print(f"screenshots_jsonl={jsonl_path}")
    print(f"video={video}")
    print(f"base_outdir={base_outdir}")

    for idx, entry in enumerate(entries, start=1):
        clip_id = entry.get("clip_id")
        if not isinstance(clip_id, str) or not clip_id.strip():
            raise ValueError(f"Invalid clip_id at line {idx}")
        start = float(entry["start"])
        end = float(entry["end"])
        granularity = float(entry.get("granularity", 1.0))
        if start < 0 or end <= start:
            raise ValueError(f"Invalid range for {clip_id}: start={start}, end={end}")
        if granularity <= 0:
            raise ValueError(f"Invalid granularity for {clip_id}: {granularity}")

        clip_outdir = base_outdir / clip_id
        clip_outdir.mkdir(parents=True, exist_ok=True)

        for ts in frame_timestamps(start, end, granularity):
            outpath = clip_outdir / frame_filename(clip_id, ts)
            if outpath.exists() and outpath.stat().st_size > 0:
                print(f"# exists, skipping: {outpath}")
                continue
            cmd = [
                args.ffmpeg_bin,
                "-hide_banner",
                "-y",
                "-i", str(video),
                "-ss", str(ts),
                "-vframes", "1",
                str(outpath),
            ]
            run(cmd)

    print(f"Wrote screenshots to: {base_outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
