#!/usr/bin/env python3
from __future__ import annotations

import sys


def main() -> int:
    print(
        "short_srt.py has been disabled because it created synthetic subtitle timings by evenly splitting coarse SRT blocks. "
        "Regenerate subtitles from fine-grained transcription timing instead.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
