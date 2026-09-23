"""List every post an Instagram creator made on a given day — metadata only.

Scrolls the creator's profile (igp.profile_history — headless Chromium,
logged-in cookies) gently, stops once it's scrolled past the target day, and
keeps only posts whose taken_at falls on that calendar day in --tz. Each hit
gets its URL and Collaborators list, with a `tags_tb` flag when timballard89
is one of the Collaborators. Nothing is downloaded; hand the URLs to
`dllink <url>` afterwards.

Scraping with care:
  - slow, randomized scroll pauses (--pause, default 4-9s) and more patience
    before assuming the feed has ended
  - a cooldown between scrapes (--cooldown minutes, default 2), tracked
    across runs in ~/.config/dl_wm/ig_scrape_last.txt; --force skips it
  - every post seen is kept in outputs/ig_timelines/<username>.jsonl, and if
    that saved timeline already covers the requested day, no scrape happens

Usage:
    python bin/ig_posts_on_day.py <username> <YYYY-MM-DD> [--tz America/Sao_Paulo]

Writes outputs/<today>/ig_posts_<username>_<day>.jsonl
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.append(root_dir)

from igp.profile_history import scrape

TB = "timballard89"
LAST_SCRAPE = Path.home() / ".config" / "dl_wm" / "ig_scrape_last.txt"
TIMELINES = Path(root_dir) / "outputs" / "ig_timelines"


def load_timeline(username):
    posts, meta = {}, {}
    path = TIMELINES / f"{username}.jsonl"
    if path.exists():
        for line in path.open():
            rec = json.loads(line)
            posts[rec["shortcode"]] = rec
    meta_path = TIMELINES / f"{username}.meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    return posts, meta


def save_timeline(username, posts, meta):
    TIMELINES.mkdir(parents=True, exist_ok=True)
    with open(TIMELINES / f"{username}.jsonl", "w") as f:
        for rec in sorted(posts.values(), key=lambda r: r["taken_at"] or 0):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (TIMELINES / f"{username}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("username")
    parser.add_argument("day", help="YYYY-MM-DD")
    parser.add_argument("--tz", default="America/Los_Angeles", help="timezone the day is counted in (default: %(default)s)")
    parser.add_argument("--cookies", default=os.path.join(root_dir, "conf", "instagram.cookies.txt"))
    parser.add_argument("--max-rounds", type=int, default=150)
    parser.add_argument("--pause", type=float, nargs=2, default=[4.0, 9.0], metavar=("MIN", "MAX"),
                        help="seconds to wait after each scroll, random in [MIN, MAX] (default: 4 9)")
    parser.add_argument("--cooldown", type=float, default=2, help="minutes required since the last scrape (default: %(default)s)")
    parser.add_argument("--force", action="store_true", help="scrape even inside the cooldown or when the saved timeline covers the day")
    args = parser.parse_args()

    username = args.username.lstrip("@").strip("/")
    tz = ZoneInfo(args.tz)
    day = date.fromisoformat(args.day)
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    lo, hi = start.timestamp(), (start + timedelta(days=1)).timestamp()

    posts, meta = load_timeline(username)
    covered = (meta.get("oldest_seen", float("inf")) < lo and meta.get("scraped_at", 0) >= hi)

    if covered and not args.force:
        print(f"saved timeline for @{username} already covers {day} — not scraping")
    else:
        if LAST_SCRAPE.exists() and not args.force:
            waited = (time.time() - float(LAST_SCRAPE.read_text().strip() or 0)) / 60
            if waited < args.cooldown:
                print(f"last scrape was {waited:.1f} min ago — wait {args.cooldown - waited:.1f} more min "
                      f"(cooldown {args.cooldown:g} min), or pass --force")
                sys.exit(2)
        LAST_SCRAPE.parent.mkdir(parents=True, exist_ok=True)
        LAST_SCRAPE.write_text(f"{time.time()}\n")

        print(f"scraping @{username} for posts on {day} ({args.tz}), pausing {args.pause[0]:g}-{args.pause[1]:g}s per scroll")
        found = asyncio.run(scrape(username, Path(args.cookies), args.max_rounds, stall_limit=10,
                                   stop_before=lo, pause=tuple(args.pause)))
        posts.update(found)
        if found:
            oldest = min(r["taken_at"] or 0 for r in found.values())
            meta["oldest_seen"] = min(oldest, meta.get("oldest_seen", oldest))
            if oldest < lo:
                meta["scraped_at"] = time.time()
        save_timeline(username, posts, meta)

        if not found:
            print("WARNING: no posts seen at all — private account, bad cookies, or IG blocked the scrape")
        elif min(r["taken_at"] or 0 for r in found.values()) >= lo:
            oldest = min(r["taken_at"] or 0 for r in found.values())
            print(f"WARNING: never scrolled back as far as {day} (oldest post seen "
                  f"{datetime.fromtimestamp(oldest, tz):%Y-%m-%d}) — IG may have stopped paginating; try again later")

    hits = []
    for rec in sorted(posts.values(), key=lambda r: r["taken_at"] or 0):
        t = rec["taken_at"] or 0
        if lo <= t < hi:
            hits.append({
                "username": username,
                "url": f"https://www.instagram.com/p/{rec['shortcode']}/",
                "taken_at": datetime.fromtimestamp(t, tz).isoformat(),
                "collaborators": rec["collaborators"],
                "tags_tb": TB in rec["collaborators"],
                "caption": rec["caption"],
            })

    outdir = os.path.join(root_dir, "outputs", datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"ig_posts_{username}_{day}.jsonl")
    with open(out_path, "w") as f:
        for h in hits:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")

    print(f"\n{len(hits)} post(s) on {day}:")
    for h in hits:
        tb = "  [tags TB]" if h["tags_tb"] else ""
        print(f"  {h['taken_at'][11:16]}  {h['url']}{tb}")
    print(f"written to {out_path}")


if __name__ == "__main__":
    main()
