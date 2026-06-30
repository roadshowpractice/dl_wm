#!/usr/bin/env python3
"""Parse an SRT, group entries by silence gap, grab a midpoint screenshot per clip,
and emit a JSONL compatible with the pipeline clip format."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SrtEntry:
    index: int
    start: float
    end: float
    text: str


def parse_srt_time(s: str) -> float:
    hh, mm, rest = s.split(":")
    ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0


def parse_srt(path: Path) -> list[SrtEntry]:
    raw = path.read_text(encoding="utf-8")
    entries: list[SrtEntry] = []
    for block in re.split(r"\n\n+", raw.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        m = re.match(r"(\S+)\s+-->\s+(\S+)", lines[1])
        if not m:
            continue
        entries.append(SrtEntry(
            index=idx,
            start=parse_srt_time(m.group(1)),
            end=parse_srt_time(m.group(2)),
            text=" ".join(lines[2:]).strip(),
        ))
    return entries


def group_by_gap(entries: list[SrtEntry], gap_seconds: float) -> list[list[SrtEntry]]:
    if not entries:
        return []
    groups: list[list[SrtEntry]] = [[entries[0]]]
    for entry in entries[1:]:
        if entry.start - groups[-1][-1].end >= gap_seconds:
            groups.append([])
        groups[-1].append(entry)
    return groups


def grab_screenshot(video_path: Path, timestamp: float, out_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(out_path),
        ],
        check=True,
        capture_output=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SRT -> clip JSONL with screenshots",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("srt", help="SRT file path")
    parser.add_argument("video", help="Video file to grab screenshots from")
    parser.add_argument(
        "--gap-seconds", type=float, default=2.0,
        help="Gap between SRT entries (seconds) that starts a new clip",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory for screenshots and JSONL (default: <srt_dir>/srt_clips/)",
    )
    parser.add_argument(
        "--jsonl-out", default=None,
        help="Output JSONL path (default: <output-dir>/clips.jsonl)",
    )
    parser.add_argument(
        "--no-screenshots", action="store_true",
        help="Skip screenshot extraction (useful for dry-run inspection)",
    )
    args = parser.parse_args(argv)

    srt_path = Path(args.srt)
    video_path = Path(args.video)
    output_dir = Path(args.output_dir) if args.output_dir else srt_path.parent / "srt_clips"
    jsonl_out = Path(args.jsonl_out) if args.jsonl_out else output_dir / "clips.jsonl"

    if not srt_path.exists():
        print(f"Error: SRT not found: {srt_path}", file=sys.stderr)
        return 1
    if not video_path.exists():
        print(f"Error: Video not found: {video_path}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Parsing: {srt_path}")
    entries = parse_srt(srt_path)
    print(f"  {len(entries)} SRT entries")

    groups = group_by_gap(entries, args.gap_seconds)
    print(f"  {len(groups)} clips at gap >= {args.gap_seconds}s")

    rows = []
    for i, group in enumerate(groups, start=1):
        clip_id = f"clip_{i:03d}"
        start = group[0].start
        end = group[-1].end
        mid = (start + end) / 2.0
        text = " ".join(e.text for e in group)
        screenshot_path = output_dir / f"{clip_id}.jpg"

        if not args.no_screenshots:
            print(f"  [{i}/{len(groups)}] {clip_id}  {start:.1f}s – {end:.1f}s  screenshot @ {mid:.1f}s")
            grab_screenshot(video_path, mid, screenshot_path)

        rows.append({
            "clip_id": clip_id,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "screenshot_path": str(screenshot_path),
        })

    with jsonl_out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nDone: {len(rows)} clips")
    print(f"  JSONL:       {jsonl_out}")
    if not args.no_screenshots:
        print(f"  Screenshots: {output_dir}/clip_NNN.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
