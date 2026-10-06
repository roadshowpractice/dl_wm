#!/usr/bin/env python3
"""Word-frequency histogram from one or more SRT files.

Usage:
  srt_word_histogram.py FILE.srt [MORE.srt ...] [-n 30] [-o OUT_PREFIX] [--all-words] [--pt] [--title TEXT]

Writes OUT_PREFIX_word_counts.txt and OUT_PREFIX_word_histogram.png
(default prefix: ~/Desktop/claude/<today>/analysis/<first SRT's name>). Several SRTs are counted together.
Every chart has a key, and a dated copy is kept in <prefix dir>/history/ (John's graph rule).
Ported into dl_wm 2026-10-05 from the 2026-09-30 one-off.
Common English filler words are dropped unless --all-words is given.
Needs matplotlib (dl_wm env: ~/miniforge3/envs/dl_wm/bin/python).
"""
import argparse, datetime, re, shutil, sys
from collections import Counter
from pathlib import Path

STOP = set("""
a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing don down during each even few for from further
get go going gonna got had has have having he her here hers herself him himself his how i if in into
is it its itself just know let like me more most my myself no nor not now of off on once only or other
our ours ourselves out over own really right said same say says see she should so some such than that
the their theirs them themselves then there these they this those through to too under until up us
very want was way we well were what when where which while who whom why will with would yeah yes you
your yours yourself yourselves okay ok oh um uh guys thing things one two also im youre dont thats
its theyre didnt doesnt isnt cant wont ive weve theyve hes shes whats theres lets gotta
ill id youll youve youd hed shed theyll wed wasnt werent arent havent hasnt wouldnt couldnt shouldnt
""".split())

STOP_PT = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para pra com sem sob
e ou mas que se como quando onde porque porquê pois então entao já ja não nao sim também tambem muito muita
mais menos só so eu tu ele ela nós nos vós eles elas você voce vocês voces me te lhe nos vos lhes meu minha
meus minhas seu sua seus suas nosso nossa isso isto aquilo esse essa este esta aquele aquela aqui ali lá la
é e foi ser era são sao está esta estão estao estava tem têm tinha ter há ha vai vou vamos fazer faz feito
ao aos à às ai aí né ne tá ta tipo coisa gente assim bem até ate mesmo quem qual todo toda todos todas
""".split())

STOP_ES = set("""
a al ante bajo con contra de del desde durante en entre hacia hasta mediante para por segun según sin sobre tras
el la los las lo un una unos unas y e o u ni pero sino que qué quien quién cual cuál como cómo cuando cuándo donde dónde
porque pues si sí no ya muy mas más menos tan tanto también tambien solo sólo aquí aqui allí alli ahí ahi
yo tu tú el él ella nosotros nosotras ustedes ellos ellas me te se nos les le mi mis su sus tu tus nuestro nuestra
este esta esto estos estas ese esa eso esos esas aquel aquella es son era fue ser está esta están estan estaba hay
ha han había habia tiene tienen tener hacer hace hizo va van vamos voy todo toda todos todas otro otra otros otras
cada mismo misma así asi bien entonces porque eh este pues
""".split())

TIMING = re.compile(r"^\d+:\d+:\d+[,.]\d+\s*-->")

def srt_text(path):
    lines = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.isdigit() or TIMING.match(s):
            continue
        lines.append(re.sub(r"<[^>]+>|\{[^}]+\}", "", s))  # drop <i> tags / ASS overrides
    return " ".join(lines)

def words(text):
    text = text.lower().replace("’", "'")
    return [w.replace("'", "") for w in re.findall(r"[a-z0-9\u00e0-\u00ff]+(?:'[a-z]+)?", text)]

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", nargs="+")
    ap.add_argument("-n", type=int, default=30, help="how many top words to plot (default 30)")
    ap.add_argument("-o", "--out", help="output prefix (default: first SRT path without .srt)")
    ap.add_argument("--all-words", action="store_true", help="keep filler words")
    ap.add_argument("--pt", action="store_true", help="also drop Portuguese filler words")
    ap.add_argument("--es", action="store_true", help="also drop Spanish filler words")
    ap.add_argument("--title", help="chart title")
    a = ap.parse_args()

    all_w = []
    for f in a.srt:
        all_w += words(srt_text(f))
    if not all_w:
        sys.exit("No words found. Check that the files are SRTs.")
    stop = STOP | (STOP_PT if a.pt else set()) | (STOP_ES if a.es else set())
    kept = all_w if a.all_words else [w for w in all_w if w not in stop and len(w) > 1 and not w.isdigit()]
    c = Counter(kept)
    top = c.most_common(a.n)

    out = Path(a.out).expanduser() if a.out else (
        Path.home() / "Desktop/claude" / datetime.date.today().isoformat() / "analysis" / Path(a.srt[0]).stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    txt = Path(f"{out}_word_counts.txt")
    png = Path(f"{out}_word_histogram.png")
    with txt.open("w") as fh:
        fh.write(f"total words: {len(all_w)}  unique {'words' if a.all_words else 'content words'}: {len(c)}\n")
        for w, n in c.most_common():
            fh.write(f"{n:4d}  {w}\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    labels = [w for w, _ in top][::-1]
    vals = [n for _, n in top][::-1]
    fig, ax = plt.subplots(figsize=(9, max(4, 0.32 * len(top) + 1.5)))
    bars = ax.barh(labels, vals, color="#1f4e8c")
    ax.bar_label(bars, padding=3, fontsize=9)
    ax.set_xlabel("times said")
    names = ", ".join(Path(f).name for f in a.srt)
    ax.set_title(a.title or f"Top {len(top)} words — {names}", fontsize=11, loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.margins(x=0.08)
    from matplotlib.patches import Patch
    key = [Patch(color="#1f4e8c", label=f"times the word is said, all {len(a.srt)} SRT(s) together ({len(all_w)} words total)")]
    if not a.all_words:
        key.append(Patch(color="none", label="filler words (the, and, you...) left out"))
    # key below the axis so it covers no bars
    ax.legend(handles=key, title="Key", loc="upper left", bbox_to_anchor=(0, -0.06 - 1.2 / max(4, len(top))),
              fontsize=8, title_fontsize=8, frameon=True)
    fig.tight_layout()
    fig.savefig(png, dpi=130)
    hist = png.parent / "history"
    hist.mkdir(exist_ok=True)
    dated = hist / f"{png.stem}_{datetime.datetime.now():%Y-%m-%d_%H%M%S}.png"
    shutil.copy2(png, dated)
    print(f"{txt}\n{png}\n{dated}")

if __name__ == "__main__":
    main()
