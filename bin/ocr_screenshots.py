#!/usr/bin/env python3
"""Pull text out of desktop screenshots (1366x768 full-screen captures) with Tesseract.

Screen text at 1366x768 is ~12px tall, well under what Tesseract reads well, so each
image is upscaled (default 2.5x) and converted to grayscale first. Tesseract's word
boxes are then grouped back into its own blocks and lines, words under --min-conf are
dropped (stray icons and UI glyphs come back as low-confidence junk), and each block
keeps its position on the original screenshot so captions, usernames and sidebars can
be told apart afterwards.

Usage:
    python bin/ocr_screenshots.py <image-or-dir> [more ...] [--out DIR] [--lang eng+spa+por]
                                  [--crop LEFT,TOP,RIGHT,BOTTOM] [--scale 2.5] [--min-conf 50]

Instagram screenshots (Chrome, 1366x768, post open in the two-pane view) are also read
region by region, because whole-screen OCR merges the photo's own text into the
caption. The URL bar gives the page kind and shortcode, and the caption panel's first
line is the author header, which is either "a and b" (a post with Collaborators) or
"a • Follow" (single author):
    "instagram": {"kind": "post_with_collaborators" | "post" | "profile", "url",
                  "shortcode", "authors": [...], "header", "caption", "image_text"}
The rectangles are found per screenshot by find_instagram_layout (the caption panel
moves sideways with the photo's shape); --draw-boxes writes a copy with them drawn on.
Other screen sizes skip this step.

Writes, per image, <out>/<image stem>.ocr.txt (blocks separated by a blank line), plus
<out>/ocr.jsonl with one record per image:
    {"file", "taken_at" (from a Screenshot_YYYY-MM-DD_HH-MM-SS name), "width", "height",
     "blocks": [{"bbox": [x, y, w, h], "conf", "text"}], "text"}
--out defaults to the input directory. Needs the tesseract binary (apt tesseract-ocr,
plus tesseract-ocr-spa / -por) and pytesseract in the dl_wm env.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

# Importing cv2 points LD_LIBRARY_PATH at the conda env's lib/, and the system
# tesseract binary then loads conda's libcurl, warns on stderr, and pytesseract
# fails parsing its version. cv2 has already loaded its libs, so drop it.
_ld = [p for p in os.environ.get("LD_LIBRARY_PATH", "").split(":") if p and "site-packages/cv2" not in p]
if _ld:
    os.environ["LD_LIBRARY_PATH"] = ":".join(_ld)
else:
    os.environ.pop("LD_LIBRARY_PATH", None)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
NAME_TIME = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})")


# Chrome's URL bar on a 1366x768 screen is browser UI, so it doesn't move.
INSTAGRAM_SIZE = (1366, 768)
URL_BAR_TOP = 78
URL_BAR_BOTTOM = 112
# Grayscale values measured on John's screenshots (2026-10-03).
OVERLAY_GRAY = 86       # dimmed page behind an open post
PANEL_WHITE = 245       # caption panel background is 255
DIVIDER_MAX = 244       # thin rules inside the panel are a little darker than white
URL_RE = re.compile(r"instagram\.com/(?:(p|reel)/([A-Za-z0-9_-]+)|([A-Za-z0-9._]+))")
USERNAME_RE = re.compile(r"[A-Za-z0-9._]{2,30}")


def find_instagram_layout(gray):
    """Locate the open post's rectangles on a 1366x768 screenshot, by pixels.

    The post photo's width changes with its shape, which moves the caption panel
    sideways, so nothing here is a fixed box except the URL bar. Returns None when
    no caption panel is found (profile page, not Instagram, etc.).

        url bar  : url_top .. url_bottom (fixed)
        photo    : image_left .. image_right, modal_top .. modal_bottom
        panel    : panel_left .. panel_right, modal_top .. modal_bottom
        header   : modal_top .. header_bottom (author line; "a and b" = Collaborators)
        caption  : header_bottom .. caption_bottom (caption + comments)
    """
    height, width = gray.shape
    if (width, height) != INSTAGRAM_SIZE:
        return None
    url_top, url_bottom = URL_BAR_TOP, URL_BAR_BOTTOM

    # Panel columns: white in the middle of almost every row below the URL bar.
    white_cols = np.flatnonzero(np.median(gray[url_bottom + 8:height - 25], axis=0) >= PANEL_WHITE)
    if white_cols.size == 0:
        return None
    col_runs = np.split(white_cols, np.flatnonzero(np.diff(white_cols) != 1) + 1)
    panel_cols = max(col_runs, key=len)
    panel_left, panel_right = int(panel_cols[0]), int(panel_cols[-1])
    if panel_right - panel_left < 300:
        return None

    # Panel rows: follow a text-free margin column near the panel's right edge.
    margin_x = panel_right - 6
    margin = gray[:, margin_x]
    bright = np.flatnonzero(margin[url_bottom:] >= 200) + url_bottom
    row_runs = np.split(bright, np.flatnonzero(np.diff(bright) > 3) + 1)
    panel_rows = max(row_runs, key=len)
    modal_top, modal_bottom = int(panel_rows[0]), int(panel_rows[-1])

    # Divider lines inside the panel: rows in the margin that dip below white.
    dividers = [y for y in range(modal_top + 10, modal_bottom - 10) if margin[y] <= DIVIDER_MAX]
    divider_rows = [y for i, y in enumerate(dividers) if i == 0 or y - dividers[i - 1] > 2]
    header_bottom = divider_rows[0] if divider_rows else modal_top + 64
    caption_bottom = divider_rows[1] if len(divider_rows) > 1 else modal_bottom

    # Photo: from where the dimmed overlay ends (mid-height row) to the panel.
    mid_y = (modal_top + modal_bottom) // 2
    row = gray[mid_y, :panel_left].astype(int)
    is_overlay = np.abs(row - OVERLAY_GRAY) <= 3
    image_left = 0
    for x in range(panel_left - 1, -1, -1):
        if is_overlay[max(0, x - 19):x + 1].all():
            image_left = x + 1
            break
    image_right = panel_left - 1

    return {
        "url_top": url_top, "url_bottom": url_bottom,
        "modal_top": modal_top, "modal_bottom": modal_bottom,
        "image_left": image_left, "image_right": image_right,
        "panel_left": panel_left, "panel_right": panel_right,
        "header_top": modal_top, "header_bottom": header_bottom,
        "caption_top": header_bottom, "caption_bottom": caption_bottom,
    }


def collect_images(paths):
    images = []
    for p in map(Path, paths):
        if p.is_dir():
            images.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS))
        elif p.suffix.lower() in IMAGE_EXTS:
            images.append(p)
    return images


def taken_at_from_name(name):
    m = NAME_TIME.search(name)
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}" if m else None


def prepare(path, crop, scale):
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"could not read image: {path}")
    height, width = img.shape[:2]
    x0, y0 = 0, 0
    if crop:
        left, top, right, bottom = crop
        x0, y0 = left, top
        img = img[top:height - bottom, left:width - right]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return big, (width, height), (x0, y0)


def ocr_region(gray_full, box, lang, min_conf, scale):
    left, top, right, bottom = box
    crop = gray_full[top:bottom, left:right]
    big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return ocr_blocks(big, lang, min_conf, scale, (left, top))


def parse_header(line):
    """Author header of the caption panel -> (authors, has_collaborators).
    "matthewcooper $ and timballard89 &" -> two authors (badge glyphs dropped);
    "ms timballard89 & + Follow ..." -> one author."""
    line = re.split(r"\bFollow(ing)?\b|[•·]", line)[0]
    # 3+ collaborators: "first and 2 others" — only the first name is on screen;
    # the full list is in Instagram's Collaborators pop-up (see collaborators_list).
    if re.search(r"\band\s+\d+\s+others?\b", line):
        first = _first_username(re.split(r"\band\b", line, maxsplit=1)[0])
        return ([first] if first else []), True
    if re.search(r"\band\b", line):
        left, right = re.split(r"\band\b", line, maxsplit=1)
        names = [_last_username(left), _first_username(right)]
        authors = [n for n in names if n]
        return authors, len(authors) > 1
    name = _longest_username(line)
    return ([name] if name else []), False


def _usernames(text):
    return [u for u in USERNAME_RE.findall(text) if not u.isdigit()]


def _first_username(text):
    names = _usernames(text)
    return names[0] if names else None


def _last_username(text):
    names = _usernames(text)
    return names[-1] if names else None


def _longest_username(text):
    names = _usernames(text)
    return max(names, key=len) if names else None


def collaborators_list(gray, lang, min_conf, scale):
    """Instagram's "Collaborators" pop-up: a title line, then for each person a
    username line (with verified badge) followed by their display name.
    Returns [{"username", "name"}] or None when the pop-up isn't on screen."""
    height, width = gray.shape
    blocks = ocr_region(gray, (0, URL_BAR_BOTTOM, width, height), lang, min_conf, scale)
    lines = [ln.strip() for b in blocks for ln in b["text"].splitlines() if ln.strip()]
    try:
        start = next(i for i, ln in enumerate(lines) if ln.lower().startswith("collaborators"))
    except StopIteration:
        return None
    people = []
    rest = lines[start + 1:]
    i = 0
    while i < len(rest):
        names = _usernames(rest[i])
        # username lines are a single lowercase handle (plus badge junk)
        if names and names[0] == names[0].lower() and len(names[0]) >= 3:
            display = rest[i + 1] if i + 1 < len(rest) and not _looks_like_handle(rest[i + 1]) else ""
            people.append({"username": names[0], "name": display})
            i += 2 if display else 1
        else:
            i += 1
    return people or None


