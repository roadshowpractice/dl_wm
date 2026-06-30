#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def run_transcription_for_clip(clip_path: Path, output_path: Path) -> bool:
    from dl_wm.transcription_caller import run_transcription

    return run_transcription(str(clip_path), str(output_path), "srt")


SRT_TIMESTAMP_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2},\d{3})(?:\s+.*)?$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate clip-relative SRTs from transcript timing data or generate a single SRT for one clip."
    )
    parser.add_argument("--clip-path", help="Path to a single extracted clip video")
    parser.add_argument("--output", help="Output path for single-clip SRT generation")
    parser.add_argument("--clips-jsonl", help="Path to the clips JSONL file")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--transcript-json", help="Path to the Whisper-like transcript JSON file")
    source_group.add_argument("--transcript-srt", help="Path to the source SRT subtitle file")
    parser.add_argument("--output-dir", help="Base output directory for subtitles/")
    args = parser.parse_args()

    single_clip_mode = bool(args.clip_path or args.output)
    batch_mode = bool(args.clips_jsonl or args.output_dir or args.transcript_json or args.transcript_srt)

    if single_clip_mode:
        if not args.clip_path or not args.output:
            parser.error("--clip-path and --output are required together")
        if args.clips_jsonl or args.output_dir or args.transcript_json or args.transcript_srt:
            parser.error("single-clip mode does not accept batch transcript arguments")
        return args

    if batch_mode:
        if not args.clips_jsonl:
            parser.error("--clips-jsonl is required in batch mode")
        if not args.output_dir:
            parser.error("--output-dir is required in batch mode")
        if not (args.transcript_json or args.transcript_srt):
            parser.error("batch mode requires --transcript-json or --transcript-srt")
        return args

    parser.error(
        "provide either --clip-path/--output for single-clip mode or --clips-jsonl with transcript source args for batch mode"
    )


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


def _normalize_word(word: dict[str, Any]) -> dict[str, Any] | None:
    try:
        start = float(word["start"])
        end = float(word["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if end <= start:
        return None
    text = str(word.get("word", ""))
    if not text.strip():
        return None
    return {"start": start, "end": end, "text": text}


def build_timing_entries_from_json(transcript_path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        data = json.loads(transcript_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in transcript file '{transcript_path}': {exc}") from exc

    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Transcript JSON must contain a list at key 'segments'")

    words: list[dict[str, Any]] = []
    normalized_segments: list[dict[str, Any]] = []
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
        if text:
            normalized_segments.append({"start": start, "end": end, "text": text})
        raw_words = segment.get("words")
        if isinstance(raw_words, list):
            for word in raw_words:
                if not isinstance(word, dict):
                    continue
                normalized = _normalize_word(word)
                if normalized is not None:
                    words.append(normalized)

    if words:
        return "word_timestamps", words
    return "native_segments", normalized_segments


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


def load_transcript(transcript_json: Path | None, transcript_srt: Path | None) -> tuple[str, list[dict[str, Any]]]:
    if transcript_json is not None:
        return build_timing_entries_from_json(transcript_json)
    if transcript_srt is not None:
        return "srt_segments", load_transcript_srt(transcript_srt)
    raise ValueError("Either --transcript-json or --transcript-srt is required")


def _join_word_texts(words: list[dict[str, Any]]) -> str:
    return "".join(str(word["text"]) for word in words).strip()


def word_rows_for_clip(
    words: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
    *,
    max_words_per_caption: int = 3,
    max_gap_seconds: float = 0.5,
) -> list[dict[str, Any]]:
    clipped_words: list[dict[str, Any]] = []
    for word in words:
        word_start = float(word["start"])
        word_end = float(word["end"])
        if word_end <= clip_start or word_start >= clip_end:
            continue
        start = max(word_start, clip_start) - clip_start
        end = min(word_end, clip_end) - clip_start
        if end <= start:
            continue
        clipped_words.append({"start": round(start, 3), "end": round(end, 3), "text": str(word["text"])})

    if not clipped_words:
        return []

    rows: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    for word in clipped_words:
        if current:
            prev = current[-1]
            gap = float(word["start"]) - float(prev["end"])
            boundary_text = str(prev["text"]).strip()
            if (
                len(current) >= max_words_per_caption
                or gap > max_gap_seconds
                or boundary_text.endswith((".", "!", "?", ",", ";", ":"))
            ):
                rows.append(
                    {
                        "start": round(float(current[0]["start"]), 3),
                        "end": round(float(current[-1]["end"]), 3),
                        "text": _join_word_texts(current),
                    }
                )
                current = []
        current.append(word)

    if current:
        rows.append(
            {
                "start": round(float(current[0]["start"]), 3),
                "end": round(float(current[-1]["end"]), 3),
                "text": _join_word_texts(current),
            }
        )

    return rows


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


def rows_for_clip(
    timing_source: str,
    entries: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
) -> list[dict[str, Any]]:
    if timing_source == "word_timestamps":
        return word_rows_for_clip(entries, clip_start, clip_end)
    return segments_for_clip(entries, clip_start, clip_end)


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
            handle.write(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n")
            handle.write(f"{text}\n\n")
            written_index += 1


def generated_srt_path_for_clip(clip_path: Path, output_path: Path) -> Path:
    return output_path.parent / f"{clip_path.stem}.srt"


def generate_single_clip_srt(clip_path: Path, output_path: Path) -> Path:
    if not clip_path.is_file():
        raise FileNotFoundError(f"Clip file not found: {clip_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clip_srt_") as tmpdir:
        temp_output = Path(tmpdir) / output_path.name
        if not run_transcription_for_clip(clip_path, temp_output):
            raise RuntimeError(f"Failed to generate SRT for clip: {clip_path}")

        candidate_paths = [temp_output, generated_srt_path_for_clip(clip_path, temp_output)]
        actual_path = next((path for path in candidate_paths if path.is_file()), None)
        if actual_path is None:
            raise RuntimeError(f"Transcription completed without creating an SRT for clip: {clip_path}")

        shutil.move(str(actual_path), str(output_path))

    return output_path


def main() -> int:
    args = parse_args()

    if args.clip_path:
        output_path = generate_single_clip_srt(Path(args.clip_path), Path(args.output))
        print(f"wrote {output_path}")
        return 0

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
    timing_source, entries = load_transcript(transcript_json, transcript_srt)

    subtitles_dir = output_dir / "subtitles"
    subtitles_dir.mkdir(parents=True, exist_ok=True)

    for clip in clips:
        clip_id = clip["clip_id"]
        rows = rows_for_clip(timing_source, entries, clip["start"], clip["end"])
        srt_path = subtitles_dir / f"{clip_id}.srt"
        write_srt(srt_path, rows)
        print(f"wrote {srt_path} (subtitle_source={timing_source}, rows={len(rows)})")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        raise SystemExit(f"Error: {exc}")
