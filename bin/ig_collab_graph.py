#!/usr/bin/env python3
"""Graph of who co-posts with whom, built from every Instagram scrape we have.

Reads outputs/ig_timelines/ (profile_history timelines, forensic captures, and the
older flat <account>.jsonl files; the newest non-empty one per account). Every post
links its account with each collaborator credited on it, and the collaborators with
each other. A post seen in several accounts' scrapes (co-authored posts show up in
each partner's grid) is counted once, by shortcode.

Writes to ~/Desktop/claude/<today>/analysis/collab_graph/ (or --out):
  edges.tsv          a, b, shared_posts, first, last, example shortcodes
  nodes.tsv          account, scraped (y/n), posts_scraped, partners, shared_posts
  collab_graph.png   the picture: node size = shared posts, line width = shared posts,
                     dark nodes = accounts we have scraped, light = only seen as collaborators
  collab_graph.html  the picture plus both tables, one local file (open in a browser)

Usage:
    python bin/ig_collab_graph.py
    python bin/ig_collab_graph.py --center hiddenwarmovie --depth 2
    python bin/ig_collab_graph.py --min-posts 2 --exclude yourimaginationisreal
    python bin/ig_collab_graph.py --only hiddenwarmovie,timballard89,spanglishmoviesofficial
    python bin/ig_collab_graph.py --touching hiddenwarmovie,timballard89     (these accounts + their partners)

    --center A --depth N   only accounts within N links of A (default depth 1)
    --min-posts N          drop links seen on fewer than N posts (default 1)
    --label-top N          name scraped accounts plus the N busiest others (default 25)
"""
import argparse
import base64
import collections
import html
import itertools
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TIMELINES = REPO / "outputs" / "ig_timelines"


def account_files(root=TIMELINES):
    """{account: newest non-empty jsonl} for every account under root."""
    found = collections.defaultdict(list)
    for p in root.glob("*_*/*_timeline.jsonl"):
        found[p.name[: -len("_timeline.jsonl")]].append(p)
    for p in root.glob("*_forensic*/posts.jsonl"):
        found[re.sub(r"_\d{4}-\d{2}-\d{2}.*$", "", p.parent.name)].append(p)
    for p in root.glob("*.jsonl"):
        found[p.stem].append(p)
    out = {}
    for acct, paths in found.items():
        paths = [p for p in paths if p.stat().st_size > 0]
        if paths:
            out[acct.lower()] = max(paths, key=lambda p: p.stat().st_mtime)
    return out


def load_posts(files):
    """{shortcode: {"people": set, "taken_at": int}} merged across all accounts' scrapes."""
    posts = {}
    counts = {}
    for acct, path in files.items():
        n = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                code = r.get("shortcode") or r.get("code")
                if not code:
                    continue
                n += 1
                people = {acct} | {c.lower() for c in (r.get("collaborators") or [])}
                rec = posts.setdefault(code, {"people": set(), "taken_at": int(r.get("taken_at") or 0)})
                rec["people"] |= people
        counts[acct] = n
    return posts, counts


def build_edges(posts):
    edges = {}
    for code, rec in posts.items():
        for a, b in itertools.combinations(sorted(rec["people"]), 2):
            e = edges.setdefault((a, b), {"n": 0, "first": None, "last": None, "codes": []})
            e["n"] += 1
            t = rec["taken_at"]
            if t:
                e["first"] = t if e["first"] is None else min(e["first"], t)
                e["last"] = t if e["last"] is None else max(e["last"], t)
            if len(e["codes"]) < 3:
                e["codes"].append(code)
    return edges


def neighborhood(edges, center, depth):
    keep, frontier = {center}, {center}
    adj = collections.defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    for _ in range(depth):
        frontier = {n for f in frontier for n in adj[f]} - keep
        keep |= frontier
    return keep


