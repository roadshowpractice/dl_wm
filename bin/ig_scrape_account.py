#!/usr/bin/env python3
"""Evidence-grade scrape of one Instagram account's post history (metadata only).

Wraps igp.profile_history.scrape with slow, randomized pacing and keeps everything
needed to show where each record came from:

  raw_responses.jsonl.gz  every Instagram data response seen, unmodified, in arrival
                          order, streamed to disk as it arrives (a crash keeps what
                          came in). Each line: seq, captured_at_utc, url, status,
                          content_type, sha256 (of text), text.
  posts.jsonl             one record per post owned by (or co-authored with) the
                          account, oldest first, rebuilt from the raw responses:
                          ids, timestamps, type, counts, full caption, collaborators,
                          location, audio, dimensions. Each record lists the seq numbers
                          of the raw responses it came from (source_seqs).
  profile.json            profile counts as served at capture time (from the profile
                          page HTML or API responses), when present.
  manifest.json           when, how and as whom: UTC start/end, host, tool versions,
                          git commit (and whether the tree was dirty), sha256 of this
                          script and the scraper module, collecting account
                          (ds_user_id from the cookie file, never cookie values),
                          parameters, and sha256 + size of every output file.
  run.log                 console output.

Usage:
    python bin/ig_scrape_account.py <username> [--cookies conf/instagram.cookies.haddamgoel.txt]
        [--out DIR] [--max-rounds 200] [--pause 4 9] [--stall-limit 12]

--out defaults to outputs/ig_timelines/<username>_<UTC date>_forensic/ and must not
already exist (a capture is never overwritten).
"""
import argparse
import asyncio
import gzip
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from igp import profile_history  # noqa: E402

KNOWN_COLLECTORS = {"38012325418": "haddamgoel", "4067475941": "merrillp.jensen"}
POST_FIELDS = (
    "pk", "id", "code", "taken_at", "media_type", "product_type", "like_count",
    "comment_count", "play_count", "ig_play_count", "view_count", "video_view_count",
    "carousel_media_count", "original_width", "original_height", "video_duration",
    "has_audio", "is_paid_partnership", "like_and_view_counts_disabled",
    "accessibility_caption", "is_pinned",
)
PROFILE_FIELDS = ("follower_count", "following_count", "media_count", "full_name",
                  "biography", "is_verified", "category", "external_url", "pk", "username")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cookie_identity(cookie_file):
    """ds_user_id from a Netscape cookie file. Never reads out any other value."""
    for line in Path(cookie_file).read_text(errors="ignore").splitlines():
        parts = line.split("\t")
        if len(parts) == 7 and parts[5] == "ds_user_id":
            return parts[6].strip()
    return None


def git_state():
    def run(*args):
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "HEAD"), "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": [l[3:] for l in run("status", "--porcelain").splitlines() if l]}


def tool_versions():
    versions = {"python": platform.python_version()}
    for mod in ("playwright", "yt_dlp"):
        try:
            from importlib.metadata import version
            versions[mod] = version(mod)
        except Exception:
            versions[mod] = None
    return versions


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def parse_json_text(text):
    text = text.strip()
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]
    try:
        return [json.loads(text)]
    except Exception:
        pass
    # some endpoints stream several JSON documents, one per line
    docs = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                docs.append(json.loads(line))
            except Exception:
                pass
    return docs


def html_json_blobs(text):
    import re
    for body in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', text, flags=re.S):
        try:
            yield json.loads(body)
        except Exception:
            continue


