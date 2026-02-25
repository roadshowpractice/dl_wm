#!/usr/bin/env python3
"""Transcribe local media files with Whisper, without scraping/snapshot workflows."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Whisper transcription from a local media file path."
    )
    parser.add_argument("input_media_path", metavar="INPUT_MEDIA_PATH")
    parser.add_argument(
        "--outdir",
        default=None,
        help="Output directory (default: directory containing input file)",
    )
    parser.add_argument("--model", default="base", help="Whisper model name")
    parser.add_argument("--language", default=None, help="Language code (optional)")
    parser.add_argument(
        "--task",
        default="transcribe",
        choices=["transcribe", "translate"],
        help="Whisper task",
    )
    parser.add_argument("--srt", action="store_true", help="Write SRT output")
    parser.add_argument("--vtt", action="store_true", help="Write VTT output")
    parser.add_argument("--txt", action="store_true", default=True, help="Write TXT output")
    parser.add_argument("--no-txt", dest="txt", action="store_false", help="Disable TXT output")
    parser.add_argument(
        "--json", action="store_true", default=True, help="Write Whisper JSON output"
    )
    parser.add_argument(
        "--no-json", dest="json", action="store_false", help="Disable Whisper JSON output"
    )
    parser.add_argument(
        "--minute-json",
        action="store_true",
        help="Write simple per-minute JSON summary",
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Skip all URL/metadata resolution",
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help="Manual source URL override, stored in manifest",
    )
    parser.add_argument(
        "--jsonl",
        action="append",
        default=[],
        help="Path to index JSONL file (repeatable)",
    )
    return parser.parse_args(argv)


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg"):
        return
    raise RuntimeError(
        "ffmpeg was not found on PATH. Install ffmpeg before running Whisper transcription."
    )


def safe_parse_jsonl_line(line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def extract_shortcode_from_filename(file_path: Path) -> str | None:
    stem = file_path.stem
    patterns = [
        r"(?:instagram|ig)[-_]?([A-Za-z0-9_-]{5,})",
        r"(?:reel|p)[-_]([A-Za-z0-9_-]{5,})",
        r"([A-Za-z0-9_-]{8,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, stem, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def record_matches_input(record: dict[str, Any], input_path: Path) -> bool:
    default_tasks = record.get("default_tasks")
    perform_download = None
    if isinstance(default_tasks, dict):
        perform_download = default_tasks.get("perform_download")

    if isinstance(perform_download, str):
        if os.path.abspath(perform_download) == str(input_path):
            return True
        if os.path.basename(perform_download) == input_path.name:
            return True

    shortcode = extract_shortcode_from_filename(input_path)
    url = record.get("url")
    if shortcode and isinstance(url, str) and shortcode in url:
        return True

    return False


def resolve_source_url(input_path: Path, jsonl_paths: list[str]) -> str | None:
    for jsonl_path in jsonl_paths:
        jsonl_file = Path(jsonl_path)
        if not jsonl_file.exists():
            continue

        with jsonl_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = safe_parse_jsonl_line(line)
                if not record:
                    continue
                if record_matches_input(record, input_path):
                    url = record.get("url")
                    if isinstance(url, str) and url:
                        return url
                    return None
    return None


def run_whisper(input_path: Path, model_name: str, language: str | None, task: str) -> dict[str, Any]:
    import whisper

    model = whisper.load_model(model_name)
    transcribe_kwargs: dict[str, Any] = {"task": task}
    if language:
        transcribe_kwargs["language"] = language
    return model.transcribe(str(input_path), **transcribe_kwargs)


def format_timestamp(seconds: float, for_vtt: bool = False) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    separator = "." if for_vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def write_srt(segments: list[dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        for index, seg in enumerate(segments, start=1):
            start = format_timestamp(float(seg.get("start", 0.0)))
            end = format_timestamp(float(seg.get("end", 0.0)))
            text = str(seg.get("text", "")).strip()
            handle.write(f"{index}\n{start} --> {end}\n{text}\n\n")


def write_vtt(segments: list[dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("WEBVTT\n\n")
        for seg in segments:
            start = format_timestamp(float(seg.get("start", 0.0)), for_vtt=True)
            end = format_timestamp(float(seg.get("end", 0.0)), for_vtt=True)
            text = str(seg.get("text", "")).strip()
            handle.write(f"{start} --> {end}\n{text}\n\n")


def build_minute_summary(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_minute: dict[int, list[str]] = defaultdict(list)
    for seg in segments:
        minute = int(float(seg.get("start", 0.0)) // 60)
        text = str(seg.get("text", "")).strip()
        if text:
            by_minute[minute].append(text)

    summary = []
    for minute in sorted(by_minute):
        summary.append({"minute": minute, "text": " ".join(by_minute[minute]).strip()})
    return summary


def whisper_package_version() -> str | None:
    try:
        import whisper

        return getattr(whisper, "__version__", None)
    except Exception:
        return None


def write_manifest(
    manifest_path: Path,
    input_path: Path,
    outdir: Path,
    model_name: str,
    task: str,
    language: str | None,
    source_url: str | None,
) -> None:
    manifest = {
        "input_path": str(input_path),
        "outdir": str(outdir),
        "model": model_name,
        "task": task,
        "language": language,
        "source_url": source_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool_versions": {
            "python": platform.python_version(),
            "whisper": whisper_package_version(),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    input_path = Path(args.input_media_path).expanduser().resolve()
    if not input_path.exists() or not input_path.is_file():
        print(f"Input media path does not exist or is not a file: {input_path}", file=sys.stderr)
        return 1

    outdir = Path(args.outdir).expanduser().resolve() if args.outdir else input_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        ensure_ffmpeg_available()
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 2

    source_url: str | None
    if args.source_url:
        source_url = args.source_url
    elif args.no_metadata:
        source_url = None
    else:
        source_url = resolve_source_url(input_path, args.jsonl)

    result = run_whisper(input_path, args.model, args.language, args.task)
    stem = input_path.stem

    if args.json:
        (outdir / f"{stem}.whisper.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    if args.txt:
        (outdir / f"{stem}.txt").write_text(str(result.get("text", "")).strip() + "\n", encoding="utf-8")

    segments = result.get("segments") or []
    if args.srt:
        write_srt(segments, outdir / f"{stem}.srt")
    if args.vtt:
        write_vtt(segments, outdir / f"{stem}.vtt")
    if args.minute_json:
        minute_data = build_minute_summary(segments)
        (outdir / f"{stem}.minute.json").write_text(
            json.dumps(minute_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    write_manifest(
        manifest_path=outdir / f"{stem}.manifest.json",
        input_path=input_path,
        outdir=outdir,
        model_name=args.model,
        task=args.task,
        language=args.language,
        source_url=source_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
