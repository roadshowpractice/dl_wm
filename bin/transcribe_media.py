#!/usr/bin/env python3
"""Transcribe local media files with openai-whisper, without scraping/snapshot workflows.

This is the default transcription engine caller (see conf/app_config.json's
transcription.caller_command). Other engines live alongside it as
bin/transcribe_media_<engine>.py, e.g. bin/transcribe_media_faster_whisper.py,
sharing the same CLI contract via lib/transcribe_common.py so any of them can
be swapped in without touching lib/transcription_caller.py or callers of it.
"""

from __future__ import annotations

import inspect
import os
import sys
from typing import Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)
LIB_DIR = os.path.join(ROOT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.append(LIB_DIR)

from transcribe_common import (  # noqa: E402  (path setup must precede this)
    build_minute_summary,
    format_timestamp,
    run_chunked_transcription,
    run_cli,
    srt_rows_from_segments,
    write_manifest,
    write_srt,
    write_vtt,
)

DEFAULT_MODEL = "base"

_LOADED_MODELS: dict[str, Any] = {}


def _get_model(model_name: str):
    import whisper

    if model_name not in _LOADED_MODELS:
        _LOADED_MODELS[model_name] = whisper.load_model(model_name)
    return _LOADED_MODELS[model_name]


def transcribe_one(
    audio_path: str,
    *,
    model_name: str,
    language: Optional[str],
    task: str,
) -> dict[str, Any]:
    model = _get_model(model_name)
    transcribe_kwargs: dict[str, Any] = {"task": task}
    if language:
        transcribe_kwargs["language"] = language
    try:
        signature = inspect.signature(model.transcribe)
    except (TypeError, ValueError):
        signature = None
    if signature and "word_timestamps" in signature.parameters:
        transcribe_kwargs["word_timestamps"] = True
        print("Whisper word_timestamps enabled for fine-grained subtitle timing.", file=sys.stderr)
    else:
        print(
            "Whisper word_timestamps not supported by the installed transcription stack; using native segment timings.",
            file=sys.stderr,
        )
    return model.transcribe(audio_path, **transcribe_kwargs)


def whisper_package_version() -> Optional[str]:
    try:
        import whisper

        return getattr(whisper, "__version__", None)
    except Exception:
        return None


def main(argv: Optional[list[str]] = None) -> int:
    return run_cli(
        argv,
        engine="whisper",
        default_model=DEFAULT_MODEL,
        description="Run Whisper transcription from a local media file path.",
        transcribe_one=transcribe_one,
        engine_version_fn=whisper_package_version,
    )


if __name__ == "__main__":
    raise SystemExit(main())
