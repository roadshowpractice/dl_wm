#!/usr/bin/env python3
"""yt_channel_meta.py: list a YouTube channel's videos with exact upload dates and basic stats. Metadata only, no downloads.

Why: YouTube's Videos tab only shows fuzzy ages ("1y ago" = 12 to 23 months). This records each video's real upload date
(and views, duration, title, description), so claims about a channel rest on dates, not labels.

Works the same on macOS and Linux. Needs Python 3.11+ (yt-dlp is dropping 3.10) and yt-dlp. On a Mac:
    brew install python            # if python3 --version is older than 3.11
    python3 -m pip install -U yt-dlp
If YouTube answers "Sign in to confirm you're not a bot", export cookies from a logged-in browser and pass --cookies:
    yt-dlp --cookies-from-browser chrome --cookies cookies.txt --skip-download https://www.youtube.com/@handle
Usage:
    python3 yt_channel_meta.py @imaginationpodcastofficial                    # whole channel (Videos tab)
    python3 yt_channel_meta.py @imaginationpodcastofficial --limit 5          # quick test on the 5 newest
    python3 yt_channel_meta.py @handle --out DIR --sleep 3 --tabs videos,streams,shorts
    python3 yt_channel_meta.py @handle --cookies cookies.txt                  # only if YouTube asks to sign in
Re-running with the same --out resumes: videos already in videos.jsonl are skipped.

Writes into --out (default ./yt_meta_<handle>_<date>/):
    videos.jsonl    one line per video: yt-dlp's metadata minus formats/thumbnails/captions (the raw record)
    videos.tsv      oldest first: upload_date, season, episode, code, id, title, duration_s, views, likes, comments, live, url
    seasons.tsv     per season code: n videos, first/last upload date, span in days, lowest/highest episode number
    run.log         command, yt-dlp version, start/end time, errors
    SHA256SUMS      hashes of the files above
"""
import argparse, csv, datetime as dt, hashlib, json, platform, re, sys, time
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is missing. Install it with:  python3 -m pip install -U yt-dlp")

DROP = {"formats", "requested_formats", "thumbnails", "automatic_captions", "subtitles", "heatmap", "http_headers",
        "_format_sort_fields", "storyboards", "requested_downloads"}
CODE = re.compile(r"\bS(\d{1,2})\s*E(\d{1,4})\b", re.I)


def log(fh, *a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    fh.write(line + "\n"); fh.flush()


def channel_url(ch):
    if ch.startswith("http"):
        return ch.rstrip("/")
    return "https://www.youtube.com/" + (ch if ch.startswith("@") else "@" + ch)


def list_ids(base, tabs, cookies, lf):
    """Flat listing of each tab, newest first; returns [(id, tab, position)] without duplicates."""
    opts = {"extract_flat": "in_playlist", "quiet": True, "no_warnings": True, "ignoreerrors": "only_download"}
    if cookies:
        opts["cookiefile"] = cookies
    seen, out = set(), []
    with yt_dlp.YoutubeDL(opts) as y:
        for tab in tabs:
            try:
                info = y.extract_info(f"{base}/{tab}", download=False) or {}
            except yt_dlp.utils.DownloadError as e:
                log(lf, f"tab {tab}: skipped ({str(e).split(': ')[-1][:120]})"); continue
            ents = [e for e in (info.get("entries") or []) if e and e.get("id")]
            log(lf, f"tab {tab}: {len(ents)} entries")
            for pos, e in enumerate(ents, 1):
                if e["id"] not in seen:
                    seen.add(e["id"]); out.append((e["id"], tab, pos))
    return out


def fetch(vid, cookies):
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "ignore_no_formats_error": True}
    if cookies:
        opts["cookiefile"] = cookies
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    return {k: v for k, v in y.sanitize_info(info).items() if k not in DROP}


def day(r):
    """Upload date as YYYY-MM-DD (UTC timestamp when present, else yt-dlp's upload_date)."""
    ts = r.get("timestamp") or r.get("release_timestamp")
    if ts:
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
    u = r.get("upload_date") or ""
    return f"{u[:4]}-{u[4:6]}-{u[6:]}" if len(u) == 8 else ""


