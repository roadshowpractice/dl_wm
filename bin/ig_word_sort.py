#!/usr/bin/env python3
"""Word sort of an Instagram account's scraped post history (metadata only).

Reads what the scrapers write and counts what's in the captions:

  posts per month         when the account was active (and when it went quiet)
  collaborators           accounts co-credited on the post
  locations               place tags (forensic captures only)
  @mentions / #hashtags   pulled out of the caption text
  words / word pairs      caption words, EN/ES/PT stopwords removed

Inputs (any mix, one report per input):
  - a timeline from igp.profile_history:  outputs/ig_timelines/<user>_<date>/<user>_timeline.jsonl
  - a forensic capture from ig_scrape_account.py:  outputs/ig_timelines/<user>_<date>_forensic/posts.jsonl
  - the folder holding either one

profile_history keeps only the first ~200 characters of each caption. When most
captions stop at the same length, the report says so and drops the last word of
each cut caption (it's usually half a word or half a hashtag, e.g. "#thetru").
Forensic captures keep full captions.

Usage:
    python bin/ig_word_sort.py outputs/ig_timelines/hiddenwarmovie_2026-10-04
    python bin/ig_word_sort.py outputs/ig_timelines/*_2026-10-04 --top 60
    python bin/ig_word_sort.py <input> --out report.txt     (one input only)

Default output: ~/Desktop/claude/<today>/analysis/<user>_word_sort.txt
(the folder is created if missing). The report is also printed when --print is set.
"""
import argparse
import collections
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

STOPWORDS = set("""
a an the and or but if of to in on at by for with from as is are was were be been being it its it's this that
these those i i'm you you're he she we we're they they're me him her us them my your his our their what which who
whom how why when where not no so do does did don't have has had will would can could just than then there here
all any some more most very also into out up down over about after before again only own same too now get got
one two new back via let let's us dont im
el la los las un una unos unas y o pero de del al a en con por para que es son fue ser se lo le les su sus mi mis
tu tus te nos este esta estos estas ese esa eso más muy ya no sí si como cuando donde qué quien hay está están
todo todos toda todas también sin sobre entre hasta desde porque aún ha han e u ni me yo él ella ellos ellas
o os as um uma uns umas e em no na nos nas do da dos das ao aos à às com por para que é são foi ser se seu sua
seus suas meu minha mais muito já não sim como quando onde quem há está estão também sem sobre entre até desde
porque ele ela eles elas eu você vocês isso isto esse essa este esta
""".split())

WORD_RE = re.compile(r"[a-záéíóúâêôãõçñü]+(?:'[a-z]+)?")
TAG_RE = re.compile(r"#(\w+)")
MENTION_RE = re.compile(r"@([\w.]+)")
URL_RE = re.compile(r"https?://\S+")

# share of captions that must stop at the same length before we call it truncation
TRUNCATION_SHARE = 0.2


def find_input(path):
    """Return the jsonl file for a timeline/forensic file or the folder holding one."""
    p = Path(path)
    if p.is_file():
        return p
    if p.is_dir():
        for pattern in ("posts.jsonl", "*_timeline.jsonl", "*.jsonl"):
            hits = sorted(p.glob(pattern))
            if hits:
                return hits[0]
    raise FileNotFoundError(f"no posts.jsonl or *_timeline.jsonl in {path}")


def account_name(jsonl_path):
    """hiddenwarmovie_2026-10-04/hiddenwarmovie_timeline.jsonl -> hiddenwarmovie."""
    p = Path(jsonl_path)
    if p.name.endswith("_timeline.jsonl"):
        return p.name[: -len("_timeline.jsonl")]
    folder = p.parent.name
    return re.sub(r"_\d{4}-\d{2}-\d{2}.*$", "", folder) or p.stem


