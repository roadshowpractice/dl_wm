"""Compare transcripts against each other to surface reused/scripted language.

Several angles, all stdlib-only (difflib):
- verbatim runs: contiguous word sequences repeated exactly across two transcripts
  (catches word-for-word script reuse).
- fuzzy sentence matches: sentence pairs that are similar but not identical
  (catches paraphrased retellings of the same material).
- timed verbatim runs: the same verbatim-run detection, but anchored to Whisper
  word-level timestamps from each video, so matches can be compared by *when*
  they occur in each video and by the time-offset between them. A near-constant
  offset across many matches suggests both videos are locked to the same
  underlying timeline/event (e.g. a re-clip, or a second recording of the same
  delivery) -- it does not by itself prove they come from the same video file.
  Scattered, inconsistent offsets suggest independently delivered performances
  of similar material.
- metadata comparison: uploader/date/duration/engagement-count diffs from the
  two videos' dl_wm metadata JSON, since "same event" claims should be checked
  against upload metadata too, not just transcript text.
"""

from __future__ import annotations

import difflib
import re
import statistics

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def tokenize_words(text: str) -> list[str]:
    """Lowercase word tokens, punctuation stripped."""
    return _WORD_RE.findall(text.lower())


def split_sentences(text: str) -> list[str]:
    """Naive sentence split; good enough for Whisper's punctuated output."""
    sentences = _SENTENCE_SPLIT_RE.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


def find_verbatim_runs(
    text_a: str, text_b: str, min_words: int = 6
) -> list[dict]:
    """Return contiguous word runs shared verbatim between two texts, longest first."""
    tokens_a = tokenize_words(text_a)
    tokens_b = tokenize_words(text_b)

    matcher = difflib.SequenceMatcher(None, tokens_a, tokens_b, autojunk=False)
    runs = []
    for block in matcher.get_matching_blocks():
        if block.size < min_words:
            continue
        run_tokens = tokens_a[block.a : block.a + block.size]
        runs.append(
            {
                "a_start_word": block.a,
                "b_start_word": block.b,
                "word_count": block.size,
                "text": " ".join(run_tokens),
            }
        )

    runs.sort(key=lambda r: r["word_count"], reverse=True)
    return runs


def words_with_timestamps_from_whisper(whisper_data: dict) -> list[dict]:
    """Flatten a Whisper JSON's segments into a word-level [{text, start, end}, ...] list.

    Returns an empty list if the transcript wasn't run with word-level timestamps.
    """
    words: list[dict] = []
    for seg in whisper_data.get("segments", []):
        for word in seg.get("words", []):
            try:
                start = float(word["start"])
                end = float(word["end"])
            except (KeyError, TypeError, ValueError):
                continue
            tokens = _WORD_RE.findall(str(word.get("word", "")).lower())
            if not tokens:
                continue
            # a whisper "word" is usually one token; if punctuation splits it into
            # several, spread them evenly across the word's time span
            span = (end - start) / len(tokens)
            for i, token in enumerate(tokens):
                words.append(
                    {
                        "text": token,
                        "start": round(start + i * span, 3),
                        "end": round(start + (i + 1) * span, 3),
                    }
                )
    return words


def format_hhmmss(seconds: float) -> str:
    """Render seconds as H:MM:SS (or M:SS under an hour)."""
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def find_verbatim_runs_timed(
    words_a: list[dict], words_b: list[dict], min_words: int = 6
) -> list[dict]:
    """Like find_verbatim_runs, but anchored to word-level timestamps in both videos."""
    tokens_a = [w["text"] for w in words_a]
    tokens_b = [w["text"] for w in words_b]

    matcher = difflib.SequenceMatcher(None, tokens_a, tokens_b, autojunk=False)
    runs = []
    for block in matcher.get_matching_blocks():
        if block.size < min_words:
            continue
        a_words = words_a[block.a : block.a + block.size]
        b_words = words_b[block.b : block.b + block.size]
        a_start, a_end = a_words[0]["start"], a_words[-1]["end"]
        b_start, b_end = b_words[0]["start"], b_words[-1]["end"]
        runs.append(
            {
                "word_count": block.size,
                "text": " ".join(w["text"] for w in a_words),
                "a_start": a_start,
                "a_end": a_end,
                "b_start": b_start,
                "b_end": b_end,
                "offset_seconds": round(b_start - a_start, 3),
            }
        )

    runs.sort(key=lambda r: r["word_count"], reverse=True)
    return runs


