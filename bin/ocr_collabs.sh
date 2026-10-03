#!/usr/bin/env bash
# ocr_collabs.sh — OCR a directory of Instagram screenshots and collect who
# collaborated on what.
#
# Runs bin/ocr_screenshots.py over every image in DIR, then reads its ocr.jsonl
# and writes, in OUTDIR:
#   collabs_by_screenshot.tsv  one row per screenshot: time, kind, shortcode,
#                              authors, "+N others", file
#   collabs_by_post.tsv        one row per post (shortcode): every author seen
#                              across all its screenshots, merged — a
#                              Collaborators pop-up fills in the names a
#                              "first and 2 others" header leaves out
#   collab_pairs.tsv           every pair of accounts seen together on a post,
#                              with how many posts they share
#   ocr.jsonl, *.ocr.txt       the raw per-screenshot OCR output
#
# Usage: bin/ocr_collabs.sh DIR [OUTDIR] [--draw-boxes]
#   OUTDIR defaults to DIR/ocr_<YYYY-MM-DD>. Re-running into the same OUTDIR
#   starts that OUTDIR's ocr.jsonl fresh. ~5-8s per screenshot.
#   COLLECT_ONLY=1 skips the OCR and just rebuilds the TSVs from OUTDIR/ocr.jsonl.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-$HOME/miniforge3/envs/dl_wm/bin/python}"

dir="${1:?usage: bin/ocr_collabs.sh DIR [OUTDIR] [--draw-boxes]}"
shift
outdir=""
extra=()
for arg in "$@"; do
  case "$arg" in
    --*) extra+=("$arg") ;;
    *) outdir="$arg" ;;
  esac
done
[ -d "$dir" ] || { echo "not a directory: $dir"; exit 1; }
outdir="${outdir:-$dir/ocr_$(date +%F)}"
mkdir -p "$outdir"
if [ "${COLLECT_ONLY:-0}" != 1 ]; then
rm -f "$outdir/ocr.jsonl"

count=$(find -L "$dir" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) | wc -l)
echo "OCR: $count image(s) in $dir -> $outdir"
"$PY" "$REPO/bin/ocr_screenshots.py" "$dir" --out "$outdir" "${extra[@]}"
fi

"$PY" - "$outdir" <<'PY'
import csv, json, sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

out = Path(sys.argv[1])
rows = [json.loads(l) for l in (out / "ocr.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

shots = []
posts = defaultdict(lambda: {"authors": [], "others": 0, "kinds": set(), "files": [], "complete": False})
for r in rows:
    ig = r.get("instagram") or {}
    kind = ig.get("kind", "not_instagram")
    authors = ig.get("authors") or ([ig["username"]] if ig.get("username") else [])
    code = ig.get("shortcode") or ""
    shots.append([r.get("taken_at") or "", kind, code, ",".join(authors),
                  ig.get("others_count") or "", Path(r["file"]).name])
    if code:
        p = posts[code]
        p["authors"] += [a for a in authors if a not in p["authors"]]
        p["others"] = max(p["others"], ig.get("others_count") or 0)
        p["kinds"].add(kind)
        p["files"].append(Path(r["file"]).name)
        p["complete"] = p["complete"] or bool(ig.get("shortcode_complete"))

def write(name, header, data):
    with (out / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(header)
        w.writerows(data)

write("collabs_by_screenshot.tsv",
      ["taken_at", "kind", "shortcode", "authors", "plus_others", "file"], sorted(shots))

post_rows, pairs = [], defaultdict(set)
for code, p in sorted(posts.items()):
    named = len(p["authors"])
    # a "+N others" header means N+1 people total; if we've named them all, nothing is missing
    missing = max(0, p["others"] + 1 - named) if p["others"] else 0
    # Instagram post shortcodes are 11 characters: shorter = URL bar cut off,
    # longer = OCR added a character (seen: DNG6zZUIRVyf for DNG6zUIRVyf).
    check = "ok" if len(code) == 11 else ("cut-off" if len(code) < 11 else "misread")
    post_rows.append([code, check, len(p["authors"]),
                      ",".join(p["authors"]), missing, ",".join(sorted(p["kinds"])), ",".join(p["files"])])
    for a, b in combinations(sorted(p["authors"]), 2):
        pairs[(a, b)].add(code)
write("collabs_by_post.tsv",
      ["shortcode", "shortcode_check", "n_authors", "authors", "names_still_missing", "kinds", "files"], post_rows)
write("collab_pairs.tsv", ["account_a", "account_b", "posts_together", "shortcodes"],
      sorted(([a, b, len(c), ",".join(sorted(c))] for (a, b), c in pairs.items()), key=lambda r: (-r[2], r[0], r[1])))

kinds = defaultdict(int)
for s in shots:
    kinds[s[1]] += 1
print("\nscreenshots by kind: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
print(f"posts: {len(posts)}  collaborator pairs: {len(pairs)}")
print(f"wrote {out}/collabs_by_screenshot.tsv, collabs_by_post.tsv, collab_pairs.tsv")
PY
