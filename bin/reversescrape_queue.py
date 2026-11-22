#!/usr/bin/env python3
"""reversescrape_queue — run bin/reversescrape.py over a list of accounts, back to back,
without re-deriving the "quarter of every cycle is idle sleep" mistake collabnet.py already
paid for on 2026-11-18 (see its docstring / Pacer class, which this reuses as-is).

Why this exists: reversescrape.py already paces itself (--pause, default 3-7 s between
every request, up to --max-requests per account) against the single IG identity in
conf/instagram.cookies.haddamgoel.txt. A FLAT extra "wait 1-2 min between accounts" on top
of that is a second, redundant rate limit — the exact anti-pattern collabnet.py's Pacer
was built to replace with a short jittered boundary pause that only widens after
consecutive empty/blocked accounts and narrows back down after successes.

This also takes the per-account bookkeeping (meeting-date lookup already done once by
read_meeting_points(), command construction, stop-condition checks, status log) out of an
LLM reasoning loop and makes it one deterministic pass. The LLM is only needed to read the
final report and to handle anything this script can't classify (it will say so and stop).

Does NOT touch reversescrape.py's own internal pacing. Does NOT run two accounts' scrapes
concurrently — there is one IG identity; concurrent requests on it is the one thing that
would look MORE like a bot, not less. One subprocess at a time, always.

Usage:
    python bin/reversescrape_queue.py MEETING_POINTS.tsv \\
        --cookies conf/instagram.cookies.haddamgoel.txt --out-dir OUTDIR \\
        [--gap MIN MAX] [--stop-after-empty N] [--dry-run] [--resume-from ACCOUNT]

MEETING_POINTS.tsv: tab-separated, header row, columns account / meeting_date (first two
columns used; extra columns ignored). This is exactly perl's existing
meet_in_middle_output/meeting_points.tsv — not regenerated here.

Per account:
  1. cd to the dl_wm repo, run:
     python bin/reversescrape.py ACCOUNT --until MEETING_DATE --cookies COOKIES --no-fresh
     (never --stale-ok: a stale cookie is a hard stop for the whole queue, checked once
     up front, same as the job's "do not use --stale-ok" rule)
  2. classify the result from summary.json / run.log:
       ok       - posts written, walk reached --until or ran out of posts naturally
       empty    - 0 posts, not a cookie/login problem (account has nothing to find)
       blocked  - "I NEED COOKIES" / login wall / checkpoint text in the log
       stale    - cookie_candidates() refused every cookie file (should only happen at
                  the very first account; treated as a hard stop, not counted toward
                  the empty streak)
  3. feed the status into the SAME Pacer class collabnet.py uses: short jittered wait by
     default, doubles on two blocked/empty in a row (capped), halves back down on success.
     A "blocked" status (not "empty") stops the whole queue immediately — it's the one
     signal that means stop, don't lean on the backoff.
  4. on success: merge the new oldest-end posts with the existing newest-end jsonl
     (dedup by shortcode) into outputs/ig_timelines/<account>_<date>_meet/, write the gap
     check, append one line to status.tsv, and copy the account's run.log + summary.json
     into --out-dir immediately (so partial progress is visible without waiting for all
     21; nothing is batched to the end).

Stop conditions (hard, no retry):
  - cookie stale at the first check (nothing runs)
  - "blocked" status (login wall / checkpoint) on ANY account
  - --stop-after-empty consecutive empty/blocked accounts (default 5, matches the job)
Ctrl-C is safe: status.tsv + merged output already written are kept; re-run the same
command and it skips accounts whose _meet folder already exists, same as collabnet.py
skipping already-scraped accounts.
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

# Reuse collabnet's pacer/backoff logic verbatim instead of re-deriving it.
import importlib.util
_spec = importlib.util.spec_from_file_location("collabnet", REPO / "bin" / "collabnet.py")
_collabnet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_collabnet)
Pacer = _collabnet.Pacer
Log = _collabnet.Log


def read_meeting_points(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if not row or row[0].lower().startswith("account"):
                continue
            if len(row) < 2 or not row[0].strip():
                continue
            rows.append((row[0].strip(), row[1].strip()))
    return rows


def cookie_is_stale(cookies_path, stale_hours=12):
    """Mirrors reversescrape.py's own STALE_HOURS check, so the queue fails fast
    instead of discovering it one subprocess call in. Does not read cookie values."""
    p = Path(cookies_path)
    if not p.exists():
        return True, "missing"
    age_h = (time.time() - p.stat().st_mtime) / 3600
    return age_h > stale_hours, f"{age_h:.0f} h old"


def classify(run_log_text, summary):
    text = run_log_text.lower()
    if "i need cookies" in text or "skipping" in text and "stale" in text:
        return "stale"
    if "checkpoint" in text or "login wall" in text or "challenge_required" in text:
        return "blocked"
    posts = (summary or {}).get("posts", 0)
    if posts == 0:
        return "empty"
    return "ok"


def merge_and_gap_check(account, meeting_date, newest_end_jsonl, oldest_end_jsonl, out_dir):
    """Dedup-merge by shortcode into a NEW dated folder; never edit the sources."""
    def load(path):
        recs = {}
        if not path or not Path(path).exists():
            return recs
        # NOT .splitlines(): found 2026-11-21 that it over-splits on Unicode line/paragraph
        # separators (U+2028/U+2029) that are legal, unescaped characters inside a JSON
        # string (a caption), breaking one record into two unparsable fragments and crashing
        # the whole queue on an uncaught JSONDecodeError (jamiledavies's newest-end file, one
        # bad caption out of 600 lines). split("\n") only splits on the real line terminator.
        for line in Path(path).read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"    WARN: skipping unparsable line in {path.name}: {e}")
                continue
            sc = rec.get("shortcode") or rec.get("code")
            if sc:
                recs[sc] = rec
        return recs

    newest = load(newest_end_jsonl)
    oldest = load(oldest_end_jsonl)
    merged = {**newest, **oldest}  # oldest-end wins on overlap (fresher walk direction)
    out_dir.mkdir(parents=True, exist_ok=True)
    merged_path = out_dir / f"{account}_timeline.jsonl"
    with open(merged_path, "w", encoding="utf-8") as fh:
        for rec in sorted(merged.values(), key=lambda r: r.get("taken_at") or 0):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    newest_oldest_date = None
    if newest:
        oldest_rec = min(newest.values(), key=lambda r: r.get("taken_at") or 0)
        newest_oldest_date = oldest_rec.get("taken_at")
    oldest_newest_date = None
    if oldest:
        newest_rec = max(oldest.values(), key=lambda r: r.get("taken_at") or 0)
        oldest_newest_date = newest_rec.get("taken_at")

    overlap = bool(set(newest) & set(oldest))
    gap_closed = bool(
        oldest_newest_date and newest_oldest_date and oldest_newest_date >= newest_oldest_date
    ) or overlap

    return {
        "merged_path": str(merged_path),
        "merged_posts": len(merged),
        "overlap": overlap,
        "gap_closed": gap_closed,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("meeting_points_tsv")
    ap.add_argument("--cookies", default=str(REPO / "conf" / "instagram.cookies.haddamgoel.txt"))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--gap", type=float, nargs=2, default=[0.5, 2.0], metavar=("MIN", "MAX"),
                     help="minutes between accounts, short + jittered, widens on backoff (default 0.5 2)")
    ap.add_argument("--stop-after-empty", type=int, default=5)
    ap.add_argument("--resume-from", default=None, help="skip accounts before this one in the list")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = Log(out_dir / f"queue_run_{datetime.now().strftime('%H%M%S')}.log")

    stale, why = cookie_is_stale(args.cookies)
    if stale:
        log(f"STOPPED before any account: cookie {args.cookies} is stale ({why}); "
            f"not using --stale-ok, per the job's rule. Fix the cookie, don't widen this check.")
        return 2

    accounts = read_meeting_points(args.meeting_points_tsv)
    if args.resume_from:
        names = [a for a, _ in accounts]
        if args.resume_from in names:
            accounts = accounts[names.index(args.resume_from):]
    log(f"queue: {len(accounts)} account(s), cookie {why}, gap {args.gap} min (jittered, adaptive)")

    status_path = out_dir / "status.tsv"
    is_new = not status_path.exists()
    status_fh = open(status_path, "a", encoding="utf-8")
    if is_new:
        status_fh.write("account\tstatus\tposts\tgap_closed\tmerged_posts\tfinished_at\n")

    pacer = Pacer(pause=(0, 0), gap=args.gap)  # pause unused here; reversescrape paces its own requests
    empty_streak = 0
    for i, (account, meeting_date) in enumerate(accounts):
        meet_dir = REPO / "outputs" / "ig_timelines" / f"{account}_{datetime.now():%Y-%m-%d}_meet"
        existing_merge = list((REPO / "outputs" / "ig_timelines").glob(f"{account}_*_meet"))
        if existing_merge and not args.dry_run:
            log(f"[{i+1}/{len(accounts)}] {account}: already merged -> {existing_merge[0]}, skipping")
            continue

        cmd = [
            sys.executable, "bin/reversescrape.py", account,
            "--until", meeting_date, "--cookies", args.cookies, "--no-fresh",
        ]
        log(f"[{i+1}/{len(accounts)}] {account}: until {meeting_date}" + (" (dry-run)" if args.dry_run else ""))
        if args.dry_run:
            continue

        # Strip DISPLAY/XAUTHORITY: under some agent users these point at a display
        # the user can't authenticate to, which crashes headless chromium at new_page()
        # with TargetClosedError -- silently, with no summary.json (found 2026-11-20
        # retest: biakicis, perl's environment). Force true headless regardless of caller.
        env = {k: v for k, v in __import__("os").environ.items() if k not in ("DISPLAY", "XAUTHORITY")}
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
        run_log_text = proc.stdout + proc.stderr
        account_dir = sorted((REPO / "outputs" / "ig_timelines").glob(f"{account}_*_reverse*"),
                              key=lambda p: p.stat().st_mtime)[-1:] or [None]
        account_dir = account_dir[0]
        summary = {}
        if account_dir and (account_dir / "summary.json").exists():
            summary = json.loads((account_dir / "summary.json").read_text())

        # Always keep the raw subprocess output somewhere, even on a crash with no
        # summary.json at all -- this is what made the first crash take real digging
        # to diagnose (nothing on disk said more than "login 1/1").
        (out_dir / f"{account}_subprocess.log").write_text(
            f"exit code: {proc.returncode}\n--- stdout+stderr ---\n{run_log_text}"
        )

        if proc.returncode != 0 and not summary:
            status = "crash"
            log(f"  -> CRASH (exit {proc.returncode}, no summary.json -- "
                f"see {account}_subprocess.log, not counted as empty)")
        else:
            status = classify(run_log_text, summary)
            log(f"  -> {status} ({summary.get('posts', '?')} posts)")

        if account_dir:
            shutil.copy2(account_dir / "run.log", out_dir / f"{account}_run.log")
            if (account_dir / "summary.json").exists():
                shutil.copy2(account_dir / "summary.json", out_dir / f"{account}_summary.json")

        if status == "stale":
            log("STOPPED mid-queue: cookie went stale (checked once up front; something changed it "
                "mid-run, e.g. another process touching the same file). Not using --stale-ok.")
            status_fh.write(f"{account}\tstale\t0\tfalse\t0\t{datetime.now().isoformat()}\n")
            break
        if status == "blocked":
            log("STOPPED: login wall or checkpoint. This is the one signal that means stop, "
                "not back off and keep going.")
            status_fh.write(f"{account}\tblocked\t{summary.get('posts',0)}\tfalse\t0\t{datetime.now().isoformat()}\n")
            break

        gap_info = {"gap_closed": False, "merged_posts": 0}
        if status == "ok" and account_dir:
            newest_end = sorted((REPO / "outputs" / "ig_timelines").glob(f"{account}_2026-11-1*/{account}_timeline.jsonl"))
            newest_end = newest_end[-1] if newest_end else None
            oldest_end = account_dir / f"{account}_timeline.jsonl"
            # One account's merge should never take down the rest of the queue (it did once,
            # 2026-11-21: an uncaught JSONDecodeError on jamiledavies killed the whole process
            # with 6 accounts still unrun). A merge failure here is recorded as its own status
            # so it's visible, not silently skipped and not fatal to everything after it.
            try:
                gap_info = merge_and_gap_check(account, meeting_date, newest_end, oldest_end, meet_dir)
                log(f"  merged -> {gap_info['merged_path']} ({gap_info['merged_posts']} posts, "
                    f"gap_closed={gap_info['gap_closed']})")
            except Exception as e:
                log(f"  MERGE FAILED ({type(e).__name__}: {e}) -- scrape succeeded "
                    f"({summary.get('posts', '?')} posts) but is not merged; account_dir={account_dir}")
                status = "merge_failed"

        status_fh.write(f"{account}\t{status}\t{summary.get('posts', 0)}\t"
                         f"{gap_info['gap_closed']}\t{gap_info['merged_posts']}\t"
                         f"{datetime.now().isoformat()}\n")
        status_fh.flush()

        scale = pacer.note(status)
        empty_streak = empty_streak + 1 if status in ("empty", "blocked") else 0
        if empty_streak >= args.stop_after_empty:
            log(f"STOPPED: {empty_streak} empty/blocked accounts in a row (--stop-after-empty {args.stop_after_empty}).")
            break

        if i < len(accounts) - 1:
            wait = pacer.account_wait()
            log(f"  waiting {wait:.0f}s before next account (scale x{scale:.2f})")
            time.sleep(wait)

    status_fh.close()
    log("queue done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