def analyze_time_offsets(timed_runs: list[dict]) -> dict:
    """Summarize how consistent the a->b time offset is across timed verbatim runs.

    A tight, near-constant offset suggests both videos share one underlying
    timeline/event (e.g. a re-clip, or a second recording of the same
    delivery) -- not necessarily the same underlying video file. A wide
    spread suggests the matched material was delivered at unrelated points
    in time (e.g. separate performances of similar material).
    """
    if not timed_runs:
        return {"count": 0}

    offsets = [r["offset_seconds"] for r in timed_runs]
    result = {
        "count": len(offsets),
        "mean_offset_seconds": round(statistics.mean(offsets), 2),
        "median_offset_seconds": round(statistics.median(offsets), 2),
        "min_offset_seconds": round(min(offsets), 2),
        "max_offset_seconds": round(max(offsets), 2),
        "stdev_offset_seconds": round(statistics.pstdev(offsets), 2) if len(offsets) > 1 else 0.0,
    }
    # Low spread relative to the run count => matches line up on one shared
    # timeline; anything else is left for a human to judge from the per-run list.
    result["consistent_timeline"] = result["stdev_offset_seconds"] <= 5.0
    return result


def compare_metadata(meta_a: dict, meta_b: dict) -> dict:
    """Side-by-side diff of the fields relevant to a 'same event?' question."""
    fields = [
        "video_title",
        "uploader",
        "video_date",
        "duration",
        "resolution",
        "view_count",
        "like_count",
        "comment_count",
        "url",
    ]
    comparison = {}
    for field in fields:
        val_a = meta_a.get(field)
        val_b = meta_b.get(field)
        comparison[field] = {"a": val_a, "b": val_b, "same": val_a == val_b}

    duration_a = meta_a.get("duration")
    duration_b = meta_b.get("duration")
    if isinstance(duration_a, (int, float)) and isinstance(duration_b, (int, float)):
        comparison["duration_diff_seconds"] = round(duration_b - duration_a, 2)

    return comparison


def find_fuzzy_sentence_matches(
    text_a: str,
    text_b: str,
    cutoff: float = 0.6,
    min_sentence_words: int = 4,
    max_matches_per_sentence: int = 1,
) -> list[dict]:
    """Return sentence pairs that are similar (not necessarily identical) between two texts."""
    sentences_a = [s for s in split_sentences(text_a) if len(s.split()) >= min_sentence_words]
    sentences_b = [s for s in split_sentences(text_b) if len(s.split()) >= min_sentence_words]

    matches = []
    for a_index, sent_a in enumerate(sentences_a):
        close = difflib.get_close_matches(
            sent_a, sentences_b, n=max_matches_per_sentence, cutoff=cutoff
        )
        for sent_b in close:
            ratio = difflib.SequenceMatcher(None, sent_a, sent_b).ratio()
            matches.append(
                {
                    "a_index": a_index,
                    "a_text": sent_a,
                    "b_text": sent_b,
                    "ratio": round(ratio, 3),
                }
            )

    matches.sort(key=lambda m: m["ratio"], reverse=True)
    return matches


