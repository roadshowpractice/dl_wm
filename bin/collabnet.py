#!/usr/bin/env python3
"""collabnet — walk an Instagram collaborator network, one account after the next.

Not the dl_wm per-link pipeline (call_router / dllink). This one works on whole
accounts, metadata only, nothing downloaded. For each account in a queue file:

  1. scrape     its post history with igp.profile_history (as the conf default login), slowly,
                into outputs/ig_timelines/<account>_<date>/  (skipped if we already
                have a full scrape of it; --refresh scrapes again)
  2. word sort  bin/ig_word_sort.py on it -> <run>/word_sorts/<account>_word_sort.txt
then pauses a short jittered moment (--gap) before the next account. The per-scroll
--pause is what paces the requests; the boundary pause is deliberately small (--sweep
uses 15-90 s, not the old 3-6 min).

When the whole queue is done (not after each account), it draws ONE graph:
  bin/ig_collab_graph.py for the queue's accounts and everyone they co-post with
  -> <run>/graph/ (png, html, edges.tsv, nodes.tsv, plus a dated copy in graph/history/).
  A run stopped with Ctrl-C draws no graph; the run that finishes the queue does.

Accounts that stop at the scroll cap (--rounds) are logged as CAPPED and written to
capped_<queue name>.txt next to the queue file, with the re-scrape command at its top.

--snowball: collaborators found on each account's posts are written to a separate
snowball_<queue>.txt next to the queue file, not appended to this run's queue. The
current run finishes the queue it was given; the snowball file is a to-do list for a
later run (deduped against the queue, that file, and existing captures).
Don't snowball for group-membership questions: membership is a direct co-post (depth one);
a partner's partner is association, not membership. See ~/glossary.md "boner depth one" (John, 2026-10-24).

Queue file: one account per line, anything after # is a comment.
Run folder: ~/Desktop/claude/<today>/collabnet_<queue name>/
    run_<time>.log    everything printed
    status.tsv        one line per account: account, step results, posts, finished_at
    word_sorts/  graph/
Ctrl-C stops cleanly; the same command again carries on (scraped accounts are skipped).

Usage:
    python bin/collabnet.py QUEUE.txt [--sweep | --deep] [--snowball] [--max-accounts 25]
        [--gap MIN MAX] [--pause MIN MAX] [--rounds N] [--max-hours H]
        [--snowball-top N] [--cookies conf/instagram.cookies.haddamgoel.txt] [--refresh] [--dry-run]

    --sweep           wide pass: --rounds 50, ~1 min account boundary (use this; ~600
                      posts/account is enough for the co-post graph, and prolific accounts
                      CAPPED at 150 rounds anyway)
    --deep            full re-scrape: --refresh --rounds 600, safe 3-6 min boundary
    --gap MIN MAX     minutes paused between accounts (default 3 6; --sweep 0.25 1.5)
    --pause MIN MAX   seconds between scrolls within an account (default 3 6)
    --max-hours H     stop gracefully after H hours and still draw the graph
    --max-accounts 0  no per-run cap (for a supervised, always-on run)
    --snowball-top N  queue at most N new collaborators per account (default 15; 0 = all)
    --snowball-min N  only queue collaborators seen on at least N posts (default 1)
    --snowball-queue F  where snowballed accounts go (default snowball_<queue stem>.txt)
    --stop-after-empty N  stop after N empty/blocked accounts in a row (default 5)

The per-scroll --pause is the request rate limit. The account boundary is only a short
jittered pause, not a second rate limit: the old 3-6 s pause *and* 3-6 min boundary meant
a quarter of every cycle was idle sleep that bought nothing. After two accounts in a row
come back empty the whole interval widens automatically (rate limiting, per 2026-11-18),
and each such account is re-queued once for a later pass.
"""
import argparse
import asyncio
import importlib.util
import json
import random
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TIMELINES = REPO / "outputs" / "ig_timelines"
sys.path.insert(0, str(REPO))

LINE_RE = re.compile(r"^\s*([A-Za-z0-9._]+)\s*(?:#.*)?$")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "bin" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


from lib.drive_check import OutputsDriveError, assert_outputs_writable

word_sort = _load("ig_word_sort")
collab_graph = _load("ig_collab_graph")


# ---------- queue ----------

def read_queue(path):
    """Accounts in file order, lower-cased, without duplicates."""
    seen, out = set(), []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(line)
        if m and m.group(1).lower() not in seen:
            seen.add(m.group(1).lower())
            out.append(m.group(1).lower())
    return out