def _looks_like_handle(line):
    names = _usernames(line)
    return bool(names) and names[0] == names[0].lower() and len(line.split()) <= 3 and len(names[0]) >= 3


def instagram_fields(path, lang, min_conf, scale):
    gray = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2GRAY)
    if (gray.shape[1], gray.shape[0]) != INSTAGRAM_SIZE:
        return None
    width = gray.shape[1]
    url_box = (0, URL_BAR_TOP, width, URL_BAR_BOTTOM)
    url_text = " ".join(b["text"] for b in ocr_region(gray, url_box, lang, 0, scale))
    m = URL_RE.search(url_text)
    if not m:
        return None
    if not m.group(2):
        return {"kind": "profile", "url": m.group(0), "username": m.group(3)}

    layout = find_instagram_layout(gray)
    if not layout:
        # Instagram's Collaborators pop-up covers the post: read the whole screen
        # and pull the list out of it.
        listing = collaborators_list(gray, lang, min_conf, scale)
        if listing:
            return {"kind": "collaborators_list", "url": m.group(0), "shortcode": m.group(2),
                    "shortcode_complete": len(m.group(2)) >= 11,
                    "authors": [c["username"] for c in listing], "collaborators": listing}
        return {"kind": "post_unreadable_layout", "url": m.group(0), "shortcode": m.group(2)}
    header_box = (layout["panel_left"], layout["header_top"], layout["panel_right"] + 1, layout["header_bottom"])
    caption_box = (layout["panel_left"], layout["caption_top"], layout["panel_right"] + 1, layout["caption_bottom"])
    image_box = (layout["image_left"], layout["modal_top"], layout["image_right"] + 1, layout["modal_bottom"] + 1)

    header_blocks = ocr_region(gray, header_box, lang, min_conf, scale)
    header_lines = [ln for blk in header_blocks for ln in blk["text"].splitlines() if ln.strip()]
    # The avatar can OCR as a stray glyph line ("O"), so take the line that names
    # the author: one with "and"/"Follow", else the first with a username in it.
    marked = [ln for ln in header_lines if re.search(r"\band\b|Follow", ln)]
    named = [ln for ln in header_lines if _usernames(ln)]
    header = (marked or named or header_lines or [""])[0]
    authors, collab = parse_header(header)
    caption_blocks = ocr_region(gray, caption_box, lang, min_conf, scale)
    image_blocks = ocr_region(gray, image_box, lang, min_conf, scale)
    return {
        "kind": "post_with_collaborators" if collab else "post",
        "url": m.group(0),
        "shortcode": m.group(2),
        # Post shortcodes are 11 characters; shorter means the URL bar was cut
        # off or misread, so don't treat it as a real ID without checking.
        "shortcode_complete": len(m.group(2)) >= 11,
        "authors": authors,
        # "first and 2 others": collaborators not named on this screen
        "others_count": int(m_others.group(1)) if (m_others := re.search(r"\band\s+(\d+)\s+others?\b", header)) else 0,
        "header": header,
        "header_extra": [ln for ln in header_lines if ln != header],  # e.g. "Original audio" on reels
        "caption": "\n".join(blk["text"] for blk in caption_blocks),
        "image_text": "\n\n".join(blk["text"] for blk in image_blocks),
        "layout": layout,
    }


