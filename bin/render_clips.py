#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


def detect_repo_root() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True)
    return Path(proc.stdout.strip()).resolve()


def resolve_path(raw: str, repo_root: Path) -> Path:
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render clips from clips.jsonl using ffmpeg.")
    p.add_argument("clips_jsonl", nargs="?", default=None, help="Path to clips.jsonl (default inferred: outputs/<latest-run>/clips/clips.jsonl)")
    p.add_argument("--video", default=None, help="Video override path")
    p.add_argument("--outdir", default=None, help="Output clip directory (default: sibling folder of clips.jsonl)")
    p.add_argument("--mode", choices=["accurate", "fast"], default=os.environ.get("MODE", "accurate"))
    p.add_argument("--vcodec", default=os.environ.get("VCODEC", "libx264"))
    p.add_argument("--acodec", default=os.environ.get("ACODEC", "aac"))
    p.add_argument("--preset", default=os.environ.get("PRESET", "medium"))
    p.add_argument("--crf", default=os.environ.get("CRF", "18"))
    p.add_argument("--ffmpeg-bin", default=os.environ.get("FFMPEG_BIN", "ffmpeg"))
    return p.parse_args(argv)


def infer_default_jsonl(repo_root: Path) -> Path:
    outputs = repo_root / "outputs"
    candidates = list(outputs.glob("*/clips/clips.jsonl"))
    if not candidates:
        raise FileNotFoundError("No outputs/*/clips/clips.jsonl found. Pass clips_jsonl explicitly.")
    return max(candidates, key=lambda p: p.stat().st_mtime).resolve()


def resolve_manifest_path(value: Any, repo_root: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    p = Path(value)
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def clip_filename(clip_id: str, start: float, end: float) -> str:
    s_ms = int(round(start * 1000))
    e_ms = int(round(end * 1000))
    return f"{clip_id}_{s_ms:09d}-{e_ms:09d}.mp4"


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = detect_repo_root()
    jsonl_path = resolve_path(args.clips_jsonl, repo_root) if args.clips_jsonl else infer_default_jsonl(repo_root)
    if not jsonl_path.exists():
        raise FileNotFoundError(f"clips jsonl not found: {jsonl_path}")

    lines = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    clips: list[dict[str, Any]] = [json.loads(ln) for ln in lines]
    if not clips:
        raise ValueError("clips jsonl is empty")

    default_video = resolve_manifest_path(clips[0].get("input_video_path"), repo_root)
    video = resolve_path(args.video, repo_root) if args.video else default_video
    if video is None:
        raise ValueError("No video could be resolved. Provide --video or include input_video_path in manifest.")
    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")

    outdir = resolve_path(args.outdir, repo_root) if args.outdir else jsonl_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"repo_root={repo_root}")
    print(f"clips_jsonl={jsonl_path}")
    print(f"video={video}")
    print(f"outdir={outdir}")

    for idx, clip in enumerate(clips, start=1):
        clip_id = clip.get("clip_id")
        if not isinstance(clip_id, str) or not clip_id.strip():
            raise ValueError(f"Invalid clip_id at line {idx}")
        start = float(clip.get("start"))
        end = float(clip.get("end"))
        if start < 0 or end <= start:
            raise ValueError(f"Invalid range for {clip_id}: start={start}, end={end}")

        outpath = outdir / clip_filename(clip_id, start, end)
        if outpath.exists() and outpath.stat().st_size > 0:
            print(f"# exists, skipping: {outpath}")
            continue

        duration = end - start

        if args.mode == "fast":
            cmd = [args.ffmpeg_bin, "-hide_banner", "-y", "-ss", str(start), "-to", str(end), "-i", str(video), "-c", "copy", str(outpath)]
        else:
            cmd = [
                args.ffmpeg_bin,
                "-hide_banner",
                "-y",
                "-i",
                str(video),
                "-ss",
                str(start),
                "-t",
                str(duration),
                "-c:v",
                args.vcodec,
                "-preset",
                args.preset,
                "-crf",
                str(args.crf),
                "-c:a",
                args.acodec,
                "-movflags",
                "+faststart",
                str(outpath),
            ]
        run(cmd)

    print(f"Wrote clips to: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