def load_posts(jsonl_path):
    """Read either scraper's records into one shape: code, taken_at, caption, collaborators, location."""
    posts = []
    with open(jsonl_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            loc = r.get("location")
            if isinstance(loc, dict):
                loc = loc.get("name")
            posts.append({
                "code": r.get("shortcode") or r.get("code"),
                "taken_at": int(r.get("taken_at") or 0),
                "caption": r.get("caption") or "",
                "collaborators": list(r.get("collaborators") or []),
                "location": loc or None,
            })
    return posts


def truncation_length(captions):
    """The length captions were cut at, or None if they weren't cut."""
    lengths = collections.Counter(len(c) for c in captions if c)
    if not lengths:
        return None
    longest = max(lengths)
    if longest >= 100 and lengths[longest] / len(captions) >= TRUNCATION_SHARE:
        return longest
    return None


def drop_cut_word(caption):
    """Remove the last (probably half) word of a truncated caption."""
    return re.sub(r"\S+$", "", caption)


def tokens(text):
    clean = URL_RE.sub(" ", text.lower())
    clean = TAG_RE.sub(" ", clean)
    clean = MENTION_RE.sub(" ", clean)
    return [w for w in WORD_RE.findall(clean) if w not in STOPWORDS and len(w) > 2]


def count(posts):
    """All the counters for one account."""
    captions = [p["caption"] for p in posts]
    cut_at = truncation_length(captions)
    c = {k: collections.Counter() for k in
         ("months", "collaborators", "locations", "mentions", "hashtags", "words", "pairs")}
    for p in posts:
        cap = p["caption"]
        if cut_at and len(cap) == cut_at:
            cap = drop_cut_word(cap)
        if p["taken_at"]:
            c["months"][datetime.fromtimestamp(p["taken_at"], timezone.utc).strftime("%Y-%m")] += 1
        c["collaborators"].update(p["collaborators"])
        if p["location"]:
            c["locations"][p["location"]] += 1
        c["hashtags"].update(t.lower() for t in TAG_RE.findall(cap))
        c["mentions"].update(m.lower().rstrip(".") for m in MENTION_RE.findall(cap))
        words = tokens(cap)
        c["words"].update(words)
        c["pairs"].update(f"{a} {b}" for a, b in zip(words, words[1:]))
    return c, cut_at


def render(account, src, posts, top):
    c, cut_at = count(posts)
    stamps = sorted(p["taken_at"] for p in posts if p["taken_at"])
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    with_caption = sum(1 for p in posts if p["caption"])
    out = [
        f"WORD SORT — {account}",
        f"source:  {src}",
        f"made:    {datetime.now(timezone.utc).isoformat(timespec='seconds')} by bin/ig_word_sort.py",
        f"posts:   {len(posts)}  ({with_caption} with a caption)"
        + (f"   span: {day(stamps[0])} .. {day(stamps[-1])}" if stamps else ""),
    ]
    if cut_at:
        out.append(f"NOTE:    captions are cut at {cut_at} characters by the scraper; counts cover the opening "
                   f"of each caption, and the last (half) word of each cut caption is dropped")
    out.append("")

    def block(title, counter, n, keep_order=False):
        if not counter:
            return
        out.append(f"== {title}   (unique {len(counter)}, total {sum(counter.values())})")
        items = sorted(counter.items()) if keep_order else counter.most_common(n)
        out.extend(f"{v:6d}  {k}" for k, v in items)
        out.append("")

    block("posts per month", c["months"], None, keep_order=True)
    block("collaborators on the post", c["collaborators"], top)
    block("locations", c["locations"], top)
    block("@mentions in caption", c["mentions"], top)
    block("#hashtags", c["hashtags"], top)
    block("words (EN/ES/PT stopwords removed)", c["words"], top * 3)
    pairs = collections.Counter({k: v for k, v in c["pairs"].items() if v > 1})
    block("word pairs (seen 2+ times)", pairs, top)
    return "\n".join(out)


def default_out(account):
    folder = Path.home() / "Desktop" / "claude" / date.today().isoformat() / "analysis"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{account}_word_sort.txt"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="timeline/posts jsonl files or the folders holding them")
    ap.add_argument("--out", help="report path (only with a single input)")
    ap.add_argument("--top", type=int, default=40, help="rows per section; words get 3x this (default 40)")
    ap.add_argument("--print", action="store_true", help="also print each report")
    args = ap.parse_args(argv)
    if args.out and len(args.inputs) > 1:
        ap.error("--out works with one input only")

    for raw in args.inputs:
        src = find_input(raw)
        account = account_name(src)
        report = render(account, src, load_posts(src), args.top)
        dest = Path(args.out) if args.out else default_out(account)
        dest.write_text(report + "\n", encoding="utf-8")
        print(f"{account}: {dest}")
        if args.print:
            print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