def write_tables(out, recs):
    rows = []
    for r in recs:
        m = CODE.search(r.get("title") or "")
        s, e = (int(m.group(1)), int(m.group(2))) if m else ("", "")
        rows.append({"upload_date": day(r), "season": s, "episode": e, "code": f"S{s}E{e}" if m else "",
                     "id": r.get("id"), "title": r.get("title"), "duration_s": r.get("duration"),
                     "views": r.get("view_count"), "likes": r.get("like_count"), "comments": r.get("comment_count"),
                     "live": r.get("live_status") or "", "url": r.get("webpage_url")})
    rows.sort(key=lambda x: (x["upload_date"] or "9999", x["id"]))
    with open(out / "videos.tsv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["upload_date"], delimiter="\t"); w.writeheader(); w.writerows(rows)
    by = {}
    for x in rows:
        if x["season"] != "" and x["upload_date"]:
            by.setdefault(x["season"], []).append(x)
    with open(out / "seasons.tsv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["season", "n_videos", "first_upload", "last_upload", "span_days", "min_episode", "max_episode"])
        for s in sorted(by):
            L = by[s]; d0, d1 = L[0]["upload_date"], L[-1]["upload_date"]
            span = (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days
            eps = [x["episode"] for x in L]
            w.writerow([s, len(L), d0, d1, span, min(eps), max(eps)])
    return rows, by


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("channel", help="@handle or channel URL")
    ap.add_argument("--out", help="output folder (default ./yt_meta_<handle>_<date>)")
    ap.add_argument("--tabs", default="videos", help="comma list of channel tabs (videos,streams,shorts)")
    ap.add_argument("--limit", type=int, default=0, help="only the N newest (testing)")
    ap.add_argument("--sleep", type=float, default=2.0, help="seconds between videos (be gentle)")
    ap.add_argument("--cookies", help="Netscape cookies.txt, only if YouTube demands sign-in")
    a = ap.parse_args()

    base = channel_url(a.channel)
    handle = base.rsplit("/", 1)[-1].lstrip("@")
    out = Path(a.out or f"yt_meta_{handle}_{dt.date.today():%Y-%m-%d}"); out.mkdir(parents=True, exist_ok=True)
    jl = out / "videos.jsonl"
    have = {}
    if jl.exists():
        for line in jl.open(encoding="utf-8"):
            try:
                r = json.loads(line); have[r["id"]] = r
            except Exception:
                pass
    with open(out / "run.log", "a", encoding="utf-8") as lf:
        log(lf, f"== {dt.datetime.now().isoformat(timespec='seconds')} start: {' '.join(sys.argv)}")
        log(lf, f"yt-dlp {yt_dlp.version.__version__}, python {platform.python_version()}, {platform.system()} {platform.release()}")
        ids = list_ids(base, [t.strip() for t in a.tabs.split(",") if t.strip()], a.cookies, lf)
        if a.limit:
            ids = ids[:a.limit]
        todo = [t for t in ids if t[0] not in have]
        log(lf, f"listed {len(ids)}, already have {len(ids) - len(todo)}, fetching {len(todo)}")
        errs = 0
        with jl.open("a", encoding="utf-8") as fh:
            for i, (vid, tab, pos) in enumerate(todo, 1):
                try:
                    r = fetch(vid, a.cookies); r["_tab"], r["_tab_position"] = tab, pos
                    r["_fetched_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n"); fh.flush(); have[vid] = r
                    log(lf, f"[{i}/{len(todo)}] {vid} {day(r)} {(r.get('title') or '')[:70]}")
                except Exception as e:
                    errs += 1; log(lf, f"[{i}/{len(todo)}] {vid} ERROR {str(e)[:200]}")
                    if errs >= 5 and errs == i:
                        log(lf, "stopping: the first 5 all failed (blocked or sign-in needed? try --cookies)"); break
                time.sleep(a.sleep)
        keep = {v for v, _, _ in ids}
        rows, by = write_tables(out, [have[v] for v in have if v in keep])
        for s in sorted(by):
            L = by[s]
            log(lf, f"season {s}: {len(L)} videos, {L[0]['upload_date']} .. {L[-1]['upload_date']}")
        log(lf, f"== done: {len(rows)} videos in tables, {errs} errors")
    with open(out / "SHA256SUMS", "w") as fh:
        for n in ("videos.jsonl", "videos.tsv", "seasons.tsv", "run.log"):
            p = out / n
            if p.exists():
                fh.write(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {n}\n")
    print(f"wrote {out}/")


if __name__ == "__main__":
    main()
