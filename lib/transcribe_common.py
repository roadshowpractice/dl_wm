"""Engine-agnostic plumbing shared by bin/transcribe_media*.py callers.

Each transcription engine (openai-whisper, faster-whisper, and future ones
like Kaldi) gets its own bin/transcribe_media_<engine>.py script with the
same CLI contract (positional media path, --outdir, --chunk-seconds,
--srt/--txt/--no-txt/...) so any of them can be dropped into
conf/app_config.json's transcription.caller_command interchangeably. This
module holds everything that doesn't vary by engine: arg parsing, repo/path
resolution, source-URL lookup, audio chunking, SRT/VTT/minute-summary
formatting, and manifest writing. An engine script only needs to supply a
`transcribe_one(audio_path, *, model_name, language, task) -> dict` callable
returning {"text": str, "segments": [...], "language": str|None} in the same
shape as openai-whisper's own output (segments optionally carrying a
"words" list of {"word", "start", "end"} for fine-grained SRT timing).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

TranscribeOneFn = Callable[..., dict[str, Any]]


def detect_repo_root() -> Path:
    proc = shutil.which("git")
    if not proc:
        raise RuntimeError("git is required to detect repository root")
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip()).resolve()


def repo_relative(path: Path, repo_root: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(repo_root).as_posix() if resolved.is_relative_to(repo_root) else resolved.as_posix()


def build_arg_parser(*, default_model: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("input_media_path", metavar="INPUT_MEDIA_PATH")
    parser.add_argument(
        "--outdir",
        default=None,
        help="Output directory (default: directory containing input file)",
    )
    parser.add_argument("--model", default=default_model, help="Model name/size")
    parser.add_argument("--language", default=None, help="Language code (optional)")
    parser.add_argument(
        "--task",
        default="transcribe",
        choices=["transcribe", "translate"],
        help="Transcription task",
    )
    parser.add_argument("--srt", action="store_true", help="Write SRT output")
    parser.add_argument("--vtt", action="store_true", help="Write VTT output")
    parser.add_argument("--txt", action="store_true", default=True, help="Write TXT output")
    parser.add_argument("--no-txt", dest="txt", action="store_false", help="Disable TXT output")
    parser.add_argument("--json", action="store_true", default=True, help="Write transcript JSON output")
    parser.add_argument("--no-json", dest="json", action="store_false", help="Disable JSON output")
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
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=300,
        help="Chunk length in seconds for long-form transcription (default: 300). Set 0 to disable chunking.",
    )
    return parser


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg"):
        return
    raise RuntimeError(
        "ffmpeg was not found on PATH. Install ffmpeg before running transcription."
    )


def safe_parse_jsonl_line(line: str) -> Optional[dict[str, Any]]:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def extract_shortcode_from_filename(file_path: Path) -> Optional[str]:
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


def resolve_source_url(input_path: Path, jsonl_paths: list[str]) -> Optional[str]:
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


def media_duration_seconds(input_path: Path) -> Optional[float]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        raw = completed.stdout.strip()
        if not raw:
            return None
        duration = float(raw)
        return duration if duration > 0 else None
    except Exception:
        return None


def _offset_segments(segments: list[dict[str, Any]], offset: float) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for seg in segments:
        copy_seg = dict(seg)
        if "start" in copy_seg:
            copy_seg["start"] = float(copy_seg["start"]) + offset
        if "end" in copy_seg:
            copy_seg["end"] = float(copy_seg["end"]) + offset
        words = copy_seg.get("words")
        if isinstance(words, list):
            adjusted_words: list[dict[str, Any]] = []
            for word in words:
                if not isinstance(word, dict):
                    continue
                copy_word = dict(word)
                if "start" in copy_word:
                    copy_word["start"] = float(copy_word["start"]) + offset
                if "end" in copy_word:
                    copy_word["end"] = float(copy_word["end"]) + offset
                adjusted_words.append(copy_word)
            copy_seg["words"] = adjusted_words
        adjusted.append(copy_seg)
    return adjusted


def _extract_chunk_to_wav(input_path: Path, chunk_path: Path, start_seconds: float, duration_seconds: int) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(start_seconds),
        "-i",
        str(input_path),
        "-t",
        str(duration_seconds),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(chunk_path),
    ]
    subprocess.run(cmd, check=True)


def run_chunked_transcription(
    input_path: Path,
    chunk_seconds: int,
    transcribe_one: TranscribeOneFn,
    **transcribe_kwargs: Any,
) -> dict[str, Any]:
    """Chunk long media into <=chunk_seconds pieces and stitch the results back
    into one {"text", "segments", "language"} result, offsetting each chunk's
    segment timestamps by its start offset. Falls back to a single
    whole-file call when duration is unknown or already <= chunk_seconds.
    """
    duration = media_duration_seconds(input_path)
    if not duration or chunk_seconds <= 0 or duration <= chunk_seconds:
        return transcribe_one(str(input_path), **transcribe_kwargs)

    print(
        f"Chunked transcription enabled: duration={duration:.1f}s, chunk_seconds={chunk_seconds}",
        file=sys.stderr,
    )

    all_segments: list[dict[str, Any]] = []
    text_parts: list[str] = []
    language_detected: Optional[str] = None

    with tempfile.TemporaryDirectory(prefix="transcribe_chunks_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        start = 0.0
        chunk_index = 0

        while start < duration:
            chunk_path = tmpdir_path / f"chunk_{chunk_index:04d}.wav"
            _extract_chunk_to_wav(input_path, chunk_path, start, chunk_seconds)

            chunk_result = transcribe_one(str(chunk_path), **transcribe_kwargs)
            chunk_segments = chunk_result.get("segments") or []
            all_segments.extend(_offset_segments(chunk_segments, start))

            chunk_text = str(chunk_result.get("text", "")).strip()
            if chunk_text:
                text_parts.append(chunk_text)

            if not language_detected:
                maybe_lang = chunk_result.get("language")
                if isinstance(maybe_lang, str) and maybe_lang:
                    language_detected = maybe_lang

            start += chunk_seconds
            chunk_index += 1

    return {
        "text": "\n".join(text_parts).strip(),
        "segments": all_segments,
        "language": language_detected,
    }


def format_timestamp(seconds: float, for_vtt: bool = False) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    separator = "." if for_vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def write_srt(segments: list[dict[str, Any]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        for index, seg in enumerate(srt_rows_from_segments(segments), start=1):
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


def _normalize_word(word: dict[str, Any]) -> Optional[dict[str, Any]]:
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


def _words_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for seg in segments:
        raw_words = seg.get("words")
        if not isinstance(raw_words, list):
            continue
        for word in raw_words:
            if not isinstance(word, dict):
                continue
            normalized = _normalize_word(word)
            if normalized is not None:
                words.append(normalized)
    return words


def _join_word_texts(words: list[dict[str, Any]]) -> str:
    return "".join(str(word["text"]) for word in words).strip()


def srt_rows_from_segments(
    segments: list[dict[str, Any]],
    *,
    max_words_per_caption: int = 3,
    max_gap_seconds: float = 0.5,
) -> list[dict[str, Any]]:
    words = _words_from_segments(segments)
    if not words:
        rows: list[dict[str, Any]] = []
        for seg in segments:
            try:
                start = float(seg["start"])
                end = float(seg["end"])
            except (KeyError, TypeError, ValueError):
                continue
            text = str(seg.get("text", "")).strip()
            if end <= start or not text:
                continue
            rows.append({"start": start, "end": end, "text": text})
        return rows

    rows: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    for word in words:
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


def write_manifest(
    manifest_path: Path,
    input_path: Path,
    outdir: Path,
    repo_root: Path,
    engine: str,
    model_name: str,
    task: str,
    language: Optional[str],
    source_url: Optional[str],
    engine_version: Optional[str],
) -> None:
    manifest = {
        "input_path": repo_relative(input_path, repo_root),
        "outdir": repo_relative(outdir, repo_root),
        "engine": engine,
        "model": model_name,
        "task": task,
        "language": language,
        "source_url": source_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool_versions": {
            "python": platform.python_version(),
            engine: engine_version,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_cli(
    argv: Optional[list[str]],
    *,
    engine: str,
    default_model: str,
    description: str,
    transcribe_one: TranscribeOneFn,
    engine_version_fn: Callable[[], Optional[str]],
) -> int:
    """Shared main() body for every bin/transcribe_media_<engine>.py script.

    `transcribe_one(audio_path, *, model_name, language, task) -> dict` does
    the engine-specific work for one whole file or one chunk; this function
    handles arg parsing, chunking, and writing every output format the same
    way regardless of which engine produced the segments.
    """
    parser = build_arg_parser(default_model=default_model, description=description)
    args = parser.parse_args(argv)

    try:
        repo_root = detect_repo_root()
    except Exception as err:
        print(f"Failed to detect repo root: {err}", file=sys.stderr)
        return 1

    input_path = (
        Path(args.input_media_path).expanduser().resolve()
        if Path(args.input_media_path).expanduser().is_absolute()
        else (repo_root / Path(args.input_media_path).expanduser()).resolve()
    )
    if not input_path.exists() or not input_path.is_file():
        print(f"Input media path does not exist or is not a file: {input_path}", file=sys.stderr)
        return 1

    outdir = (
        (Path(args.outdir).expanduser().resolve() if Path(args.outdir).expanduser().is_absolute() else (repo_root / Path(args.outdir).expanduser()).resolve())
        if args.outdir
        else input_path.parent
    )
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"repo_root={repo_root}")
    print(f"input_path={input_path}")
    print(f"outdir={outdir}")
    print(f"engine={engine} model={args.model}")

    try:
        ensure_ffmpeg_available()
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 2

    source_url: Optional[str]
    if args.source_url:
        source_url = args.source_url
    elif args.no_metadata:
        source_url = None
    else:
        source_url = resolve_source_url(input_path, args.jsonl)

    stem = input_path.stem
    existing_json = outdir / f"{stem}.whisper.json"
    if existing_json.is_file():
        print(
            f"Reusing existing transcription: {existing_json} "
            "(skipping re-run; delete this file to force a fresh transcribe)",
            file=sys.stderr,
        )
        result = json.loads(existing_json.read_text(encoding="utf-8"))
    else:
        result = run_chunked_transcription(
            input_path,
            args.chunk_seconds,
            transcribe_one,
            model_name=args.model,
            language=args.language,
            task=args.task,
        )

    if args.json:
        existing_json.write_text(
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
        repo_root=repo_root,
        engine=engine,
        model_name=args.model,
        task=args.task,
        language=args.language,
        source_url=source_url,
        engine_version=engine_version_fn(),
    )
    return 0