def rebuild(raw_path, username):
    """posts + profile from the raw capture, so every value traces back to a seq."""
    posts, profile = {}, {}
    with gzip.open(raw_path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            seq, text = rec["seq"], rec["text"]
            docs = list(html_json_blobs(text)) if "text/html" in rec["content_type"] else parse_json_text(text)
            for doc in docs:
                for node in walk(doc):
                    if node.get("username") == username and any(k in node for k in ("follower_count", "edge_followed_by")):
                        for k in PROFILE_FIELDS:
                            if node.get(k) not in (None, ""):
                                profile[k] = node[k]
                        if "edge_followed_by" in node:
                            profile["follower_count"] = (node["edge_followed_by"] or {}).get("count")
                            profile["following_count"] = (node.get("edge_follow") or {}).get("count")
                        profile.setdefault("source_seqs", []).append(seq)
                    code = node.get("code") or node.get("shortcode")
                    if not code or "taken_at" not in node:
                        continue
                    owner = (node.get("user") or node.get("owner") or {})
                    owner = owner.get("username") if isinstance(owner, dict) else None
                    coauthors = sorted({u.get("username") for k in ("coauthor_producers", "invited_coauthor_producers")
                                        for u in (node.get(k) or []) if isinstance(u, dict) and u.get("username")})
                    if owner != username and username not in coauthors:
                        continue
                    p = posts.setdefault(code, {"code": code, "owner": owner, "source_seqs": []})
                    for k in POST_FIELDS:
                        if node.get(k) is not None:
                            p[k] = node[k]
                    cap = node.get("caption")
                    if isinstance(cap, dict) and cap.get("text") is not None:
                        p["caption"] = cap["text"]
                        p["caption_created_at"] = cap.get("created_at")
                    if coauthors:
                        p["collaborators"] = sorted(set(p.get("collaborators", [])) | set(coauthors))
                    loc = node.get("location")
                    if isinstance(loc, dict) and loc.get("name"):
                        p["location"] = loc.get("name")
                    clips = node.get("clips_metadata") or {}
                    music = (clips.get("music_info") or {}).get("music_asset_info") or {}
                    sound = clips.get("original_sound_info") or {}
                    if music.get("title"):
                        p["audio"] = f"{music.get('display_artist', '')} - {music['title']}".strip(" -")
                    elif sound.get("original_audio_title"):
                        p["audio"] = sound["original_audio_title"]
                    if seq not in p["source_seqs"]:
                        p["source_seqs"].append(seq)
    for p in posts.values():
        if p.get("taken_at"):
            p["taken_at_utc"] = datetime.fromtimestamp(p["taken_at"], timezone.utc).isoformat()
    return sorted(posts.values(), key=lambda r: r.get("taken_at") or 0), profile


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("--cookies", default=str(REPO / "conf" / "instagram.cookies.haddamgoel.txt"))
    ap.add_argument("--out")
    ap.add_argument("--max-rounds", type=int, default=200)
    ap.add_argument("--pause", type=float, nargs=2, default=[4.0, 9.0], metavar=("MIN", "MAX"))
    ap.add_argument("--stall-limit", type=int, default=12)
    args = ap.parse_args()

    username = args.username.lstrip("@").strip("/")
    started = utc_now()
    out = Path(args.out) if args.out else REPO / "outputs" / "ig_timelines" / f"{username}_{started[:10]}_forensic"
    if out.exists():
        sys.exit(f"refusing to overwrite an existing capture: {out}")
    out.mkdir(parents=True)
    raw_path = out / "raw_responses.jsonl.gz"
    log = open(out / "run.log", "w", encoding="utf-8")

    def say(msg):
        line = f"{utc_now()} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    collector_id = cookie_identity(args.cookies)
    say(f"capture of @{username} as {KNOWN_COLLECTORS.get(collector_id, 'unknown account')} "
        f"(ds_user_id {collector_id}), pause {args.pause[0]:g}-{args.pause[1]:g}s, max {args.max_rounds} rounds")

    raw = gzip.open(raw_path, "wt", encoding="utf-8")
    counter = {"seq": 0}

    def sink(rec):
        counter["seq"] += 1
        text = rec["text"]
        raw.write(json.dumps({"seq": counter["seq"], "captured_at_utc": utc_now(), "url": rec["url"],
                              "status": rec["status"], "content_type": rec["content_type"],
                              "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "text": text},
                             ensure_ascii=False) + "\n")
        raw.flush()

    t0 = time.time()
    found = asyncio.run(profile_history.scrape(username, Path(args.cookies), args.max_rounds,
                                               stall_limit=args.stall_limit, pause=tuple(args.pause),
                                               raw_sink=sink))
    raw.close()
    say(f"scrape done: {counter['seq']} raw responses, {len(found)} posts seen by the scraper, {time.time() - t0:.0f}s")

    posts, profile = rebuild(raw_path, username)
    with open(out / "posts.jsonl", "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    (out / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"rebuilt from raw: {len(posts)} posts, profile fields: {sorted(k for k in profile if k != 'source_seqs')}")
    if profile.get("media_count"):
        say(f"coverage: {len(posts)} of {profile['media_count']} posts the profile reports")

    log.close()
    files = {}
    for name in ("raw_responses.jsonl.gz", "posts.jsonl", "profile.json", "run.log"):
        path = out / name
        files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest = {
        "subject": username,
        "started_utc": started,
        "finished_utc": utc_now(),
        "collector": {"ds_user_id": collector_id, "account": KNOWN_COLLECTORS.get(collector_id),
                      "cookie_file": Path(args.cookies).name},
        "host": platform.node(),
        "method": "headless Chromium (Playwright) on the profile page, scrolling to trigger "
                  "Instagram's own timeline API; responses recorded as received, unmodified. "
                  "Images/video/fonts/CSS not loaded. No interaction beyond scrolling.",
        "parameters": {"max_rounds": args.max_rounds, "pause_seconds": args.pause, "stall_limit": args.stall_limit},
        "tools": tool_versions(),
        "code": {**git_state(),
                 "sha256_bin_ig_scrape_account_py": sha256_file(Path(__file__)),
                 "sha256_igp_profile_history_py": sha256_file(Path(profile_history.__file__))},
        "counts": {"raw_responses": counter["seq"], "posts": len(posts),
                   "profile_media_count": profile.get("media_count")},
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"manifest sha256 {sha256_file(out / 'manifest.json')}")
    print(f"written to {out}")


if __name__ == "__main__":
    main()
