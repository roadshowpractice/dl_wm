#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SRTBlock:
    index: int
    start_ms: int
    end_ms: int
    text: str


TIME_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)


def die(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    raise SystemExit(1)


def parse_ts(ts: str) -> int:
    h, m, s_ms = ts.split(":", 2)
    s, ms = s_ms.split(",")
    return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)


def fmt_ms(ms: int) -> str:
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(path: Path):
    blocks = []
    raw = path.read_text(encoding="utf-8").strip().split("\n\n")
    for chunk in raw:
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        if len(lines) < 2:
            continue

        if lines[0].isdigit():
            time_line = lines[1]
            text_lines = lines[2:]
        else:
            time_line = lines[0]
            text_lines = lines[1:]

        m = TIME_RE.match(time_line)
        if not m:
            continue

        start = parse_ts(f"{m.group(1)}:{m.group(2)}:{m.group(3)},{m.group(4)}")
        end = parse_ts(f"{m.group(5)}:{m.group(6)}:{m.group(7)},{m.group(8)}")

        text = " ".join(text_lines).strip()
        if not text:
            continue

        blocks.append(SRTBlock(len(blocks)+1, start, end, text))

    return blocks


def shorten(blocks, max_words=3):
    out = []
    for b in blocks:
        words = b.text.split()
        if not words:
            continue

        chunks = [words[i:i+max_words] for i in range(0, len(words), max_words)]
        dur = b.end_ms - b.start_ms
        step = max(1, dur // len(chunks))

        t = b.start_ms
        for chunk in chunks:
            end = min(b.end_ms, t + step)
            out.append(SRTBlock(len(out)+1, t, end, " ".join(chunk)))
            t = end

    return out


def write_srt(path: Path, blocks):
    lines = []
    for i, b in enumerate(blocks, 1):
        lines.append(str(i))
        lines.append(f"{fmt_ms(b.start_ms)} --> {fmt_ms(b.end_ms)}")
        lines.append(b.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    if len(sys.argv) != 3:
        die("Usage: short_srt.py in.srt out.srt")

    inp = Path(sys.argv[1])
    out = Path(sys.argv[2])

    if not inp.exists():
        die(f"Missing input: {inp}")

    blocks = parse_srt(inp)
    short = shorten(blocks)
    write_srt(out, short)

    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