def draw_layout(path, layout, out_path):
    """Copy of the screenshot with the found rectangles drawn on, for checking by eye."""
    img = cv2.imread(str(path))
    L = layout
    boxes = [
        ("url", (0, L["url_top"], img.shape[1] - 1, L["url_bottom"]), (0, 160, 255)),
        ("image", (L["image_left"], L["modal_top"], L["image_right"], L["modal_bottom"]), (255, 0, 0)),
        ("header", (L["panel_left"], L["header_top"], L["panel_right"], L["header_bottom"]), (0, 0, 255)),
        ("caption", (L["panel_left"], L["caption_top"], L["panel_right"], L["caption_bottom"]), (0, 170, 0)),
    ]
    for name, (x1, y1, x2, y2), color in boxes:
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, name, (x1 + 4, y1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.imwrite(str(out_path), img)


def ocr_blocks(img, lang, min_conf, scale, offset):
    data = pytesseract.image_to_data(img, lang=lang, config="--psm 3", output_type=Output.DICT)
    blocks = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        conf = float(data["conf"][i])
        if not word or conf < min_conf:
            continue
        key = data["block_num"][i]
        line_key = (data["par_num"][i], data["line_num"][i])
        x, y, w, h = (data[k][i] / scale for k in ("left", "top", "width", "height"))
        x, y = x + offset[0], y + offset[1]
        b = blocks.setdefault(key, {"lines": {}, "confs": [], "box": [x, y, x + w, y + h]})
        b["lines"].setdefault(line_key, []).append(word)
        b["confs"].append(conf)
        box = b["box"]
        box[0], box[1] = min(box[0], x), min(box[1], y)
        box[2], box[3] = max(box[2], x + w), max(box[3], y + h)

    out = []
    for key in sorted(blocks):
        b = blocks[key]
        text = "\n".join(" ".join(words) for _, words in sorted(b["lines"].items()))
        x1, y1, x2, y2 = b["box"]
        out.append({
            "bbox": [round(x1), round(y1), round(x2 - x1), round(y2 - y1)],
            "conf": round(sum(b["confs"]) / len(b["confs"]), 1),
            "text": text,
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="image files and/or directories of images")
    ap.add_argument("--out", help="output directory (default: the first input's directory)")
    ap.add_argument("--lang", default="eng+spa+por")
    ap.add_argument("--crop", help="pixels to cut from the original edges: LEFT,TOP,RIGHT,BOTTOM (e.g. browser chrome)")
    ap.add_argument("--scale", type=float, default=2.5)
    ap.add_argument("--min-conf", type=float, default=50)
    ap.add_argument("--draw-boxes", action="store_true", help="also write <stem>.boxes.png with the found rectangles")
    args = ap.parse_args()

    images = collect_images(args.inputs)
    if not images:
        print("no images found")
        return 1
    crop = [int(v) for v in args.crop.split(",")] if args.crop else None
    first = Path(args.inputs[0])
    out_dir = Path(args.out) if args.out else (first if first.is_dir() else first.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "ocr.jsonl").open("a", encoding="utf-8") as jsonl:
        for path in images:
            img, (width, height), offset = prepare(path, crop, args.scale)
            blocks = ocr_blocks(img, args.lang, args.min_conf, args.scale, offset)
            text = "\n\n".join(b["text"] for b in blocks)
            ig = instagram_fields(path, args.lang, args.min_conf, args.scale)
            if args.draw_boxes and ig and ig.get("layout"):
                draw_layout(path, ig["layout"], out_dir / f"{path.stem}.boxes.png")
            txt = text
            if ig and ig["kind"] == "collaborators_list":
                txt = (f"[collaborators_list] {ig['url']}\n" +
                       "\n".join(f"{c['username']}  ({c['name']})" for c in ig["collaborators"]))
            elif ig and ig.get("layout"):
                txt = (f"[{ig['kind']}] {ig['url']}{'' if ig['shortcode_complete'] else '  (shortcode looks cut off)'}\nauthors: {', '.join(ig['authors'])}\n\n"
                       f"CAPTION PANEL:\n{ig['caption']}\n\nON IMAGE:\n{ig['image_text']}")
            (out_dir / f"{path.stem}.ocr.txt").write_text(txt + "\n", encoding="utf-8")
            jsonl.write(json.dumps({
                "file": str(path), "taken_at": taken_at_from_name(path.name),
                "width": width, "height": height, "blocks": blocks, "text": text,
                "instagram": ig,
            }, ensure_ascii=False) + "\n")
            kind = f" [{ig['kind']}: {', '.join(ig.get('authors') or [ig.get('username') or ''])}]" if ig else ""
            print(f"{path.name}: {len(blocks)} blocks, {len(text.split())} words{kind}")
    print(f"written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
