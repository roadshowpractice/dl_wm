#!/usr/bin/env python
"""Bundle video transcripts for comparison, with optional source articles for context.

For each --video, reuses an existing .whisper.json/.txt transcript sitting next to it
(as produced by the normal dl_wm download/caption pipeline) rather than re-running
Whisper; only falls back to transcribing if neither exists. When 2+ videos are given,
every pair of transcripts is run through lib/transcript_compare.py to surface verbatim
word runs and fuzzy sentence matches shared between them (e.g. detecting the same
scripted material reused across retellings), plus a timeline-offset analysis when
word-level timestamps are available. Comparison against article text is entirely
optional -- pass --url to also fetch and save article text alongside the transcripts
for manual reading; no cross-comparison is run against articles.

Each comparison pair gets a .json/.txt report and a self-contained .html report
(lib/compare_report_html.py) -- no network calls, open the .html directly in a
browser. Everything lands in --outdir alongside a manifest.json pointing at the
gathered files, all local.

Ported/generalized from a similar one-off script in the sibling `mimesis` repo.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from teton_utils import initialize_logging
from transcription_caller import run_transcription
from article_utils import save_article
from transcript_compare import (
    compare_transcripts,
    format_report_text,
    words_with_timestamps_from_whisper,
)
from compare_report_html import render_html_report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--video", action="append", default=[], help="Local video file to include (repeatable)"
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Optional article URL to fetch for context (repeatable); not compared against videos",
    )
    parser.add_argument(
        "--outdir",
        default=None,
        help="Output directory (default: outputs/compare/<UTC timestamp>)",
    )
    parser.add_argument(
        "--min-verbatim-words",
        type=int,
        default=6,
        help="Minimum word run length to report as verbatim reuse (default: 6)",
    )
    parser.add_argument(
        "--fuzzy-cutoff",
        type=float,
        default=0.6,
        help="Minimum difflib similarity ratio (0-1) to report a fuzzy sentence match (default: 0.6)",
    )
    parser.add_argument(
        "--no-compare",
        action="store_true",
        help="Skip pairwise transcript comparison even when 2+ videos are given",
    )
    return parser.parse_args(argv)


def load_metadata_for_video(video_path: Path) -> dict | None:
    """Look up this video's dl_wm metadata JSON by its {vendor}__{vendor_id} stem."""
    metadata_path = Path(root_dir) / "metadata" / f"{video_path.stem}.json"
    if not metadata_path.is_file():
        return None
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def gather_video_data(video_path: Path, logger) -> dict | None:
    """Return {"transcript": str, "words": list|None} for a video.

    Reuses an existing .whisper.json (which also carries word-level timestamps)
    or .txt transcript next to the video; only runs transcription as a fallback.
    """
    base = video_path.with_suffix("")
    whisper_json = base.with_suffix(".whisper.json")
    if whisper_json.exists():
        try:
            data = json.loads(whisper_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict):
            text = data.get("text")
            if isinstance(text, str) and text.strip():
                words = words_with_timestamps_from_whisper(data)
                return {"transcript": text.strip(), "words": words or None}

    txt_path = base.with_suffix(".txt")
    if txt_path.exists():
        return {"transcript": txt_path.read_text(encoding="utf-8").strip(), "words": None}

    logger.info("No existing transcript for %s; running transcription.", video_path)
    if not run_transcription(str(video_path), str(txt_path), "txt"):
        logger.error("Transcription failed for %s", video_path)
        return None
    if txt_path.exists():
        return {"transcript": txt_path.read_text(encoding="utf-8").strip(), "words": None}
    return None


def main(argv: list[str] | None = None) -> int:
    logger = initialize_logging()
    args = parse_args(argv)

    if not args.video and not args.url:
        logger.error("Provide at least one --video and/or --url to compare.")
        return 1

    outdir = (
        Path(args.outdir)
        if args.outdir
        else Path("outputs") / "compare" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    outdir.mkdir(parents=True, exist_ok=True)
    articles_dir = outdir / "articles"

    manifest: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "videos": [],
        "articles": [],
        "comparisons": [],
    }

    transcripts_by_stem: dict[str, str] = {}
    words_by_stem: dict[str, list] = {}
    metadata_by_stem: dict[str, dict] = {}

    for video_arg in args.video:
        video_path = Path(video_arg).expanduser().resolve()
        if not video_path.is_file():
            logger.error("Video not found, skipping: %s", video_path)
            continue

        video_data = gather_video_data(video_path, logger)
        if video_data is None:
            continue
        transcript = video_data["transcript"]

        transcript_out = outdir / f"{video_path.stem}.transcript.txt"
        transcript_out.write_text(transcript + "\n", encoding="utf-8")
        manifest["videos"].append({"source": str(video_path), "transcript": str(transcript_out)})
        transcripts_by_stem[video_path.stem] = transcript
        if video_data["words"]:
            words_by_stem[video_path.stem] = video_data["words"]

        metadata = load_metadata_for_video(video_path)
        if metadata:
            metadata_by_stem[video_path.stem] = metadata

        logger.info("Transcript ready: %s", transcript_out)

    if not args.no_compare and len(transcripts_by_stem) >= 2:
        compare_dir = outdir / "comparisons"
        for (stem_a, text_a), (stem_b, text_b) in itertools.combinations(
            transcripts_by_stem.items(), 2
        ):
            report = compare_transcripts(
                text_a,
                text_b,
                min_verbatim_words=args.min_verbatim_words,
                fuzzy_cutoff=args.fuzzy_cutoff,
                words_a=words_by_stem.get(stem_a),
                words_b=words_by_stem.get(stem_b),
                metadata_a=metadata_by_stem.get(stem_a),
                metadata_b=metadata_by_stem.get(stem_b),
            )
            compare_dir.mkdir(parents=True, exist_ok=True)
            base_name = f"{stem_a}__vs__{stem_b}"
            json_path = compare_dir / f"{base_name}.json"
            txt_path = compare_dir / f"{base_name}.txt"
            html_path = compare_dir / f"{base_name}.html"
            json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            txt_path.write_text(format_report_text(report, stem_a, stem_b), encoding="utf-8")
            html_path.write_text(render_html_report(report, stem_a, stem_b), encoding="utf-8")
            manifest["comparisons"].append(
                {
                    "a": stem_a,
                    "b": stem_b,
                    "verbatim_word_total": report["verbatim_word_total"],
                    "fuzzy_match_count": len(report["fuzzy_sentence_matches"]),
                    "time_offset_analysis": report.get("time_offset_analysis"),
                    "report_json": str(json_path),
                    "report_txt": str(txt_path),
                    "report_html": str(html_path),
                }
            )
            logger.info(
                "Compared %s vs %s: %d verbatim words, %d fuzzy sentence matches",
                stem_a,
                stem_b,
                report["verbatim_word_total"],
                len(report["fuzzy_sentence_matches"]),
            )

    for url in args.url:
        article_path = save_article(url, articles_dir)
        if article_path is None:
            logger.error("Failed to fetch/extract article: %s", url)
            continue
        manifest["articles"].append({"url": url, "text_file": str(article_path)})
        logger.info("Article saved: %s", article_path)

    manifest_path = outdir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Comparison bundle written to %s", outdir)
    print(outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
