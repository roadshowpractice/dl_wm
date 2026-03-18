#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SRT_TIMESTAMP_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2},\d{3})(?:\s+.*)?$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one clip-relative SRT per clip from clips JSONL and either transcript JSON or a source SRT."
    )
    parser.add_argument("--clips-jsonl", required=True, help="Path to the clips JSONL file")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--transcript-json", help="Path to the Whisper-like transcript JSON file")
    source_group.add_argument("--transcript-srt", help="Path to the source SRT subtitle file")
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


def load_transcript_json(transcript_path: Path) -> list[dict[str, Any]]:
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


def parse_srt_timestamp(raw: str) -> float:
    hours_part, minutes_part, seconds_part = raw.split(":")
    seconds_text, millis_text = seconds_part.split(",")
    return (
        int(hours_part) * 3600
        + int(minutes_part) * 60
        + int(seconds_text)
        + int(millis_text) / 1000.0
    )


def load_transcript_srt(transcript_path: Path) -> list[dict[str, Any]]:
    content = transcript_path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    normalized: list[dict[str, Any]] = []

    for index, block in enumerate(blocks, start=1):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        timestamp_index = 0
        if len(lines) >= 2 and lines[0].isdigit():
            timestamp_index = 1
        if timestamp_index >= len(lines):
            raise ValueError(f"SRT block {index} is missing a timestamp line")

        timestamp_line = lines[timestamp_index]
        match = SRT_TIMESTAMP_RE.match(timestamp_line)
        if not match:
            raise ValueError(f"SRT block {index} has an invalid timestamp line: {timestamp_line!r}")

        start = parse_srt_timestamp(match.group("start"))
        end = parse_srt_timestamp(match.group("end"))
        if end <= start:
            continue

        text_lines = lines[timestamp_index + 1 :]
        text = "\n".join(part.strip() for part in text_lines if part.strip())
        normalized.append({"start": start, "end": end, "text": text})

    return normalized


def load_transcript(transcript_json: Path | None, transcript_srt: Path | None) -> list[dict[str, Any]]:
    if transcript_json is not None:
        return load_transcript_json(transcript_json)
    if transcript_srt is not None:
        return load_transcript_srt(transcript_srt)
    raise ValueError("Either --transcript-json or --transcript-srt is required")


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
    transcript_json = Path(args.transcript_json) if args.transcript_json else None
    transcript_srt = Path(args.transcript_srt) if args.transcript_srt else None
    output_dir = Path(args.output_dir)

    if not clips_path.is_file():
        raise FileNotFoundError(f"Clips JSONL file not found: {clips_path}")
    if transcript_json is not None and not transcript_json.is_file():
        raise FileNotFoundError(f"Transcript JSON file not found: {transcript_json}")
    if transcript_srt is not None and not transcript_srt.is_file():
        raise FileNotFoundError(f"Transcript SRT file not found: {transcript_srt}")

    clips = load_clips(clips_path)
    segments = load_transcript(transcript_json, transcript_srt)

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
