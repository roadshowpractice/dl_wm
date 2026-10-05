#!/usr/bin/env python3
"""List the posts, across a set of scraped accounts, that tie to one account.

A post counts when ANY of these is true (the "why" column says which):
  collab   the account is credited as a collaborator on the post
  @        the caption has @<account>
  name     the caption matches --name (a regex, case-insensitive), e.g. "tim\\s*ballard"
The account's OWN solo posts are left out (they aren't collaborator posts);
its co-authored posts stay in. Each post is listed once, by shortcode, even when it
shows up in several accounts' grids.

Reads the newest non-empty scrape of each account in outputs/ig_timelines/
(profile_history timelines or forensic captures). "have" = dl_wm/metadata/instagram__<code>.json
exists (already downloaded).

Writes (default prefix ~/Desktop/claude/<today>/analysis/<account>_tagged_posts):
  <prefix>.tsv        every matching post: shortcode, posted, found_in, why, collaborators, have, caption start
  <prefix>.urls.txt   only the ones NOT downloaded yet, one URL per line -> `dllink --list <prefix>.urls.txt`

Usage:
    python bin/ig_tagged_posts.py timballard89 --name "tim\\s*ballard" --queue QUEUE.txt
    python bin/ig_tagged_posts.py timballard89 --accounts hiddenwarmovie,tbfrescue
    python bin/ig_tagged_posts.py timballard89 --all          (every account we have scraped)

Caveat: profile_history captions are cut at ~200 characters, so the @ and name checks
miss mentions later in a long caption. The collab check uses the collaborator field and
isn't affected.
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
META = REPO / "metadata"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "bin" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_queue(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        a = line.split("#")[0].strip().lower()
        if a and a not in out:
            out.append(a)
    return out


def find_tagged(files, account, name_re=None):
    """{shortcode: record} for posts in these accounts' scrapes that tie to `account`."""
    account = account.lower()
    name = re.compile(name_re, re.I) if name_re else None
    rows = {}
    for acct, path in files.items():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                code = r.get("shortcode") or r.get("code")
                cap = r.get("caption") or ""
                collabs = sorted({c.lower() for c in (r.get("collaborators") or [])})
                if acct == account and not [c for c in collabs if c != account]:
                    continue  # the account's own solo post
                why = [w for w, hit in (("collab", account in collabs),
                                        ("@", f"@{account}" in cap.lower()),
                                        ("name", bool(name and name.search(cap)))) if hit]
                if not (code and why):
                    continue
                rec = rows.setdefault(code, {"found_in": set(), "why": set(), "collabs": set(),
                                             "taken_at": int(r.get("taken_at") or 0), "caption": cap})
                rec["found_in"].add(acct)
                rec["why"] |= set(why)
                rec["collabs"] |= set(collabs)
    return rows


def write(rows, prefix, meta_dir=META):
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    have = {p.name[len("instagram__"):-len(".json")] for p in meta_dir.glob("instagram__*.json")}
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t else ""
    new = 0
    with open(f"{prefix}.tsv", "w", encoding="utf-8") as t, open(f"{prefix}.urls.txt", "w", encoding="utf-8") as u:
        t.write("shortcode\tposted\tfound_in\twhy\tcollaborators\thave\tcaption_start\n")
        for code, r in sorted(rows.items(), key=lambda kv: kv[1]["taken_at"]):
            got = code in have
            t.write(f"{code}\t{day(r['taken_at'])}\t{','.join(sorted(r['found_in']))}\t{','.join(sorted(r['why']))}\t"
                    f"{','.join(sorted(r['collabs']))}\t{'y' if got else ''}\t{r['caption'][:90].replace(chr(10), ' ')}\n")
            if not got:
                u.write(f"https://www.instagram.com/p/{code}/\n")
                new += 1
    return len(rows), new


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("account", help="the account posts must tie to, e.g. timballard89")
    ap.add_argument("--name", help='caption regex for the name, e.g. "tim\\s*ballard"')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--queue", help="collabnet queue file: use the accounts in it")
    src.add_argument("--accounts", help="comma-separated accounts")
    src.add_argument("--all", action="store_true", help="every account we have scraped")
    ap.add_argument("--out", help="output prefix (default ~/Desktop/claude/<today>/analysis/<account>_tagged_posts)")
    args = ap.parse_args(argv)

    files = _load("ig_collab_graph").account_files()
    if args.queue:
        wanted = read_queue(args.queue)
    elif args.accounts:
        wanted = [a.strip().lower() for a in args.accounts.split(",") if a.strip()]
    else:
        wanted = list(files)
    missing = [a for a in wanted if a not in files]
    files = {a: files[a] for a in wanted if a in files}

    rows = find_tagged(files, args.account, args.name)
    prefix = args.out or (Path.home() / "Desktop" / "claude" / date.today().isoformat() / "analysis" / f"{args.account}_tagged_posts")
    total, new = write(rows, prefix)
    print(f"{total} posts tie to {args.account} across {len(files)} accounts; {total - new} already downloaded, "
          f"{new} to get -> {prefix}.urls.txt")
    if missing:
        print(f"no scrape yet for: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
