#!/usr/bin/env python3
"""Build a labeled scene video from a scene_split.py + render_scene_cards.py
output dir: real clip footage (not the static cards), scene number burned on
top in the same style as the cards (pink, bold, 2x, top-quarter), assembled
in whatever order a scenes_*.jsonl file specifies.

Usage:
    python3 bin/render_labeled_scene_video.py <scene_clips_dir> <scenes.jsonl> <output.mp4>

Example (forward and reverse, from the same scene_clips dir):
    python3 bin/render_labeled_scene_video.py scene_clips scene_clips/scenes_forward.jsonl scene_clips/clips_labeled_forward.mp4
    python3 bin/render_labeled_scene_video.py scene_clips scene_clips/scenes_reverse.jsonl scene_clips/clips_labeled_reverse.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "Inter-Bold.otf"
FONT_SIZE = 90  # fixed pixel size — ffmpeg drawtext's fontsize doesn't take expressions like iw/6


def label_clip(clip_path: Path, scene_num: int, out_path: Path) -> None:
    drawtext = (
        f"drawtext=fontfile='{FONT_PATH}':text='{scene_num}':"
        f"fontcolor=0xFF1493:fontsize={FONT_SIZE}:x=(w-text_w)/2:y=h*0.25"
    )
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", str(clip_path),
         "-vf", drawtext, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
         str(out_path), "-loglevel", "error"],
        check=True, stdin=subprocess.DEVNULL,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene_dir", help="scene_split.py output dir (contains clips/)")
    parser.add_argument("scenes_jsonl", help="scenes_forward.jsonl or scenes_reverse.jsonl (or any reordering) — determines clip order")
    parser.add_argument("output", help="output video path")
    args = parser.parse_args(argv)

    scene_dir = Path(args.scene_dir).expanduser().resolve()
    clips_dir = scene_dir / "clips"
    scenes_jsonl = Path(args.scenes_jsonl).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    if not scenes_jsonl.exists():
        print(f"Not found: {scenes_jsonl}", file=sys.stderr)
        return 1

    records = [json.loads(l) for l in scenes_jsonl.read_text().splitlines() if l.strip()]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        concat_list = tmp_path / "concat.txt"
        lines = []
        for i, rec in enumerate(records, start=1):
            clip_id = rec["clip_id"]
            scene_num = rec["scene_num"]
            clip_path = clips_dir / f"{clip_id}.mp4"
            seg_path = tmp_path / f"seg_{i:03d}.mp4"
            label_clip(clip_path, scene_num, seg_path)
            lines.append(f"file '{seg_path}'")
        concat_list.write_text("\n".join(lines))

        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", str(output), "-loglevel", "error"],
            check=True, stdin=subprocess.DEVNULL,
        )

    print(f"written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
