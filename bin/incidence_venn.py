#!/usr/bin/env python3
"""Weights and Venns straight from an incidence matrix (accounts x posts).

An incidence matrix is the sole object here: one row per account, one column per
post, a 1 meaning the account appears on that post. The weight of a link is the
overlap of two rows (their dot product); a row's sum is how many posts the
account is on. Nothing outside the matrix is read -- not authorship, not scrape
metadata, not the timelines. (Authorship belongs to interpretation, not to this
count; and if you read past the matrix you get lost in the forest.)

Reads a CSV shaped like docs/data/*/incidence_matrix.csv (header: account, then
one column per post). Picks the accounts named on the command line, prints their
sizes, every pairwise overlap, the triple overlap and the unions, and draws a
Venn (two circles, or three). The same link carries a different weight in a
different matrix -- the weight is only defined once the matrix is fixed.

Writes <out>/incidence_<accounts>.png and <out>/incidence_<accounts>.tsv.

Usage:
    python bin/incidence_venn.py docs/data/congruence/incidence_matrix.csv LDA LDC TB
    python bin/incidence_venn.py M.csv LDA LDC
    python bin/incidence_venn.py M.csv A B C --out ~/Desktop/claude/<date>/<handle>
"""
import argparse
import csv
import itertools
import os
from collections import Counter
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

PAPER = "#fbfaf6"; INK = "#1c1d22"; MUTED = "#5d6070"
HUE = ["#c6dbef", "#9ecae1", "#4292c6", "#2171b5", "#08306b"]
FALSEY = {"", "0", "0.0", "false", "f", "no", "n", "nan", "none", "n/a"}


def load_matrix(path):
    """Return {account: set(post_label)} from an incidence CSV."""
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise SystemExit(f"empty matrix: {path}")
    posts = rows[0][1:]
    out = {}
    for r in rows[1:]:
        if not r or not r[0].strip() or r[0].lstrip().startswith("#"):
            continue
        name = r[0].strip()
        cols = r[1:]
        out[name] = {posts[i] for i, v in enumerate(cols)
                     if i < len(posts) and v.strip().lower() not in FALSEY}
    return out


def draw2(names, sets, overlap, out):
    fig, ax = plt.subplots(figsize=(8.6, 6.0), dpi=170)
    ax.set_aspect("equal"); ax.axis("off")
    ln, rn = names
    ln_ = len(sets[ln]); rn_ = len(sets[rn])
    ax.set_title(f"{ln} vs {rn} — what the incidence says", fontsize=18, color=INK,
                 fontweight="bold", pad=14)
    ax.text(0.0, 1.02, "a link's weight is the number of posts two accounts share",
            ha="center", va="bottom", fontsize=11.5, color=MUTED, transform=ax.transAxes)
    ax.add_patch(Circle((-0.42, 0), 1.0, facecolor=HUE[2], alpha=0.45,
                        edgecolor=HUE[4], lw=1.5))
    ax.add_patch(Circle((0.42, 0), 1.0, facecolor=HUE[3], alpha=0.45,
                        edgecolor=HUE[4], lw=1.5))
    ax.text(-0.72, 0, str(ln_ - overlap), ha="center", va="center", fontsize=26, color=INK)
    ax.text(0.0, 0, str(overlap), ha="center", va="center", fontsize=30, color=HUE[4],
            fontweight="bold")
    ax.text(0.72, 0, str(rn_ - overlap), ha="center", va="center", fontsize=26, color=INK)
    ax.text(-0.55, 1.14, f"{ln}\n{ln_} posts", ha="center", va="bottom", fontsize=11, color=INK)
    ax.text(0.55, 1.14, f"{rn}\n{rn_} posts", ha="center", va="bottom", fontsize=11, color=INK)
    ax.text(0.0, -0.60, f"weight λ = {overlap}", ha="center", va="top", fontsize=14,
            color=HUE[4], fontweight="bold")
    ax.text(0.0, -0.88, "the overlap: posts both accounts appear on", ha="center",
            va="top", fontsize=10.5, color=MUTED)
    ax.text(0.0, -1.24, "circles schematic; counts exact (incidence only)",
            ha="center", va="top", fontsize=9.5, color=MUTED, style="italic")
    ax.set_xlim(-1.7, 1.7); ax.set_ylim(-1.4, 1.5)
    fig.tight_layout()
    p = out / f"incidence_{ln}_{rn}.png"
    fig.savefig(p, facecolor=PAPER, bbox_inches="tight"); plt.close(fig)
    print("wrote", p)


