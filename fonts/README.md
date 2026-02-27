# Fonts

This repository intentionally does not bundle proprietary font binaries.

If your configuration uses font paths like `fonts/InterVariable.ttf` or `fonts/Inter-Bold.ttf`,
copy the corresponding `.ttf`/`.otf` font files into this folder after cloning.

Notes:
- `.odf` is usually a typo for `.otf` (OpenType font files).
- `bin/call_watermark.py` now tries common extension fallbacks (`.ttf`/`.otf`/`.odf`) and then falls back to MoviePy font-name lookup.
