#!/usr/bin/env python3
"""Cursory look at a random sample of transcripts from a dllink --list run.

Picks N posts at random from the finished links of a run (FILE.urls.txt.done), finds each post's .srt in
outputs/, and writes one report: post facts (date, where we found it, why it ties, collaborators, uploader),
length, every caption line matching the search terms (with its timestamp), and the top words from
bin/srt_word_histogram.py (which also leaves its chart and word list next to the report).

    python bin/srt_sample_report.py --done LIST.urls.txt.done --tsv LIST.tsv -n 3
    python bin/srt_sample_report.py --done ... --tsv ... -n 3 --more      (3 more, never repeating earlier picks)

Search terms (default): friend/friends (any case), Backfire (any case), SRA (capitals only, so Spanish
"Sra." isn't counted). Change with --term, e.g. --term "(?i)\\bstake president\\b" (repeatable).
Output: ~/Desktop/claude/<today>/analysis/srt_sample/ (report_<time>.md, picks.txt, per-post word lists).
Written 2026-10-06.
"""
import argparse, csv, datetime, glob, json, random, re, subprocess, sys
from pathlib import Path

import pysrt

REPO = Path(__file__).resolve().parents[1]
DEFAULT_TERMS = [r"(?i)\bfriends?\b", r"(?i)backfire", r"\bSRA\b"]


def code_of(url):
    return url.rstrip("/").split("/")[-1]


def find_srts(code):
    return sorted(Path(p) for p in glob.glob(str(REPO / "outputs" / "*" / f"instagram__{code}*" / "*.srt")))


def uploader(code):
    p = REPO / "metadata" / f"instagram__{code}.json"
    try:
        return json.loads(p.read_text()).get("uploader") or "?"
    except Exception:
        return "?"


def top_words(srt, outdir, n=10):
    prefix = outdir / f"{srt.stem}"
    subprocess.run([sys.executable, str(REPO / "bin" / "srt_word_histogram.py"), str(srt), "-o", str(prefix), "-n", "20", "--es", "--pt"],
                   capture_output=True, text=True)
    counts = Path(f"{prefix}_word_counts.txt")
    if not counts.exists():
        return "(no words)"
    lines = counts.read_text().splitlines()[1:n + 1]
    return ", ".join(f"{l.split()[1]} {l.split()[0]}" for l in lines if len(l.split()) == 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--done", required=True, help="the run's FILE.urls.txt.done (links that finished ok)")
    ap.add_argument("--tsv", required=True, help="the list's .tsv from ig_tagged_posts.py (post facts)")
    ap.add_argument("-n", type=int, default=3)
    ap.add_argument("--more", action="store_true", help="skip posts already picked (picks.txt in --out)")
    ap.add_argument("--seed", type=int, help="fix the random pick (for repeat runs)")
    ap.add_argument("--codes", help="comma-separated shortcodes to report instead of a random pick")
    ap.add_argument("--term", action="append", help="search regex (repeatable); default friend / Backfire / SRA")
    ap.add_argument("--out", default=str(Path.home() / "Desktop/claude" / datetime.date.today().isoformat() / "analysis/srt_sample"))
    a = ap.parse_args()

    out = Path(a.out).expanduser(); out.mkdir(parents=True, exist_ok=True)
    picks_file = out / "picks.txt"
    already = set(picks_file.read_text().split()) if (a.more and picks_file.exists()) else set()
    facts = {r["shortcode"]: r for r in csv.DictReader(open(a.tsv, newline=""), delimiter="\t")}
    done = [code_of(u) for u in Path(a.done).read_text().split() if u.strip()]
    pool = [c for c in dict.fromkeys(done) if c not in already and find_srts(c)]
    if not pool:
        sys.exit("No finished posts with a transcript left to pick.")
    rng = random.Random(a.seed)
    picked = a.codes.split(",") if a.codes else rng.sample(pool, min(a.n, len(pool)))
    terms = [re.compile(t) for t in (a.term or DEFAULT_TERMS)]

    stamp = datetime.datetime.now().strftime("%H%M%S")
    rep = [f"# Transcript sample, {datetime.datetime.now():%Y-%m-%d %H:%M}",
           f"{len(picked)} picked at random from {len(pool)} finished posts with a transcript "
           f"({Path(a.done).name}). Seed: {a.seed if a.seed is not None else 'random'}.",
           "Search terms: " + " · ".join(f"`{t.pattern}`" for t in terms), ""]
    total_hits = 0
    for code in picked:
        f = facts.get(code, {})
        rep += [f"## {code}  ·  https://www.instagram.com/p/{code}/",
                f"- posted {f.get('posted','?')} · found in {f.get('found_in','?')} · ties by: {f.get('why','?')} · uploader: {uploader(code)}",
                f"- credited: {f.get('collaborators') or '(none listed)'}",
                f"- caption starts: {(f.get('caption_start') or '').strip()[:160]}"]
        for srt in find_srts(code):
            subs = pysrt.open(str(srt), encoding="utf-8")
            words = sum(len(s.text.split()) for s in subs)
            length = subs[-1].end.to_time().strftime("%H:%M:%S") if subs else "0"
            rep.append(f"- transcript `{srt.name}`: {len(subs)} captions, {words} words, length {length}")
            rep.append(f"- top words: {top_words(srt, out)}")
            hits = [(s.start, s.text.replace(chr(10), ' ')) for s in subs if any(t.search(s.text) for t in terms)]
            total_hits += len(hits)
            if hits:
                rep.append(f"- **{len(hits)} line(s) match:**")
                rep += [f"  - `{str(t).split(',')[0]}` {txt}" for t, txt in hits]
            else:
                rep.append("- no line matches the search terms")
        rep.append("")
    rep.append(f"Total matching lines: {total_hits}.")
    report = out / f"report_{stamp}.md"
    report.write_text("\n".join(rep) + "\n")
    if not a.codes:
      with open(picks_file, "a") as fh:
        fh.write("\n".join(picked) + "\n")
    print(report)


if __name__ == "__main__":
    main()
