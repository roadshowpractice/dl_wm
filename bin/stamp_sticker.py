#!/usr/bin/env python3
"""Put the round WATCH BUTTFIRE sticker (or any transparent PNG) onto images going out.

    python bin/stamp_sticker.py card.png                      -> card_stamped.png, sticker in the emptiest corner
    python bin/stamp_sticker.py a.png b.png c.png --corner tl --size 0.18
    python bin/stamp_sticker.py card.png -o out.png --rotate 0

--corner   auto (default: a corner with nothing under the sticker) / br / bl / tr / tl
--size     sticker width as a fraction of the image's shorter side (default 0.22; with auto it shrinks,
           down to 0.12, until a corner is clear, and warns if none is)
--margin   gap from the edges, same units (default 0.03)
--rotate   degrees, a slight tilt reads as a sticker (default -8)
--sticker  another round transparent PNG (default assets/stickers/watch_buttfire.png)

Never overwrites the input: writes <name>_stamped.png next to it unless -o is given.
The sticker covers that corner. "auto" picks the calmest one, and prints which; check the result anyway.
Written 2026-10-06.
"""
import argparse
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
DEFAULT_STICKER = REPO / "assets" / "stickers" / "watch_buttfire.png"


def _place(W, H, w, h, m, corner):
    return (W - w - m if "r" in corner else m, H - h - m if "b" in corner else m)


def _ink(gray, box):
    """Share of pixels in box that differ from that box's own background (its most common grey)."""
    region = gray.crop(box)
    hist = region.histogram()
    bg = max(range(256), key=lambda v: hist[v])
    near = sum(hist[max(0, bg - 24):min(256, bg + 25)])
    return 1 - near / max(1, region.width * region.height)


def _sticker(path, px, rotate):
    st = Image.open(path).convert("RGBA").resize((px, px), Image.LANCZOS)
    return st.rotate(rotate, resample=Image.BICUBIC, expand=True) if rotate else st


def stamp(src, dst, sticker, corner="auto", size=0.22, margin=0.03, rotate=-8.0, min_size=0.12):
    base = Image.open(src).convert("RGBA")
    W, H = base.size
    short = min(base.size)
    m = int(short * margin)
    note = ""
    if corner == "auto":
        # try the requested size, then smaller, until some corner has (almost) nothing under the sticker
        gray = base.convert("L")
        sz = size
        while True:
            st = _sticker(sticker, max(1, int(short * sz)), rotate)
            scores = {c: _ink(gray, (*_place(W, H, st.width, st.height, m, c),
                                     _place(W, H, st.width, st.height, m, c)[0] + st.width,
                                     _place(W, H, st.width, st.height, m, c)[1] + st.height))
                      for c in ("br", "bl", "tr", "tl")}
            corner = min(scores, key=scores.get)
            if scores[corner] <= 0.001 or sz <= min_size:
                break
            sz = round(sz - 0.02, 3)
            corner = "auto"
        if scores[corner] > 0.001:
            note = f"  WARNING: covers {scores[corner]:.1%} non-background pixels even at size {sz}; check it"
        elif sz != size:
            note = f"  (shrunk to size {sz} to find a clear corner)"
    else:
        st = _sticker(sticker, max(1, int(short * size)), rotate)
    x, y = _place(W, H, st.width, st.height, m, corner)
    base.alpha_composite(st, (x, y))
    out = base if Path(dst).suffix.lower() == ".png" else base.convert("RGB")
    out.save(dst)
    return f"{dst}  (corner {corner}){note}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+")
    ap.add_argument("-o", "--out", help="output file (only with one input image)")
    ap.add_argument("--corner", default="auto", choices=["auto", "br", "bl", "tr", "tl"])
    ap.add_argument("--size", type=float, default=0.22)
    ap.add_argument("--margin", type=float, default=0.03)
    ap.add_argument("--rotate", type=float, default=-8.0)
    ap.add_argument("--sticker", default=str(DEFAULT_STICKER))
    a = ap.parse_args()
    if a.out and len(a.images) > 1:
        ap.error("-o works with one image; leave it out to write <name>_stamped.png for each")
    for img in a.images:
        p = Path(img)
        dst = Path(a.out) if a.out else p.with_name(f"{p.stem}_stamped{p.suffix}")
        if dst.resolve() == p.resolve():
            ap.error(f"refusing to overwrite the input: {p}")
        print(stamp(p, dst, a.sticker, a.corner, a.size, a.margin, a.rotate))


if __name__ == "__main__":
    main()