def existing_capture(account, root=TIMELINES):
    """Newest non-empty full scrape of this account, or None.

    Only <account>_<date>/ timelines and forensic captures count. The old flat
    <account>.jsonl files are partial (some are logged-out latest-12 checks), so
    they don't stop a fresh scrape."""
    candidates = list(root.glob(f"{account}_*/{account}_timeline.jsonl"))
    candidates += list(root.glob(f"{account}_*_forensic*/posts.jsonl"))
    candidates = [p for p in candidates if p.stat().st_size > 0]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def collaborators_of(timeline_path, account):
    """{collaborator: posts} across one account's scrape, the account itself excluded."""
    counts = {}
    with open(timeline_path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                for c in json.loads(line).get("collaborators") or []:
                    c = c.lower()
                    if c != account:
                        counts[c] = counts.get(c, 0) + 1
    return counts


def pick_new(counts, have, min_posts=1, top=0):
    """Collaborators worth queueing: unknown, seen on >= min_posts, top N by co-post count."""
    new = {a: c for a, c in counts.items() if a not in have and c >= min_posts}
    if top and len(new) > top:
        new = dict(sorted(new.items(), key=lambda kv: -kv[1])[:top])
    return new


def snowball_path(queue_path):
    """snowball_<queue>.txt next to the queue, so snowballed accounts are done later."""
    base = queue_path.stem.removeprefix("snowball_")
    return queue_path.with_name(f"snowball_{base}.txt")


def append_to_queue(path, new, source, header=None):
    empty = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8") as fh:
        if header and empty:
            fh.write(header)
        for acct, n in sorted(new.items(), key=lambda kv: -kv[1]):
            fh.write(f"{acct:<30}# from {source}, {n} posts\n")


# ---------- steps ----------

def step_scrape(account, cookies, rounds, pause, outdir):
    import igp.profile_history as ph
    found = asyncio.run(ph.scrape(account, Path(cookies), max_rounds=rounds, pause=tuple(pause)))
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{account}_timeline.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for rec in sorted(found.values(), key=lambda r: (r["taken_at"] or 0)):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out, len(found), ph.LAST_END


def step_word_sort(account, timeline, run_dir, top=40):
    dest = run_dir / "word_sorts" / f"{account}_word_sort.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(word_sort.render(account, timeline, word_sort.load_posts(timeline), top) + "\n", encoding="utf-8")
    return dest


def step_graph(queue, run_dir):
    """Links touching any queue account (so the graph shows the queue plus its partners)."""
    return collab_graph.main(["--touching", ",".join(queue), "--out", str(run_dir / "graph")])


def write_capped(capped, queue_path, rounds, log):
    """Accounts that hit the scroll cap -> capped_<queue>.txt next to the queue file, ready to re-run.
    Appends (a re-run may cap more); accounts already listed aren't repeated."""
    if not capped:
        return
    out = queue_path.with_name(f"capped_{queue_path.stem}.txt")
    have = set(read_queue(out)) if out.exists() else set()
    new = [(a, n) for a, n in capped if a not in have]
    if not new:
        return
    with open(out, "a", encoding="utf-8") as fh:
        if not have:
            fh.write(f"# Accounts from {queue_path.name} whose scrape stopped at --rounds {rounds} (older posts\n"
                     f"# NOT reached). Re-scrape with:\n"
                     f"#   collabnet {out} --deep\n")
        for a, n in new:
            fh.write(f"{a:<30}# {n} posts at the cap, {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    log(f"{len(new)} capped account(s) listed for re-scrape -> {out}")


class Pacer:
    """The run's single rate budget.

    The per-scroll pause is the rate limit; the account boundary is a short jittered
    pause. Two empty/blocked accounts in a row widen the whole interval (that pattern
    was rate limiting on 2026-11-18, not missing data); successes walk it back down.
    """

    def __init__(self, pause, gap, ceiling=4.0):
        self.pause = tuple(pause)
        self.gap = tuple(gap)
        self.ceiling = ceiling
        self.scale = 1.0
        self.empty_streak = 0

    def round_pause(self):
        return tuple(min(60.0, p * self.scale) for p in self.pause)

    def account_wait(self):
        if self.gap[1] <= 0:
            return 0.0
        return random.uniform(*self.gap) * 60 * self.scale

    def note(self, status):
        if status in ("empty", "blocked"):
            self.empty_streak += 1
            if self.empty_streak >= 2:
                self.scale = min(self.ceiling, self.scale * 1.5)
        else:
            self.empty_streak = 0
            self.scale = max(1.0, self.scale * 0.9)
        return self.scale


def sleep_with_deadline(seconds, deadline=None):
    """Sleep in slices, watching --max-hours. False if the deadline passed first."""
    end = time.monotonic() + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        slice_ = min(left, 10.0)
        if deadline is not None:
            slice_ = min(slice_, deadline - time.monotonic())
        if slice_ > 0:
            time.sleep(slice_)


class Log:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")
        self.path = path

    def __call__(self, msg):
        line = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("queue")
    ap.add_argument("--cookies", default=str(REPO / "conf" / "instagram.cookies.haddamgoel.txt"))   # 2026-11-06: daystrom does not see timballard89
    ap.add_argument("--rounds", type=int, default=None, help="max scroll rounds per account (default 150; 50 with --sweep; 600 with --deep)")
    ap.add_argument("--gap", type=float, nargs=2, default=None, metavar=("MIN", "MAX"), help="minutes between accounts (default 3 6; 0.25 1.5 with --sweep)")
    ap.add_argument("--pause", type=float, nargs=2, default=None, metavar=("MIN", "MAX"), help="seconds between scrolls (default 3 6)")
    ap.add_argument("--sweep", action="store_true", help="wide pass: --rounds 50 and a ~1 min account boundary")
    ap.add_argument("--deep", action="store_true", help="full re-scrape: --refresh --rounds 600, safe pacing")
    ap.add_argument("--snowball", action="store_true", help="add newly found collaborators to the queue")
    ap.add_argument("--snowball-top", type=int, default=None, help="queue at most N new collaborators per account (default 15; 0 = all)")
    ap.add_argument("--snowball-min", type=int, default=1, help="only queue collaborators seen on at least N posts (default 1)")
    ap.add_argument("--snowball-queue", default=None, help="file for snowballed accounts (default snowball_<queue stem>.txt)")
    ap.add_argument("--max-accounts", type=int, default=25, help="scrape at most this many this run (0 = no cap; default 25)")
    ap.add_argument("--max-hours", type=float, default=None, help="stop gracefully after this many hours (draws the graph)")
    ap.add_argument("--stop-after-empty", type=int, default=5, help="stop after N empty/blocked accounts in a row (default 5)")
    ap.add_argument("--refresh", action="store_true", help="scrape accounts we already have")
    ap.add_argument("--dry-run", action="store_true", help="say what would happen, scrape nothing")
    args = ap.parse_args(argv)

    if args.sweep and args.deep:
        ap.error("--sweep and --deep are exclusive")
    rounds = args.rounds if args.rounds is not None else (50 if args.sweep else 600 if args.deep else 150)
    gap = args.gap if args.gap is not None else ([0.25, 1.5] if args.sweep else [3, 6])
    pause = args.pause if args.pause is not None else [3, 6]
    refresh = args.refresh or args.deep
    snowball_top = args.snowball_top if args.snowball_top is not None else 15
    pacer = Pacer(pause, gap)
    deadline = time.monotonic() + args.max_hours * 3600 if args.max_hours else None

    queue_path = Path(args.queue).resolve()
    sg_queue = Path(args.snowball_queue).resolve() if args.snowball_queue else snowball_path(queue_path)
    snowball_seen = set(read_queue(sg_queue)) if args.snowball and sg_queue.exists() else set()
    run_dir = Path.home() / "Desktop" / "claude" / date.today().isoformat() / f"collabnet_{queue_path.stem}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = Log(run_dir / f"run_{datetime.now().strftime('%H%M%S')}.log")
    log(f"collabnet  queue {queue_path}")
    log(f"  run folder {run_dir}")
    log(f"  cookies {args.cookies}  rounds {rounds}  gap {gap} min  pause {pause} s  "
        f"snowball {args.snowball}"
        + (f" -> {sg_queue.name} top {snowball_top}/min {args.snowball_min} posts"
           if args.snowball and snowball_top else "")
        + f"  max accounts {args.max_accounts or 'none'}"
        + (f"  max {args.max_hours:g}h" if args.max_hours else "")
        + f"{'  DRY RUN' if args.dry_run else ''}")

    # The scrapes are saved on the USB drive (outputs/ -> the vault USB). Prove it can be
    # written to before starting, and again before every account (drives drop out mid-run).
    def drive_ok():
        try:
            assert_outputs_writable()
            return True
        except OutputsDriveError as e:
            log(f"STOPPED, nothing more will be saved: {e}")
            return False

    if not args.dry_run and not drive_ok():
        return 2
    scraped, i = 0, 0
    capped = []  # (account, posts) that hit --rounds this run
    retried = {}  # account -> re-queued this run (kept small so a real empty can't loop)
    empty_streak = 0
    stop_reason = "queue finished"
    stop_now = False
    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                stop_reason = f"--max-hours {args.max_hours:g}"
                break
            queue = read_queue(queue_path)  # re-read each time: snowball grows it
            if i >= len(queue):
                break
            account = queue[i]
            i += 1
            tag = f"[{i}/{len(queue)}] {account}"
            timeline = existing_capture(account)
            if timeline and not refresh:
                status, n = "had", sum(1 for _ in open(timeline, encoding="utf-8"))
                log(f"{tag}: have it ({timeline.relative_to(REPO)}, {n} posts)")
            elif args.max_accounts and scraped >= args.max_accounts:
                stop_reason = f"--max-accounts {args.max_accounts}"
                break
            elif args.dry_run:
                log(f"{tag}: would scrape")
                continue
            else:
                if scraped:
                    wait = pacer.account_wait()
                    if wait:
                        log(f"    waiting {wait:.0f}s before {account}")
                        if not sleep_with_deadline(wait, deadline):
                            stop_reason = f"--max-hours {args.max_hours:g}"
                            break
                if not drive_ok():
                    return 2
                outdir = TIMELINES / f"{account}_{date.today().isoformat()}"
                log(f"{tag}: scraping -> {outdir.relative_to(REPO)}")
                try:
                    timeline, n, ended = step_scrape(account, args.cookies, rounds, pacer.round_pause(), outdir)
                    # "CAPPED" = stopped at --rounds before the oldest post: re-run with --deep
                    if not n:
                        status = "blocked" if ended == "logged_out" else "empty"
                    elif ended == "feed_end":
                        status = "complete"
                    elif ended == "max_rounds":
                        status = "CAPPED"
                    else:
                        status = ended
                except Exception as e:  # one bad account shouldn't stop the walk
                    timeline, n, status = None, 0, f"error: {e!r}"[:200]
                scraped += 1
                if status == "CAPPED":
                    capped.append((account, n))
                scale = pacer.note(status)
                if scale > 1.0:
                    log(f"    pacing widened to {scale:.2f}x (pause {pacer.round_pause()}) after "
                        f"{pacer.empty_streak} empty/blocked in a row")
                log(f"    {status}, {n} posts" + (f"  (hit --rounds {rounds}: older posts not reached; "
                                                     f"re-run with --deep)" if status == "CAPPED" else ""))
                if status in ("empty", "blocked"):
                    empty_streak += 1
                    if account not in retried:
                        retried[account] = True
                        with open(queue_path, "a", encoding="utf-8") as fh:
                            fh.write(f"{account:<30}# retry: {status}, {date.today().isoformat()}\n")
                        log("    re-queued at the end for one retry")
                    if args.stop_after_empty and empty_streak >= args.stop_after_empty:
                        stop_reason = f"{empty_streak} empty/blocked accounts in a row"
                        log(f"STOPPING: {stop_reason} (login may be rate-limited or walled)")
                        stop_now = True
                else:
                    empty_streak = 0

            ws = ""
            if timeline and n and not args.dry_run:
                ws = step_word_sort(account, timeline, run_dir)
                log(f"    word sort -> {ws.relative_to(run_dir)}")
                if args.snowball:
                    counts = collaborators_of(timeline, account)
                    known = set(queue) | snowball_seen | set(retried)
                    before = pick_new(counts, known, args.snowball_min)
                    new = pick_new(counts, known, args.snowball_min, snowball_top)
                    if len(new) < len(before):
                        log(f"    snowball cap: {len(before) - len(new)} lower-count collaborators not queued")
                    captured = {a for a in new if existing_capture(a)}
                    if captured:
                        new = {a: c for a, c in new.items() if a not in captured}
                        log(f"    snowball: {len(captured)} already captured, skipped")
                    if new:
                        header = (f"# Snowballed from {queue_path.name}; run later with:\n"
                                  f"#   python bin/collabnet.py {sg_queue} --sweep --snowball\n")
                        append_to_queue(sg_queue, new, account, header)
                        snowball_seen |= set(new)
                        log(f"    + {len(new)} new collaborators -> {sg_queue.name} (for a later run)")
            with open(run_dir / "status.tsv", "a", encoding="utf-8") as fh:
                fh.write(f"{account}\t{status}\t{n}\t{timeline or ''}\t{ws}\t"
                         f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
            if stop_now:
                break
    except KeyboardInterrupt:
        write_capped(capped, queue_path, rounds, log)
        log("stopped (Ctrl-C). Run the same command again to carry on.")
        return 130
    write_capped(capped, queue_path, rounds, log)
    # One graph per run, drawn only at the very end (John, 2026-10-04: no image after every account).
    if not args.dry_run:
        step_graph(read_queue(queue_path), run_dir)
        log(f"graph -> graph/collab_graph.png (+ dated copy in graph/history/)")
    log(f"finished ({stop_reason}): {scraped} scraped this run. "
        f"graph: {run_dir / 'graph' / 'collab_graph.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
