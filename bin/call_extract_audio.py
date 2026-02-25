#!/usr/bin/env python
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from teton_utils import initialize_logging, load_app_config
from transcription_caller import run_transcription, update_task_for_media


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