def day(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t else ""


def draw(edges, scraped, out_png, label_top, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    G = nx.Graph()
    for (a, b), e in edges.items():
        G.add_edge(a, b, weight=e["n"])
    strength = dict(G.degree(weight="weight"))
    pos = nx.spring_layout(G, k=3.0 / max(len(G) ** 0.5, 1), iterations=300, seed=7, weight="weight")
    fig, ax = plt.subplots(figsize=(16, 12), dpi=110)
    fig.patch.set_facecolor("#12151c")
    ax.set_facecolor("#12151c")
    widths = [0.4 + 3.0 * (G[a][b]["weight"] / max(1, max(e["n"] for e in edges.values()))) ** 0.5 for a, b in G.edges]
    nx.draw_networkx_edges(G, pos, ax=ax, width=widths, edge_color="#5b6b85", alpha=0.6)
    sizes = [60 + 40 * strength[n] ** 0.7 for n in G]
    colors = ["#e0b93a" if n in scraped else "#7d8798" for n in G]
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=sizes, node_color=colors, edgecolors="#12151c", linewidths=1)
    top = {n for n in G if n in scraped} | set(sorted((n for n in G if n not in scraped), key=lambda n: -strength[n])[:label_top])
    nx.draw_networkx_labels(G, pos, ax=ax, labels={n: n for n in G if n in top}, font_size=9,
                            font_color="#e6e8ee", font_family="DejaVu Sans")
    ax.set_title(title, color="#e6e8ee", fontsize=14, loc="left")
    ax.text(0.0, -0.02, "gold = accounts scraped · grey = only seen as collaborators · "
            "size/width = shared posts", transform=ax.transAxes, color="#a2a9b8", fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_png, facecolor=fig.get_facecolor())
    plt.close(fig)
    return strength


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--center")
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--min-posts", type=int, default=1)
    ap.add_argument("--exclude", default="", help="comma-separated accounts to leave out")
    ap.add_argument("--only", default="", help="comma-separated: keep links among these accounts only")
    ap.add_argument("--touching", default="", help="comma-separated: keep links with at least one end in these accounts")
    ap.add_argument("--label-top", type=int, default=25, help="also name the N busiest unscraped accounts (scraped ones are always named)")
    ap.add_argument("--out", help="output folder")
    args = ap.parse_args(argv)

    files = account_files()
    posts, counts = load_posts(files)
    edges = build_edges(posts)
    exclude = {a.strip().lower() for a in args.exclude.split(",") if a.strip()}
    edges = {k: v for k, v in edges.items() if v["n"] >= args.min_posts and not (set(k) & exclude)}
    if args.only:
        only = {a.strip().lower() for a in args.only.split(",") if a.strip()}
        edges = {k: v for k, v in edges.items() if set(k) <= only}
    if args.touching:
        touching = {a.strip().lower() for a in args.touching.split(",") if a.strip()}
        edges = {k: v for k, v in edges.items() if set(k) & touching}
    if args.center:
        keep = neighborhood(edges, args.center.lower(), args.depth)
        edges = {k: v for k, v in edges.items() if set(k) <= keep}
    if not edges:
        print("no links left after filtering")
        return 1

    out = Path(args.out) if args.out else Path.home() / "Desktop" / "claude" / date.today().isoformat() / "analysis" / "collab_graph"
    out.mkdir(parents=True, exist_ok=True)
    scraped = set(files)
    nodes = sorted({n for k in edges for n in k})
    shared = collections.Counter()
    partners = collections.Counter()
    for (a, b), e in edges.items():
        shared[a] += e["n"]; shared[b] += e["n"]
        partners[a] += 1; partners[b] += 1

    with open(out / "edges.tsv", "w", encoding="utf-8") as fh:
        fh.write("a\tb\tshared_posts\tfirst\tlast\texamples\n")
        for (a, b), e in sorted(edges.items(), key=lambda kv: -kv[1]["n"]):
            fh.write(f"{a}\t{b}\t{e['n']}\t{day(e['first'])}\t{day(e['last'])}\t{','.join(e['codes'])}\n")
    with open(out / "nodes.tsv", "w", encoding="utf-8") as fh:
        fh.write("account\tscraped\tposts_scraped\tpartners\tshared_posts\n")
        for n in sorted(nodes, key=lambda n: -shared[n]):
            fh.write(f"{n}\t{'y' if n in scraped else 'n'}\t{counts.get(n, '')}\t{partners[n]}\t{shared[n]}\n")

    scope = (f"around {args.center} (depth {args.depth})" if args.center
             else f"{len(args.touching.split(','))} accounts and their partners" if args.touching
             else "all scraped accounts")
    title = f"Instagram co-posting — {scope} · {len(nodes)} accounts, {len(edges)} links · {date.today().isoformat()}"
    draw(edges, scraped, out / "collab_graph.png", args.label_top, title)

    png64 = base64.b64encode((out / "collab_graph.png").read_bytes()).decode()
    def table(path):
        rows = (out / path).read_text(encoding="utf-8").splitlines()
        head, body = rows[0].split("\t"), [r.split("\t") for r in rows[1:]]
        return ("<table><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in head) + "</tr>" +
                "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in body) + "</table>")
    page = f"""<!doctype html><meta charset="utf-8"><title>Collab graph</title>
<style>body{{background:#12151c;color:#e6e8ee;font:14px/1.4 system-ui,sans-serif;margin:24px}}
img{{max-width:100%}}table{{border-collapse:collapse;margin:12px 0 32px}}td,th{{border-bottom:1px solid #2e3544;padding:4px 10px;text-align:left}}
th{{color:#a2a9b8}}h2{{margin-top:32px}}</style>
<h1>{html.escape(title)}</h1>
<p>Sources: {len(files)} scrapes in outputs/ig_timelines/ · {len(posts)} unique posts · made by bin/ig_collab_graph.py</p>
<img src="data:image/png;base64,{png64}">
<h2>Accounts</h2>{table("nodes.tsv")}<h2>Links</h2>{table("edges.tsv")}"""
    (out / "collab_graph.html").write_text(page, encoding="utf-8")
    print(f"{len(nodes)} accounts, {len(edges)} links -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
