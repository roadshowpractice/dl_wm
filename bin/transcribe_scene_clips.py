#!/usr/bin/env python3
"""Transcribe every clip from a scene_split.py output dir.

Writes a real per-clip .srt (via the existing Whisper pipeline, one
subprocess per clip so a long batch doesn't hold one giant process/model
in memory) into <scene_dir>/subtitles/, and aggregates every clip's scene
metadata + transcript into one JSON manifest.

Resumable: the manifest is rewritten after every clip, and a clip already
present in an existing manifest (with a still-present .whisper.json cache)
is skipped on a rerun - killing/restarting mid-batch loses at most the one
clip in flight, not prior progress.

Usage:
    python bin/transcribe_scene_clips.py <scene_clips_dir> \
        [--jsonl scenes_forward.jsonl] [--out clips_transcripts.json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent

# This machine is memory-constrained enough that even Whisper's "base" model
# (transcribe_media.py's own default) can get OOM-killed on a single short
# clip once word-timestamp alignment is enabled. "tiny" is far lighter and
# plenty for basic clip captioning at this scale.
WHISPER_MODEL = "tiny"


def transcribe_clip(clip_path: Path, outdir: Path) -> bool:
    script_path = ROOT_DIR / "bin" / "transcribe_media.py"
    cmd = [
        sys.executable, str(script_path), str(clip_path),
        "--outdir", str(outdir),
        "--model", WHISPER_MODEL,
        "--chunk-seconds", "300",
        "--srt", "--no-txt",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return False
    return True


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_manifest(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"clips": []}


def whisper_segments(whisper_data: dict) -> list[dict]:
    segments = []
    for seg in whisper_data.get("segments", []):
        segments.append({
            "start": seg.get("start"),
            "end": seg.get("end"),
            "text": (seg.get("text") or "").strip(),
            "words": [
                {"word": w.get("word"), "start": w.get("start"), "end": w.get("end")}
                for w in seg.get("words", [])
            ],
        })
    return segments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene_dir", help="scene_split.py output dir (contains clips/ and a scenes_*.jsonl)")
    parser.add_argument("--jsonl", default="scenes_forward.jsonl", help="scene manifest filename inside scene_dir")
    parser.add_argument("--out", default="clips_transcripts.json", help="output JSON filename inside scene_dir")
    args = parser.parse_args(argv)

    scene_dir = Path(args.scene_dir).expanduser().resolve()
    clips_dir = scene_dir / "clips"
    subs_dir = scene_dir / "subtitles"
    subs_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = scene_dir / args.jsonl
    if not jsonl_path.is_file():
        print(f"Not found: {jsonl_path}", file=sys.stderr)
        return 1
    records = load_jsonl(jsonl_path)

    out_path = scene_dir / args.out
    manifest = load_manifest(out_path)
    done_by_id = {c["clip_id"]: c for c in manifest.get("clips", []) if c.get("segments") is not None}

    clips_out: list[dict] = []
    n = len(records)
    for i, rec in enumerate(records, start=1):
        clip_id = rec["clip_id"]

        if clip_id in done_by_id:
            print(f"[{i}/{n}] {clip_id} - already done, skipping")
            clips_out.append(done_by_id[clip_id])
            continue

        clip_path = clips_dir / f"{clip_id}.mp4"
        if not clip_path.is_file():
            print(f"[{i}/{n}] {clip_id} - SKIP, no clip file at {clip_path}", file=sys.stderr)
            clip_record = dict(rec)
            clip_record.update({"srt_path": None, "language": None, "text": None, "segments": None, "error": "missing_clip_file"})
            clips_out.append(clip_record)
            _write_manifest(out_path, scene_dir, jsonl_path, clips_out)
            continue

        srt_path = subs_dir / f"{clip_id}.srt"
        whisper_json_path = subs_dir / f"{clip_id}.whisper.json"
        duration = rec["end"] - rec["start"]
        print(f"[{i}/{n}] {clip_id} ({duration:.1f}s)")

        ok = transcribe_clip(clip_path, subs_dir)
        if not ok or not whisper_json_path.is_file():
            print(f"  ! transcription failed for {clip_id}", file=sys.stderr)
            clip_record = dict(rec)
            clip_record.update({"srt_path": None, "language": None, "text": None, "segments": None, "error": "transcription_failed"})
        else:
            whisper_data = json.loads(whisper_json_path.read_text(encoding="utf-8"))
            clip_record = dict(rec)
            clip_record.update({
                "duration": round(duration, 3),
                "srt_path": str(srt_path),
                "language": whisper_data.get("language"),
                "text": (whisper_data.get("text") or "").strip(),
                "segments": whisper_segments(whisper_data),
            })

        clips_out.append(clip_record)
        _write_manifest(out_path, scene_dir, jsonl_path, clips_out)

    print(f"done: {out_path} ({len(clips_out)} clips)")
    return 0


def _write_manifest(out_path: Path, scene_dir: Path, jsonl_path: Path, clips_out: list[dict]) -> None:
    manifest = {
        "scene_dir": str(scene_dir),
        "jsonl_source": str(jsonl_path),
        "clip_count": len(clips_out),
        "clips": clips_out,
    }
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
