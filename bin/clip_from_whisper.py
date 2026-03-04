#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def detect_repo_root() -> Path:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        return Path(proc.stdout.strip()).resolve()
    except Exception as exc:
        raise RuntimeError("Unable to detect repo root via git rev-parse --show-toplevel") from exc


def resolve_input_path(raw: str, repo_root: Path) -> Path:
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def repo_rel(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root).as_posix() if path.resolve().is_relative_to(repo_root) else Path(path).resolve().as_posix()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build question-based clip manifest from Whisper JSON.")
    parser.add_argument("whisper_json", help="Whisper JSON path (abs or repo-root-relative)")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--run", default=None, help="Run name under outputs/<run> (inferred by default)")
    parser.add_argument("--output", default=None, help="Output JSONL path (default outputs/<run>/clips/clips.jsonl)")
    parser.add_argument("--input-video", default=None, help="Input video path override")
    parser.add_argument("--max-seconds", type=float, default=600.0)
    parser.add_argument("--question-block-gap-seconds", type=float, default=3.0)
    parser.add_argument("--clip-end-padding-seconds", type=float, default=0.2)
    parser.add_argument("--question-marker", default="?")
    return parser.parse_args(argv)


@dataclass
class QuestionClip:
    start: float
    question_text: str


def find_input_video_from_manifest(whisper_json: Path, repo_root: Path) -> Path | None:
    manifest = whisper_json.with_name(f"{whisper_json.stem.removesuffix('.whisper')}.manifest.json")
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    raw = data.get("input_path")
    if not isinstance(raw, str) or not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    return p.resolve()


def load_segments(whisper_json: Path) -> list[dict[str, Any]]:
    data = json.loads(whisper_json.read_text(encoding="utf-8"))
    segs = data.get("segments")
    if not isinstance(segs, list):
        raise ValueError("Whisper JSON must contain a list at key 'segments'.")
    return segs


def collect_question_starts(segments: list[dict[str, Any]], marker: str, max_seconds: float) -> list[QuestionClip]:
    out: list[QuestionClip] = []
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if marker not in text:
            continue
        start = float(seg.get("start", 0.0))
        if start < 0 or start > max_seconds:
            continue
        out.append(QuestionClip(start=start, question_text=text))
    out.sort(key=lambda c: c.start)
    dedup: list[QuestionClip] = []
    for clip in out:
        if dedup and abs(clip.start - dedup[-1].start) < 1e-6:
            continue
        dedup.append(clip)
    return dedup


def infer_run(whisper_json: Path, repo_root: Path) -> str:
    rel = whisper_json.resolve().relative_to(repo_root)
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "outputs":
        return parts[1]
    raise ValueError("Could not infer run from whisper path; pass --run.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = resolve_input_path(args.repo_root, Path.cwd()) if args.repo_root else detect_repo_root()
    whisper_json = resolve_input_path(args.whisper_json, repo_root)

    if not whisper_json.exists():
        raise FileNotFoundError(f"Whisper JSON not found: {whisper_json}")

    run = args.run or infer_run(whisper_json, repo_root)
    out_jsonl = resolve_input_path(args.output, repo_root) if args.output else (repo_root / "outputs" / run / "clips" / "clips.jsonl").resolve()
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)

    input_video = resolve_input_path(args.input_video, repo_root) if args.input_video else find_input_video_from_manifest(whisper_json, repo_root)
    if input_video is None:
        raise ValueError("Could not resolve input video path. Pass --input-video or ensure whisper manifest exists.")
    if not input_video.exists():
        raise FileNotFoundError(f"Input video does not exist: {input_video}")

    segs = load_segments(whisper_json)
    questions = collect_question_starts(segs, args.question_marker, args.max_seconds)
    if not questions:
        raise ValueError("No question markers found in segment text.")

    rows: list[dict[str, Any]] = []
    pad = args.clip_end_padding_seconds
    for idx, q in enumerate(questions, start=1):
        next_start = questions[idx].start if idx < len(questions) else args.max_seconds
        end = max(q.start + 0.01, min(args.max_seconds, next_start - pad))
        if end <= q.start:
            continue
        rows.append(
            {
                "clip_id": f"clip_{idx:03d}",
                "start": round(q.start, 3),
                "end": round(end, 3),
                "question_text": q.question_text,
                "input_video_path": repo_rel(input_video, repo_root),
                "source_whisper_json": repo_rel(whisper_json, repo_root),
                "max_seconds": args.max_seconds,
                "heuristic": {
                    "question_marker": args.question_marker,
                    "question_block_gap_seconds": args.question_block_gap_seconds,
                    "clip_end_padding_seconds": args.clip_end_padding_seconds,
                    "clip_end_rule": "next_question_start_minus_pad (last clip ends at max_seconds_minus_pad)",
                },
            }
        )

    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest_path = out_jsonl.with_suffix(".manifest.json")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": repo_root.as_posix(),
        "run": run,
        "clips_jsonl": repo_rel(out_jsonl, repo_root),
        "input_video_path": repo_rel(input_video, repo_root),
        "source_whisper_json": repo_rel(whisper_json, repo_root),
        "clip_count": len(rows),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"repo_root={repo_root}")
    print(f"whisper_json={whisper_json}")
    print(f"input_video={input_video}")
    print(f"out_jsonl={out_jsonl}")
    print(f"manifest={manifest_path}")
    print(f"clips={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
