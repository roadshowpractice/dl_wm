#!/usr/bin/env python3
"""Transcribe local media files with faster-whisper (CTranslate2 backend).

Alternate transcription engine caller, same CLI contract as
bin/transcribe_media.py (see lib/transcribe_common.py). Added 2026-09-18
because openai-whisper (PyTorch) was repeatedly getting killed for memory on
this machine (3.2GB RAM) transcribing a 100-minute video, even chunked down
to 20-minute pieces. faster-whisper uses CTranslate2 instead of PyTorch —
notably lower memory footprint and ~4x faster on CPU for the same model
size, at the same accuracy (it runs the same Whisper model weights, just a
different inference engine).

To use this as the pipeline's default transcription caller instead of
bin/transcribe_media.py, set in conf/app_config.json:
    "transcription": {"caller_command": "python bin/transcribe_media_faster_whisper.py {input} --outdir <dir> --srt --no-txt"}
Or invoke it directly per-video, same arguments as transcribe_media.py:
    python bin/transcribe_media_faster_whisper.py INPUT.mp4 --outdir OUTDIR --srt --no-txt
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)
LIB_DIR = os.path.join(ROOT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.append(LIB_DIR)

from transcribe_common import run_cli  # noqa: E402  (path setup must precede this)

DEFAULT_MODEL = "base"

_LOADED_MODELS: dict[str, Any] = {}


def _get_model(model_name: str):
    from faster_whisper import WhisperModel

    if model_name not in _LOADED_MODELS:
        # int8 compute type: lowest memory footprint on CPU, the whole point
        # of using faster-whisper here over openai-whisper's PyTorch/FP32 path.
        _LOADED_MODELS[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _LOADED_MODELS[model_name]


def transcribe_one(
    audio_path: str,
    *,
    model_name: str,
    language: Optional[str],
    task: str,
) -> dict[str, Any]:
    model = _get_model(model_name)
    segments_iter, info = model.transcribe(
        audio_path,
        task=task,
        language=language,
        word_timestamps=True,
    )

    segments: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for seg in segments_iter:
        words = None
        if seg.words:
            words = [
                {"word": w.word, "start": w.start, "end": w.end}
                for w in seg.words
            ]
        segments.append(
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": words,
            }
        )
        if seg.text and seg.text.strip():
            text_parts.append(seg.text.strip())

    return {
        "text": "\n".join(text_parts).strip(),
        "segments": segments,
        "language": getattr(info, "language", None),
    }


def faster_whisper_version() -> Optional[str]:
    try:
        import faster_whisper

        return getattr(faster_whisper, "__version__", None)
    except Exception:
        return None


def main(argv: Optional[list[str]] = None) -> int:
    return run_cli(
        argv,
        engine="faster_whisper",
        default_model=DEFAULT_MODEL,
        description="Run faster-whisper (CTranslate2) transcription from a local media file path.",
        transcribe_one=transcribe_one,
        engine_version_fn=faster_whisper_version,
    )


if __name__ == "__main__":
    raise SystemExit(main())
