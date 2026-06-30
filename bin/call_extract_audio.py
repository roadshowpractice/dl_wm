#!/usr/bin/env python
import os
import sys

import pathlib
_root = str(pathlib.Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from dl_wm.teton_utils import initialize_logging, load_app_config
from dl_wm.transcription_caller import run_transcription, update_task_for_media


def main() -> int:
    logger = initialize_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python bin/call_extract_audio.py <video_file_path>")
        return 1

    input_video = sys.argv[1]
    if not os.path.isfile(input_video):
        logger.error("Input video file does not exist: %s", input_video)
        return 1

    base, _ = os.path.splitext(input_video)
    txt_path = f"{base}.txt"

    load_app_config()  # Force app config parse early for clearer errors.
    if not run_transcription(input_video, txt_path, "txt"):
        logger.error("Transcription failed for txt output: %s", txt_path)
        return 1

    update_task_for_media(input_video, "extract_audio", txt_path)
    logger.info("Transcript created: %s", txt_path)
    print(txt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