def draw3(names, sets, regions, out):
    A, B, C = names
    fig, ax = plt.subplots(figsize=(8.8, 7.2), dpi=165)
    ax.set_aspect("equal"); ax.axis("off")
    cen = {A: (0.0, 0.32), B: (-0.42, -0.30), C: (0.42, -0.30)}
    col = {A: HUE[1], B: HUE[2], C: HUE[3]}
    for k in names:
        x, y = cen[k]
        ax.add_patch(Circle((x, y), 0.72, facecolor=col[k], alpha=0.40,
                            edgecolor=HUE[4], lw=1.6))
    pos = {
        (A,): (0.0, 0.78), (B,): (-0.72, -0.44), (C,): (0.72, -0.44),
        (A, B): (-0.26, 0.14), (A, C): (0.26, 0.14), (B, C): (0.0, -0.44),
        (A, B, C): (0.0, -0.02),
    }
    for key, n in regions.items():
        x, y = pos[key]
        ax.text(x, y, str(n), ha="center", va="center",
                fontsize=15 if len(key) == 3 else 13,
                color=MUTED if n == 0 else (HUE[4] if len(key) == 3 else INK),
                fontweight="bold" if (len(key) == 3 and n) else "normal")
    for k in names:
        x, y = cen[k]
        ax.text(x, y + (0.86 if k == A else -0.60 if y < 0 else 0.86), f"{k}\n{len(sets[k])}",
                ha="center", va="center", fontsize=11, color=INK)
    ax.set_title(f"{A} / {B} / {C} — posts in common", fontsize=16, color=INK,
                 fontweight="bold", pad=30)
    ax.text(0.5, 1.008, "incidence only · a weight is an overlap",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=11, color=MUTED)
    ax.text(0.0, -1.10, "circles schematic; counts exact (incidence only)",
            ha="center", va="top", fontsize=9.5, color=MUTED, style="italic")
    ax.set_xlim(-1.25, 1.25); ax.set_ylim(-1.15, 1.2)
    fig.tight_layout()
    p = out / f"incidence_{A}_{B}_{C}.png"
    fig.savefig(p, facecolor=PAPER, bbox_inches="tight"); plt.close(fig)
    print("wrote", p)


def main():
    ap = argparse.ArgumentParser(description="Weights and Venns from an incidence matrix.")
    ap.add_argument("matrix", help="incidence_matrix.csv (account, post, post, ...)")
    ap.add_argument("accounts", nargs="+", help="accounts to compare (2 or 3)")
    ap.add_argument("--out", default=None,
                    help="output dir (default ~/Desktop/claude/<today>/<handle>, "
                         "handle from $AGENT_HANDLE or 'opencode')")
    args = ap.parse_args()

    sets = load_matrix(args.matrix)
    missing = [a for a in args.accounts if a not in sets]
    if missing:
        raise SystemExit(f"not in matrix: {missing}\naccounts present: {list(sets)[:40]}...")
    names = sorted(args.accounts, key=lambda a: -len(sets[a]))  # biggest first
    if len(names) not in (2, 3):
        raise SystemExit("give 2 or 3 accounts")

    handle = os.environ.get("AGENT_HANDLE") or "opencode"
    out = Path(args.out) if args.out else Path.home() / "Desktop/claude" / str(date.today()) / handle
    out.mkdir(parents=True, exist_ok=True)

    print(f"matrix: {args.matrix}  ({len(sets)} accounts)")
    for a in names:
        print(f"  |{a}| = {len(sets[a])}")
    lines = [f"# {args.matrix}"]
    for a, b in itertools.combinations(names, 2):
        n = len(sets[a] & sets[b])
        print(f"  {a} ∩ {b} = {n}")
        lines.append(f"{a}\t{b}\t{n}")
    if len(names) == 3:
        A, B, C = names
        nAB = len(sets[A] & sets[B]); nAC = len(sets[A] & sets[C]); nBC = len(sets[B] & sets[C])
        abc = len(sets[A] & sets[B] & sets[C])
        regions = {
            (A,): len(sets[A]) - nAB - nAC + abc,
            (B,): len(sets[B]) - nAB - nBC + abc,
            (C,): len(sets[C]) - nAC - nBC + abc,
            (A, B): nAB - abc, (A, C): nAC - abc, (B, C): nBC - abc,
            (A, B, C): abc,
        }
        print(f"  {A} ∩ {B} ∩ {C} = {abc}")
        print(f"  {A} ∪ {B} ∪ {C} = {len(sets[A] | sets[B] | sets[C])}")
        for k, v in regions.items():
            print(f"    only {'+'.join(k)}: {v}")
            lines.append("only:" + "+".join(k) + "\t" + str(v))
        draw3(names, sets, regions, out)
    else:
        draw2(names, sets, len(sets[names[0]] & sets[names[1]]), out)

    tsv = out / f"incidence_{'_'.join(names)}.tsv"
    tsv.write_text("\n".join(lines) + "\n")
    print("wrote", tsv)


if __name__ == "__main__":
    main()
