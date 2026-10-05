#!/usr/bin/env python3
"""Decide a group's membership from the data: documented seeds + accounts the posts tie to them.

Tier 1, "documented": the seed accounts, as listed in the seeds file (one account per line,
'# source' after it: where in OUR earlier work the account was placed in the group).
Tier 2, "added by data": any other account that our scrapes show co-posting with at least
--min-seeds DIFFERENT seed accounts. Co-posting = both are among {scraped account} + {credited
collaborators} on the same post (the same rule bin/ig_collab_graph.py uses for a link).

Writes (into --out):
  members.txt           tier 1 + tier 2, ready for `ig_collab_graph.py --members` (source/rule after #)
  members_by_data.tsv   every tier-2 account: which seeds, how many posts with each, every shortcode
  seeds_check.tsv       every seed: was it scraped, how many posts, how many other seeds it co-posts with

Usage:
    python bin/ig_group_members.py --seeds sra_group.txt --out DIR [--min-seeds 2]
        [--inputs FILE,FILE,...]      (default: every scrape we have, newest per account)

Limits, stated in the files: only accounts and posts in our scrapes count; capped scrapes miss
older posts; an account that only co-posts with ONE seed is not added, however often.
"""
import argparse
import collections
import importlib.util
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ig_collab_graph", REPO / "bin" / "ig_collab_graph.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def decide(posts, seeds, min_seeds):
    """(tier2, seed_stats). tier2 = {account: {seed: [shortcodes]}} for accounts tied to >= min_seeds seeds."""
    ties = collections.defaultdict(lambda: collections.defaultdict(list))
    seed_ties = collections.defaultdict(set)
    for code, rec in posts.items():
        people = rec["people"]
        here = people & seeds
        for p in people:
            for s in here:
                if p != s:
                    ties[p][s].append(code)
        for s in here:
            seed_ties[s] |= here - {s}
    tier2 = {a: dict(t) for a, t in ties.items() if a not in seeds and len(t) >= min_seeds}
    return tier2, seed_ties


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-seeds", type=int, default=2)
    ap.add_argument("--inputs", default="")
    args = ap.parse_args(argv)

    seeds_notes = g.read_members(args.seeds)
    seeds = set(seeds_notes)
    if args.inputs:
        files = {}
        for raw in args.inputs.split(","):
            p = Path(raw.strip()).expanduser().resolve()
            acct = (p.name[: -len("_timeline.jsonl")] if p.name.endswith("_timeline.jsonl")
                    else re.sub(r"_\d{4}-\d{2}-\d{2}.*$", "", p.parent.name))
            files[acct.lower()] = p
    else:
        files = g.account_files()
    posts, counts = g.load_posts(files)
    tier2, seed_ties = decide(posts, seeds, args.min_seeds)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(out / "members.txt", "w", encoding="utf-8") as fh:
        fh.write(f"# Group membership decided {stamp} by bin/ig_group_members.py from {len(files)} scrapes.\n"
                 f"# Tier 1 = documented seeds ({args.seeds}). Tier 2 = co-posts with >= {args.min_seeds} "
                 f"different seeds (evidence: members_by_data.tsv).\n")
        for a in seeds_notes:
            fh.write(f"{a:<30}# documented: {seeds_notes[a]}\n")
        for a in sorted(tier2, key=lambda a: (-len(tier2[a]), a)):
            fh.write(f"{a:<30}# added by data: co-posts with {len(tier2[a])} seeds ({', '.join(sorted(tier2[a]))})\n")
    with open(out / "members_by_data.tsv", "w", encoding="utf-8") as fh:
        fh.write("account\tseeds_tied\tseed\tposts_with_seed\tshortcodes\n")
        for a in sorted(tier2, key=lambda a: (-len(tier2[a]), a)):
            for s, codes in sorted(tier2[a].items()):
                fh.write(f"{a}\t{len(tier2[a])}\t{s}\t{len(codes)}\t{','.join(sorted(codes))}\n")
    with open(out / "seeds_check.tsv", "w", encoding="utf-8") as fh:
        fh.write("seed\tscraped\tposts_in_scrape\tother_seeds_it_coposts_with\tsource\n")
        for s in seeds_notes:
            fh.write(f"{s}\t{'y' if s in files else 'n'}\t{counts.get(s, '')}\t"
                     f"{','.join(sorted(seed_ties.get(s, ())))}\t{seeds_notes[s]}\n")
    print(f"{len(seeds)} documented + {len(tier2)} added by data (>= {args.min_seeds} seeds) -> {out / 'members.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
