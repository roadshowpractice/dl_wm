#!/usr/bin/env python3
"""Check every minute_chunks boundary for a mid-word cut.

Each edge_check clip is a 6s window [cut_time-3, cut_time+3] extracted
from the original source, so the real minute_chunks cut point always
falls at exactly t=3.0s within the edge clip's own (clip-relative) time.
Uses the word-level timestamps in each edge clip's .whisper.json (from
Whisper's word_timestamps mode) to check whether any spoken word's
[start, end] interval straddles that t=3.0s mark - if so, the actual
minute_chunks cut sliced that word in half.

Usage:
    python3 check_edge_cuts.py <edge_checks_dir>
"""
import json
import sys
from pathlib import Path

CUT_T = 3.0  # clip-relative second where the real boundary falls


def main(argv):
    edge_dir = Path(argv[0] if argv else
                     "/home/hogan/Documents/repos/dl_wm/outputs/2026-09-07/youtube__pBo_2DYxfrY/minute_chunks/_edge_checks")

    whisper_jsons = sorted(edge_dir.glob("edge_*.whisper.json"))
    print(f"checking {len(whisper_jsons)} boundaries\n")

    mid_word = []
    clean = []
    no_data = []

    for wj in whisper_jsons:
        label = wj.stem.replace(".whisper", "")
        data = json.loads(wj.read_text(encoding="utf-8"))

        words = []
        for seg in data.get("segments", []):
            words.extend(seg.get("words", []))

        if not words:
            no_data.append(label)
            continue

        straddler = None
        prev_word = None
        next_word = None
        for w in words:
            ws, we = w.get("start"), w.get("end")
            if ws is None or we is None:
                continue
            if ws < CUT_T < we:
                straddler = w
            if we <= CUT_T and (prev_word is None or we > prev_word.get("end", -1)):
                prev_word = w
            if ws >= CUT_T and next_word is None:
                next_word = w

        if straddler:
            mid_word.append((label, straddler, prev_word, next_word))
        else:
            clean.append((label, prev_word, next_word))

    print(f"=== MID-WORD CUTS: {len(mid_word)} ===")
    for label, w, prev_w, next_w in mid_word:
        prev_txt = prev_w["word"].strip() if prev_w else "?"
        next_txt = next_w["word"].strip() if next_w else "?"
        print(f"  {label}: cut through \"{w['word'].strip()}\" "
              f"({w['start']:.2f}-{w['end']:.2f}s)  context: ...{prev_txt} [{w['word'].strip()}] {next_txt}...")

    print(f"\n=== CLEAN (gap/pause at the cut): {len(clean)} ===")
    tight = []
    for label, prev_w, next_w in clean:
        gap = None
        if prev_w and next_w:
            gap = next_w["start"] - prev_w["end"]
        if gap is not None and gap < 0.15:
            tight.append((label, prev_w, next_w, gap))
    print(f"  ({len(tight)} of these have a gap under 0.15s - worth a second look)")
    for label, prev_w, next_w, gap in tight:
        print(f"  {label}: gap {gap:.3f}s between \"{prev_w['word'].strip()}\" and \"{next_w['word'].strip()}\"")

    if no_data:
        print(f"\n=== NO WORD DATA (silence / no speech detected): {len(no_data)} ===")
        for label in no_data:
            print(f"  {label}")

    print(f"\nTOTAL: {len(mid_word)} mid-word, {len(tight)} tight-but-clean, "
          f"{len(clean) - len(tight)} clearly clean, {len(no_data)} no-speech")


if __name__ == "__main__":
    main(sys.argv[1:])