def compare_transcripts(
    text_a: str,
    text_b: str,
    min_verbatim_words: int = 6,
    fuzzy_cutoff: float = 0.6,
    words_a: list[dict] | None = None,
    words_b: list[dict] | None = None,
    metadata_a: dict | None = None,
    metadata_b: dict | None = None,
) -> dict:
    """Run all comparison passes and return a combined report.

    words_a/words_b (from words_with_timestamps_from_whisper) enable the timed
    verbatim + timeline-offset passes; metadata_a/metadata_b (each video's dl_wm
    metadata JSON) enable the metadata diff. All are optional.
    """
    verbatim_runs = find_verbatim_runs(text_a, text_b, min_words=min_verbatim_words)
    fuzzy_matches = find_fuzzy_sentence_matches(text_a, text_b, cutoff=fuzzy_cutoff)
    report = {
        "verbatim_runs": verbatim_runs,
        "verbatim_word_total": sum(r["word_count"] for r in verbatim_runs),
        "fuzzy_sentence_matches": fuzzy_matches,
    }

    if words_a and words_b:
        timed_runs = find_verbatim_runs_timed(words_a, words_b, min_words=min_verbatim_words)
        report["timed_verbatim_runs"] = timed_runs
        report["time_offset_analysis"] = analyze_time_offsets(timed_runs)

    if metadata_a and metadata_b:
        report["metadata_comparison"] = compare_metadata(metadata_a, metadata_b)

    return report


def format_report_text(report: dict, label_a: str, label_b: str) -> str:
    """Render a compare_transcripts() report as human-readable text."""
    lines = [f"Comparison: {label_a}  <->  {label_b}", ""]

    if "metadata_comparison" in report:
        lines.append("=== Metadata ===")
        meta = report["metadata_comparison"]
        for field, values in meta.items():
            if field == "duration_diff_seconds":
                continue
            marker = "" if values["same"] else "  <-- differs"
            lines.append(f"{field}: {values['a']!r} vs {values['b']!r}{marker}")
        if "duration_diff_seconds" in meta:
            lines.append(f"duration_diff_seconds: {meta['duration_diff_seconds']}")
        lines.append("")

    if "time_offset_analysis" in report:
        lines.append("=== Timeline offset analysis (verbatim runs, timestamped) ===")
        analysis = report["time_offset_analysis"]
        if analysis.get("count"):
            lines.append(
                f"{analysis['count']} timed runs; offset (b_start - a_start) "
                f"mean={analysis['mean_offset_seconds']}s median={analysis['median_offset_seconds']}s "
                f"stdev={analysis['stdev_offset_seconds']}s range=[{analysis['min_offset_seconds']}, "
                f"{analysis['max_offset_seconds']}]"
            )
            verdict = (
                "consistent single timeline (likely the same event, e.g. a re-clip or a second "
                "recording of the same delivery)"
                if analysis["consistent_timeline"]
                else "inconsistent timeline (likely separate performances/deliveries)"
            )
            lines.append(f"verdict: {verdict}")
            lines.append("")
            lines.append("per-run timestamps (a @ time -> b @ time, offset):")
            for run in report.get("timed_verbatim_runs", []):
                lines.append(
                    f"  [{run['word_count']}w] {format_hhmmss(run['a_start'])} -> "
                    f"{format_hhmmss(run['b_start'])}  (offset {run['offset_seconds']}s)  "
                    f"\"{run['text'][:80]}\""
                )
        else:
            lines.append("(no timed verbatim runs)")
        lines.append("")

    lines.append(f"=== Verbatim runs (total {report['verbatim_word_total']} words) ===")
    if not report["verbatim_runs"]:
        lines.append("(none)")
    for run in report["verbatim_runs"]:
        lines.append(f"[{run['word_count']} words] \"{run['text']}\"")
    lines.append("")

    lines.append("=== Fuzzy sentence matches ===")
    if not report["fuzzy_sentence_matches"]:
        lines.append("(none)")
    for match in report["fuzzy_sentence_matches"]:
        lines.append(f"ratio={match['ratio']}")
        lines.append(f"  {label_a}: {match['a_text']}")
        lines.append(f"  {label_b}: {match['b_text']}")
    lines.append("")

    return "\n".join(lines)
