#!/usr/bin/env python3
"""ig_opened_posts: the Instagram posts and reels John opened in a Chrome profile, read from its History.

The "browse, then harvest" step (docs/browse_then_harvest.md). John browses an account by hand
and clicks into each post he wants; this reads which ones he opened. No scraper, no extension,
no network: it only reads a copy of the profile's History database.

  1. COPY. Chrome locks History while it runs, so the file is copied first (close Chrome before
     running, or the last few minutes may not be flushed yet). The copy is kept in the output dir.
  2. QUERY. Every visit to instagram.com/p/... or /reel/... in the time window, oldest first.
     URLs are cut at '?'. Chrome stores visit_time as microseconds since 1601-01-01 UTC.
  3. WRITE. <outdir>/
         history_visits_raw.tsv      every visit: local time, URL (repeats kept)
         <date>_<name>_opened_posts.txt   unique URLs in first-visit order, one per line (dllink --list)
         History.copy                the database copy the list came from
         SHA256SUMS                  for all of the above
  4. CHECK (optional, --timeline). Each shortcode is looked up in a captured timeline jsonl
     (e.g. a reversescrape run) and the ones missing from it are listed.

Usage:
    openedposts [--name LABEL] [--date YYYY-MM-DD] [--since HH:MM] [--until HH:MM]
                [--profile DIR] [--timeline FILE.jsonl] [--outdir DIR]

  --name      label for the output dir and list file (default: instagram)
  --date      which day's visits, local time (default: today)
  --since/--until  narrow the window within that day (default: whole day)
  --profile   Chrome profile dir (default: ~/.config/google-chrome/Profile 2)
  --timeline  captured timeline jsonl to check the shortcodes against
  --outdir    default: ~/Desktop/claude/<today>/claude/<name>_opened_posts/
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys

CHROME_EPOCH_OFFSET = 11644473600  # seconds from 1601-01-01 to 1970-01-01

QUERY = """
    select datetime(v.visit_time/1000000 - ?, 'unixepoch', 'localtime') as t, u.url
    from visits v join urls u on u.id = v.url
    where (u.url like '%instagram.com/p/%' or u.url like '%instagram.com/reel/%')
      and date(v.visit_time/1000000 - ?, 'unixepoch', 'localtime') = ?
      and time(v.visit_time/1000000 - ?, 'unixepoch', 'localtime') between ? and ?
    order by v.visit_time
"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def shortcode(url):
    return url.rstrip("/").split("/")[-1]


def timeline_shortcodes(path):
    codes = set()
    with open(path) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                codes.add(r.get("shortcode") or r.get("code"))
    return codes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", default="instagram")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--since", default="00:00")
    ap.add_argument("--until", default="23:59:59")
    ap.add_argument("--profile", default="~/.config/google-chrome/Profile 2")
    ap.add_argument("--timeline", help="timeline jsonl to check the shortcodes against")
    ap.add_argument("--outdir")
    args = ap.parse_args()

    history = os.path.join(os.path.expanduser(args.profile), "History")
    if not os.path.exists(history):
        sys.exit(f"no History file at {history}")
    today = dt.date.today().isoformat()
    outdir = os.path.expanduser(args.outdir or f"~/Desktop/claude/{today}/claude/{args.name}_opened_posts")
    os.makedirs(outdir, exist_ok=True)

    copy = os.path.join(outdir, "History.copy")
    shutil.copyfile(history, copy)
    print(f"copied {history} -> {copy}")

    since = args.since if args.since.count(":") == 2 else args.since + ":00"
    until = args.until if args.until.count(":") == 2 else args.until + ":59"
    con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    rows = con.execute(QUERY, (CHROME_EPOCH_OFFSET, CHROME_EPOCH_OFFSET, args.date,
                               CHROME_EPOCH_OFFSET, since, until)).fetchall()
    con.close()

    visits = [(t, url.split("?")[0]) for t, url in rows]
    unique = []
    for _, url in visits:
        if url not in unique:
            unique.append(url)

    raw = os.path.join(outdir, "history_visits_raw.tsv")
    with open(raw, "w") as f:
        f.writelines(f"{t}\t{url}\n" for t, url in visits)
    listfile = os.path.join(outdir, f"{args.date}_{args.name}_opened_posts.txt")
    with open(listfile, "w") as f:
        f.writelines(url + "\n" for url in unique)

    with open(os.path.join(outdir, "SHA256SUMS"), "w") as f:
        for p in (copy, raw, listfile):
            f.write(f"{sha256(p)}  {os.path.basename(p)}\n")

    window = f"{args.date} {since}-{until}"
    if visits:
        window += f" (first {visits[0][0][11:]}, last {visits[-1][0][11:]})"
    print(f"{window}: {len(visits)} visits, {len(unique)} unique posts")
    if args.timeline:
        codes = timeline_shortcodes(os.path.expanduser(args.timeline))
        missing = [u for u in unique if shortcode(u) not in codes]
        print(f"in timeline {args.timeline}: {len(unique) - len(missing)}/{len(unique)}")
        for u in missing:
            print(f"  NOT IN TIMELINE: {u}")
    print(f"list: {listfile}")
    print(f"next: dllink --list {listfile}")


if __name__ == "__main__":
    main()
