#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one clip-relative SRT per clip from clips JSONL and Whisper-like transcript JSON."
    )
    parser.add_argument("--clips-jsonl", required=True, help="Path to the clips JSONL file")
    parser.add_argument("--transcript-json", required=True, help="Path to the Whisper-like transcript JSON file")
    parser.add_argument("--output-dir", required=True, help="Base output directory for subtitles/")
    return parser.parse_args()


def load_clips(jsonl_path: Path) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in clips JSONL at line {lineno}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Clip row at line {lineno} must be a JSON object")

            clip_id = row.get("clip_id")
            start = row.get("start")
            end = row.get("end")

            if not isinstance(clip_id, str) or not clip_id.strip():
                raise ValueError(f"Clip row at line {lineno} is missing a valid clip_id")
            try:
                clip_start = float(start)
                clip_end = float(end)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Clip '{clip_id}' at line {lineno} has invalid start/end values") from exc
            if clip_end <= clip_start:
                raise ValueError(f"Clip '{clip_id}' at line {lineno} has end <= start")

            clip = dict(row)
            clip["clip_id"] = clip_id.strip()
            clip["start"] = clip_start
            clip["end"] = clip_end
            clips.append(clip)
    return clips


def load_transcript(transcript_path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(transcript_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in transcript file '{transcript_path}': {exc}") from exc

    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Transcript JSON must contain a list at key 'segments'")

    normalized: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise ValueError(f"Transcript segment {index} must be a JSON object")
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Transcript segment {index} is missing valid start/end timestamps") from exc
        if end <= start:
            continue
        text = str(segment.get("text", "")).strip()
        normalized.append({"start": start, "end": end, "text": text})
    return normalized


def segments_for_clip(segments: list[dict[str, Any]], clip_start: float, clip_end: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in segments:
        segment_start = float(segment["start"])
        segment_end = float(segment["end"])
        if segment_end <= clip_start or segment_start >= clip_end:
            continue

        row_start = max(segment_start, clip_start) - clip_start
        row_end = min(segment_end, clip_end) - clip_start
        text = str(segment.get("text", "")).strip()

        if row_end <= row_start or not text:
            continue

        rows.append({"start": row_start, "end": row_end, "text": text})
    return rows


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt(srt_path: Path, rows: list[dict[str, Any]]) -> None:
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    with srt_path.open("w", encoding="utf-8") as handle:
        written_index = 1
        for row in rows:
            text = str(row.get("text", "")).strip()
            start = float(row.get("start", 0.0))
            end = float(row.get("end", 0.0))
            if not text or end <= start:
                continue
            handle.write(f"{written_index}\n")
            handle.write(
                f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n"
            )
            handle.write(f"{text}\n\n")
            written_index += 1


def main() -> int:
    args = parse_args()

    clips_path = Path(args.clips_jsonl)
    transcript_path = Path(args.transcript_json)
    output_dir = Path(args.output_dir)

    if not clips_path.is_file():
        raise FileNotFoundError(f"Clips JSONL file not found: {clips_path}")
    if not transcript_path.is_file():
        raise FileNotFoundError(f"Transcript JSON file not found: {transcript_path}")

    clips = load_clips(clips_path)
    segments = load_transcript(transcript_path)

    subtitles_dir = output_dir / "subtitles"
    subtitles_dir.mkdir(parents=True, exist_ok=True)

    for clip in clips:
        clip_id = clip["clip_id"]
        rows = segments_for_clip(segments, clip["start"], clip["end"])
        srt_path = subtitles_dir / f"{clip_id}.srt"
        write_srt(srt_path, rows)
        print(f"wrote {srt_path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        raise SystemExit(f"Error: {exc}")
