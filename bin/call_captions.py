#!/usr/bin/env python
import os
import subprocess
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from teton_utils import initialize_logging, load_app_config
from transcription_caller import run_transcription, update_task_for_media


def _escape_sub_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized.replace(":", "\\:").replace("'", "\\'")


def burn_subtitles(video_path: str, srt_path: str) -> str:
    base, ext = os.path.splitext(video_path)
    output_video = f"{base}.captioned{ext}"
    subtitle_filter = f"subtitles='{_escape_sub_path(srt_path)}'"
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", subtitle_filter, "-c:a", "copy", output_video]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg subtitle burn failed")
    return output_video


def main() -> int:
    logger = initialize_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python bin/call_captions.py <video_file_path> [--burn]")
        return 1

    input_video = sys.argv[1]
    if not os.path.isfile(input_video):
        logger.error("Input video file does not exist: %s", input_video)
        return 1

    app_config = load_app_config()
    captions_cfg = app_config.get("captions", {})
    force_burn = "--burn" in sys.argv[2:]
    burn_into_video = bool(captions_cfg.get("burn_into_video", False) or force_burn)

    base, _ = os.path.splitext(input_video)
    srt_path = f"{base}.srt"

    if not run_transcription(input_video, srt_path, "srt"):
        logger.error("Caption transcription failed for srt output: %s", srt_path)
        return 1

    update_task_for_media(input_video, "generate_captions", srt_path)
    logger.info("Caption file created: %s", srt_path)

    if burn_into_video:
        try:
            output_video = burn_subtitles(input_video, srt_path)
            logger.info("Captioned video created: %s", output_video)
            print(output_video)
            return 0
        except Exception as exc:
            logger.error("Failed to burn subtitles into video: %s", exc)
            return 1

    print(srt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
