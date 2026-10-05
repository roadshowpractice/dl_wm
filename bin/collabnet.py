#!/usr/bin/env python3
"""collabnet — walk an Instagram collaborator network, one account after the next.

Not the dl_wm per-link pipeline (call_router / dllink). This one works on whole
accounts, metadata only, nothing downloaded. For each account in a queue file:

  1. scrape     its post history with igp.profile_history (as haddamgoel), slowly,
                into outputs/ig_timelines/<account>_<date>/  (skipped if we already
                have a full scrape of it; --refresh scrapes again)
  2. word sort  bin/ig_word_sort.py on it -> <run>/word_sorts/<account>_word_sort.txt
then waits a random few minutes (--gap) before the next account.

When the whole queue is done (not after each account), it draws ONE graph:
  bin/ig_collab_graph.py for the queue's accounts and everyone they co-post with
  -> <run>/graph/ (png, html, edges.tsv, nodes.tsv, plus a dated copy in graph/history/).
  A run stopped with Ctrl-C draws no graph; the run that finishes the queue does.

Accounts that stop at the scroll cap (--rounds) are logged as CAPPED and written to
capped_<queue name>.txt next to the queue file, with the re-scrape command at its top.

--snowball: collaborators found on each account's posts that aren't in the queue yet
are appended to the queue file ("# from <account>, N posts") and walked too, until
--max-accounts scrapes have been done this run.

Queue file: one account per line, anything after # is a comment.
Run folder: ~/Desktop/claude/<today>/collabnet_<queue name>/
    run_<time>.log    everything printed
    status.tsv        one line per account: account, step results, posts, finished_at
    word_sorts/  graph/
Ctrl-C stops cleanly; the same command again carries on (scraped accounts are skipped).

Usage:
    python bin/collabnet.py QUEUE.txt [--snowball] [--max-accounts 25] [--gap 3 6] [--pause 3 6]
        [--rounds 150] [--cookies conf/instagram.cookies.haddamgoel.txt] [--refresh] [--dry-run]
    collabnet QUEUE.txt ...        (wrapper in ~/.local/bin: activates the env, mounts the USB drive)

    --gap MIN MAX     minutes between accounts (default 3 6)
    --pause MIN MAX   seconds between scrolls within an account (default 3 6)
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


def append_to_queue(queue_path, new, source):
    with open(queue_path, "a", encoding="utf-8") as fh:
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
                     f"#   collabnet {out} --refresh --rounds {rounds * 4}\n")
        for a, n in new:
            fh.write(f"{a:<30}# {n} posts at the cap, {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    log(f"{len(new)} capped account(s) listed for re-scrape -> {out}")


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
    ap.add_argument("--cookies", default=str(REPO / "conf" / "instagram.cookies.haddamgoel.txt"))
    ap.add_argument("--rounds", type=int, default=150, help="max scroll rounds per account (default 150)")
    ap.add_argument("--gap", type=float, nargs=2, default=[3, 6], metavar=("MIN", "MAX"))
    ap.add_argument("--pause", type=float, nargs=2, default=[3, 6], metavar=("MIN", "MAX"))
    ap.add_argument("--snowball", action="store_true", help="add newly found collaborators to the queue")
    ap.add_argument("--max-accounts", type=int, default=25, help="scrape at most this many this run (default 25)")
    ap.add_argument("--refresh", action="store_true", help="scrape accounts we already have")
    ap.add_argument("--dry-run", action="store_true", help="say what would happen, scrape nothing")
    args = ap.parse_args(argv)

    queue_path = Path(args.queue).resolve()
    run_dir = Path.home() / "Desktop" / "claude" / date.today().isoformat() / f"collabnet_{queue_path.stem}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = Log(run_dir / f"run_{datetime.now().strftime('%H%M%S')}.log")
    log(f"collabnet  queue {queue_path}")
    log(f"  run folder {run_dir}")
    log(f"  cookies {args.cookies}  rounds {args.rounds}  gap {args.gap} min  pause {args.pause} s  "
        f"snowball {args.snowball}  max {args.max_accounts}{'  DRY RUN' if args.dry_run else ''}")

    # The scrapes are saved on the USB drive (outputs/ -> /mnt/ubuntu26). Prove it can be
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
    try:
        while True:
            queue = read_queue(queue_path)  # re-read each time: snowball grows it
            if i >= len(queue):
                break
            account = queue[i]
            i += 1
            tag = f"[{i}/{len(queue)}] {account}"
            timeline = existing_capture(account)
            if timeline and not args.refresh:
                status, n = "had", sum(1 for _ in open(timeline, encoding="utf-8"))
                log(f"{tag}: have it ({timeline.relative_to(REPO)}, {n} posts)")
            elif scraped >= args.max_accounts:
                log(f"reached --max-accounts {args.max_accounts}; {len(queue) - i + 1} left in the queue")
                break
            elif args.dry_run:
                log(f"{tag}: would scrape")
                continue
            else:
                if scraped:
                    wait = random.uniform(*args.gap) * 60
                    log(f"    waiting {wait / 60:.1f} min before {account}")
                    time.sleep(wait)
                if not drive_ok():
                    return 2
                outdir = TIMELINES / f"{account}_{date.today().isoformat()}"
                log(f"{tag}: scraping -> {outdir.relative_to(REPO)}")
                try:
                    timeline, n, ended = step_scrape(account, args.cookies, args.rounds, args.pause, outdir)
                    # "capped" = stopped at --rounds before the oldest post: re-run with --refresh --rounds N
                    status = ("empty" if not n else "complete" if ended == "feed_end"
                              else "CAPPED" if ended == "max_rounds" else ended)
                except Exception as e:  # one bad account shouldn't stop the walk
                    timeline, n, status = None, 0, f"error: {e!r}"[:200]
                scraped += 1
                if status == "CAPPED":
                    capped.append((account, n))
                log(f"    {status}, {n} posts" + (f"  (hit --rounds {args.rounds}: older posts not reached; "
                                                     f"re-run with --refresh --rounds {args.rounds * 4})" if status == "CAPPED" else ""))

            ws = ""
            if timeline and n and not args.dry_run:
                ws = step_word_sort(account, timeline, run_dir)
                log(f"    word sort -> {ws.relative_to(run_dir)}")
                if args.snowball:
                    new = {a: c for a, c in collaborators_of(timeline, account).items()
                           if a not in read_queue(queue_path)}
                    if new:
                        append_to_queue(queue_path, new, account)
                        log(f"    + {len(new)} new collaborators queued: {', '.join(sorted(new))}")
            with open(run_dir / "status.tsv", "a", encoding="utf-8") as fh:
                fh.write(f"{account}\t{status}\t{n}\t{timeline or ''}\t{ws}\t"
                         f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
    except KeyboardInterrupt:
        write_capped(capped, queue_path, args.rounds, log)
        log("stopped (Ctrl-C). Run the same command again to carry on.")
        return 130
    write_capped(capped, queue_path, args.rounds, log)
    # One graph per run, drawn only at the very end (John, 2026-10-04: no image after every account).
    if not args.dry_run:
        step_graph(read_queue(queue_path), run_dir)
        log(f"graph -> graph/collab_graph.png (+ dated copy in graph/history/)")
    log(f"finished: {scraped} scraped this run. graph: {run_dir / 'graph' / 'collab_graph.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
