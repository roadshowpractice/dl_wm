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
  collab_graph.png   the picture, always with a key (John's standing rule for every graph).
                     Line colour (and width) = band of shared posts, faint blue 1 -> near-white 100+;
                     dot size = shared posts; gold = scraped, grey = only seen as a collaborator
  collab_graph.html  the picture plus both tables, one local file (open in a browser)
  history/           a dated copy of every drawing: <date_time>_<accounts>a_<links>l_collab_graph.png
                     (+ its edges.tsv / nodes.tsv), since the files above are overwritten each run

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


# Edge colour = how many posts the two accounts share, in bands (John's rule: edges defined by
# colour, always with a key; no numbers on the lines). One hue, faint -> bright on the dark
# background (ordinal blue ramp from the dataviz palette, checked: faintest 2.25:1 on #12151c,
# every neighbouring step >= 9.5 dE, colour-blind too). Width grows with the band as well.
EDGE_BANDS = [  # (lowest count in band, label, colour, width)
    (1, "1 shared post", "#184f95", 0.6),
    (2, "2-4 shared posts", "#256abf", 1.1),
    (5, "5-19 shared posts", "#3987e5", 1.8),
    (20, "20-99 shared posts", "#86b6ef", 2.8),
    (100, "100+ shared posts", "#cde2fb", 4.0),
]


def edge_band(n):
    """Index into EDGE_BANDS for a link seen on n posts."""
    return max(i for i, (lo, *_rest) in enumerate(EDGE_BANDS) if n >= lo)


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
                rec = posts.setdefault(code, {"people": set(), "taken_at": int(r.get("taken_at") or 0),
                                              "credited": set(), "seen_in": set(), "caption": ""})
                rec["people"] |= people
                # evidence: who Instagram credited on the post, and which scrape(s) it came from
                rec["credited"] |= {c.lower() for c in (r.get("collaborators") or [])}
                rec["seen_in"].add(acct)
                rec["caption"] = rec["caption"] or (r.get("caption") or "")
        counts[acct] = n
    return posts, counts


def build_edges(posts):
    edges = {}
    for code, rec in posts.items():
        for a, b in itertools.combinations(sorted(rec["people"]), 2):
            e = edges.setdefault((a, b), {"n": 0, "first": None, "last": None, "codes": [], "all_codes": []})
            e["n"] += 1
            t = rec["taken_at"]
            if t:
                e["first"] = t if e["first"] is None else min(e["first"], t)
                e["last"] = t if e["last"] is None else max(e["last"], t)
            if len(e["codes"]) < 3:
                e["codes"].append(code)
            e["all_codes"].append(code)
    return edges


def names_from_metadata(meta_dir=REPO / "metadata"):
    """{handle: (display name, source)} from downloaded posts: metadata title "Video by <handle>" + "uploader"."""
    found = {}
    for f in sorted(meta_dir.glob("instagram__*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        m = re.match(r"(?:Video|Post) by ([\w.]+)", d.get("video_title") or "")
        if m and d.get("uploader"):
            found.setdefault(m.group(1).lower(), (d["uploader"], f"metadata/{f.name} (uploader)"))
    return found


def read_names(path):
    """{handle: (display name, source)} from a file: handle<TAB>name<TAB>source. Overrides metadata."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip() and not line.startswith("#"):
            out[parts[0].strip().lower()] = (parts[1].strip(), parts[2].strip() if len(parts) > 2 else path)
    return out


def read_members(path):
    """{account: source note} from a membership file: one account per line, '# source' after it."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        acct, _, note = line.partition("#")
        acct = acct.strip().lower()
        if acct:
            out[acct] = note.strip()
    return out


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_evidence(out, files, posts, edges, members, argv, started):
    """Evidence package: every input fingerprinted, every link traced to every post, a manifest."""
    import getpass, platform, socket, subprocess
    import matplotlib, networkx
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ") if t else ""
    with open(out / "inputs.tsv", "w", encoding="utf-8") as fh:
        fh.write("account\tfile\tsha256\tbytes\tlines\tmodified_utc\n")
        for acct, path in sorted(files.items()):
            st = Path(path).stat()
            lines = sum(1 for l in open(path, encoding="utf-8") if l.strip())
            fh.write(f"{acct}\t{path}\t{sha256(path)}\t{st.st_size}\t{lines}\t"
                     f"{datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec='seconds')}\n")
    with open(out / "edge_posts.tsv", "w", encoding="utf-8") as fh:
        fh.write("a\tb\tshortcode\turl\tposted_utc\tcredited_collaborators\tseen_in_scrape_of\tcaption_start\n")
        for (a, b), e in sorted(edges.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
            for code in sorted(e["all_codes"], key=lambda c: posts[c]["taken_at"]):
                r = posts[code]
                fh.write(f"{a}\t{b}\t{code}\thttps://www.instagram.com/p/{code}/\t{day(r['taken_at'])}\t"
                         f"{','.join(sorted(r['credited']))}\t{','.join(sorted(r['seen_in']))}\t"
                         f"{r['caption'][:120].replace(chr(10), ' ').replace(chr(9), ' ')}\n")
    if members is not None:
        with open(out / "members.tsv", "w", encoding="utf-8") as fh:
            fh.write("account\tsource\tscraped_input\tin_graph\n")
            in_graph = {n for k in edges for n in k}
            for acct, note in members.items():
                fh.write(f"{acct}\t{note}\t{'y' if acct in files else ''}\t{'y' if acct in in_graph else ''}\n")
    git = lambda *a: subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout.strip()
    manifest = {
        "made_by": "bin/ig_collab_graph.py --evidence",
        "command": [sys.executable, str(Path(__file__).resolve()), *argv],
        "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": socket.gethostname(), "user": getpass.getuser(), "platform": platform.platform(),
        "python": platform.python_version(), "networkx": networkx.__version__, "matplotlib": matplotlib.__version__,
        "git_commit": git("rev-parse", "HEAD"), "git_dirty_files": [l for l in git("status", "--porcelain").splitlines()],
        "script_sha256": sha256(Path(__file__).resolve()),
        "rules": {
            "post": "one record per shortcode, merged across the input scrapes",
            "link": "two accounts are linked by a post when both are among {the scraped account} + {credited collaborators}",
            "weight": "number of distinct posts (shortcodes) linking the two accounts",
            "members": "with --members, only links whose BOTH ends are members are kept",
        },
        "outputs": {},
    }
    for f in sorted(out.iterdir()):
        if f.is_file() and f.name != "manifest.json":
            manifest["outputs"][f.name] = {"sha256": sha256(f), "bytes": f.stat().st_size}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


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


def draw(edges, scraped, out_png, label_top, title, names=None, label_all=False):
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
    band_of = {(a, b): edge_band(G[a][b]["weight"]) for a, b in G.edges}
    for i, (_lo, _label, colour, width) in enumerate(EDGE_BANDS):  # faint first, strong drawn on top
        es = [e for e, b in band_of.items() if b == i]
        if es:
            nx.draw_networkx_edges(G, pos, ax=ax, edgelist=es, width=width, edge_color=colour, alpha=0.9)
    sizes = [60 + 40 * strength[n] ** 0.7 for n in G]
    colors = ["#e0b93a" if n in scraped else "#7d8798" for n in G]
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=sizes, node_color=colors, edgecolors="#12151c", linewidths=1)
    top = {n for n in G if n in scraped} | set(sorted((n for n in G if n not in scraped), key=lambda n: -strength[n])[:label_top])
    if label_all:
        top = set(G)
    names = names or {}
    labels = {n: (f"{names[n][0]}\n@{n}" if n in names else f"@{n}") if names else n for n in G if n in top}
    nx.draw_networkx_labels(G, pos, ax=ax, labels=labels, font_size=9,
                            font_color="#e6e8ee", font_family="DejaVu Sans")
    ax.set_title(title, color="#e6e8ee", fontsize=14, loc="left")
    # Key: ALWAYS (John's standing rule).
    from matplotlib.lines import Line2D
    band_counts = [sum(1 for v in band_of.values() if v == i) for i in range(len(EDGE_BANDS))]
    key = [
        Line2D([], [], marker="o", ls="", ms=11, mfc="#e0b93a", mec="#12151c", label="account we scraped"),
        Line2D([], [], marker="o", ls="", ms=11, mfc="#7d8798", mec="#12151c", label="only seen as a collaborator"),
        Line2D([], [], ls="", label="dot size = all shared posts for that account"),
        Line2D([], [], ls="", label=""),
        Line2D([], [], ls="", label="LINE COLOUR = posts the two accounts share"),
    ] + [
        Line2D([], [], color=colour, lw=max(width, 1.5) + 1, label=f"{label}  ({band_counts[i]} links)")
        for i, (_lo, label, colour, width) in enumerate(EDGE_BANDS)
    ]
    leg = ax.legend(handles=key, loc="upper left", bbox_to_anchor=(1.01, 1.0), title="Key", fontsize=9, title_fontsize=10,
                    facecolor="#1a1f29", edgecolor="#2e3544", labelcolor="#e6e8ee", framealpha=0.95)
    leg.get_title().set_color("#e6e8ee")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_png, facecolor=fig.get_facecolor(), bbox_inches="tight")  # keeps the key (outside the axes) in frame
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
    ap.add_argument("--inputs", default="", help="comma-separated scrape files to use INSTEAD of every scrape we have "
                    "(account = <account>_<date>/<account>_timeline.jsonl name or forensic folder name)")
    ap.add_argument("--members", help="membership file (one account per line, '# source' after it): keep only links "
                    "whose BOTH ends are members")
    ap.add_argument("--names", nargs="?", const="auto", help="label nodes 'Display Name / @handle': names from "
                    "downloaded-post metadata, plus/overridden by a TSV file (handle<TAB>name<TAB>source) if given")
    ap.add_argument("--label-all", action="store_true", help="label every node (small graphs)")
    ap.add_argument("--evidence", action="store_true", help="also write inputs.tsv (sha256 of every input), "
                    "edge_posts.tsv (every post behind every link), members.tsv and manifest.json")
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.inputs:
        files = {}
        for raw in args.inputs.split(","):
            p = Path(raw.strip()).expanduser().resolve()
            acct = (p.name[: -len("_timeline.jsonl")] if p.name.endswith("_timeline.jsonl")
                    else re.sub(r"_\d{4}-\d{2}-\d{2}.*$", "", p.parent.name))
            files[acct.lower()] = p
    else:
        files = account_files()
    posts, counts = load_posts(files)
    edges = build_edges(posts)
    exclude = {a.strip().lower() for a in args.exclude.split(",") if a.strip()}
    edges = {k: v for k, v in edges.items() if v["n"] >= args.min_posts and not (set(k) & exclude)}
    if args.only:
        only = {a.strip().lower() for a in args.only.split(",") if a.strip()}
        edges = {k: v for k, v in edges.items() if set(k) <= only}
    members = read_members(args.members) if args.members else None
    if members is not None:
        edges = {k: v for k, v in edges.items() if set(k) <= set(members)}
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
    if members is not None:
        title = f"Instagram co-posting — {Path(args.members).stem} ({len(members)} listed accounts) · {len(nodes)} accounts, {len(edges)} links · {date.today().isoformat()}"
    names = None
    if args.names:
        names = names_from_metadata()
        if args.names != "auto":
            names.update(read_names(args.names))
        with open(out / "names.tsv", "w", encoding="utf-8") as fh:
            fh.write("handle\tdisplay_name\tsource\n")
            for n in nodes:
                nm, src = names.get(n, ("", "no name in our data"))
                fh.write(f"{n}\t{nm}\t{src}\n")
    draw(edges, scraped, out / "collab_graph.png", args.label_top, title, names=names, label_all=args.label_all)

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
    if args.evidence:
        write_evidence(out, files, posts, edges, members, list(argv if argv is not None else sys.argv[1:]), started)

    # Dated copy of every drawing (John, 2026-10-04): the files above are overwritten each run,
    # history/ keeps each version: <date_time>_<accounts>a_<links>l.png plus its edges/nodes tables.
    import shutil
    hist = out / "history"
    hist.mkdir(exist_ok=True)
    stamp = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{len(nodes)}a_{len(edges)}l"
    for name in ("collab_graph.png", "edges.tsv", "nodes.tsv"):
        shutil.copy2(out / name, hist / f"{stamp}_{name}")
    print(f"{len(nodes)} accounts, {len(edges)} links -> {out}  (dated copy: history/{stamp}_collab_graph.png)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
