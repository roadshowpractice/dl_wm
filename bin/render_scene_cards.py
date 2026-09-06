#!/usr/bin/env python3
"""Turn a scene_split.py output dir into review cards + forward/reverse JSONL.

Takes the segments.json + screenshots/clip_NN.jpg already produced by
bin/scene_split.py (screenshots are taken at each scene's midpoint) and:
  - renders one "card" per scene: that midpoint screenshot as the
    background, with the scene number burned on top (big, bold, a dark
    translucent bar behind it so it reads over any background)
  - writes scenes_forward.jsonl (chronological) and scenes_reverse.jsonl
    (reverse-chronological) — same records, just reordered, one JSON
    object per line, each with a card_path pointing at its rendered card

Usage:
    python3 bin/render_scene_cards.py <scene_clips_dir>
    (i.e. the --out-dir passed to, or defaulted by, scene_split.py —
    the directory containing segments.json, clips/, screenshots/)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "Inter-Bold.otf"


def render_card(screenshot_path: Path, scene_num: int, out_path: Path) -> None:
    im = Image.open(screenshot_path).convert("RGB")
    draw = ImageDraw.Draw(im, "RGBA")

    label = f"{scene_num:02d}"
    font_size = max(56, im.width // 6)
    font = ImageFont.truetype(str(FONT_PATH), font_size)

    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    x = (im.width - text_w) // 2
    y = int(im.height * 0.25)
    draw.text((x, y - bbox[1]), label, font=font, fill=(255, 20, 147, 255))

    im.save(out_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene_dir", help="scene_split.py output dir (contains segments.json, clips/, screenshots/)")
    args = parser.parse_args(argv)

    scene_dir = Path(args.scene_dir).expanduser().resolve()
    segments_path = scene_dir / "segments.json"
    screenshots_dir = scene_dir / "screenshots"
    cards_dir = scene_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)

    if not segments_path.exists():
        print(f"No segments.json in {scene_dir} — run bin/scene_split.py first", file=sys.stderr)
        return 1

    segments = json.loads(segments_path.read_text())

    records = []
    for i, seg in enumerate(segments, start=1):
        clip_id = seg["clip_id"]
        mid = (seg["start"] + seg["end"]) / 2
        screenshot = screenshots_dir / f"{clip_id}.jpg"
        card_path = cards_dir / f"{clip_id}_card.png"
        render_card(screenshot, i, card_path)
        records.append({
            "scene_num": i,
            "clip_id": clip_id,
            "start": seg["start"],
            "end": seg["end"],
            "midpoint": mid,
            "screenshot": str(screenshot),
            "card": str(card_path),
        })

    forward_path = scene_dir / "scenes_forward.jsonl"
    reverse_path = scene_dir / "scenes_reverse.jsonl"
    forward_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    reverse_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in reversed(records)))

    print(f"cards: {cards_dir} ({len(records)} rendered)")
    print(f"forward: {forward_path}")
    print(f"reverse: {reverse_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
