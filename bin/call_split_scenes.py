#!/usr/bin/env python
"""Router-callable wrapper around bin/scene_split.py.

Unlike the other default_tasks, this one needs the WATERMARKED video, not
the raw download the router passes as its positional arg (screenshots/clips
with no source watermark burned in aren't usable as evidence) - so this
looks up apply_watermark's completed output path in the item's metadata and
runs scene_split against that instead.
"""
import json
import os
import sys
from pathlib import Path

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)
if current_dir not in sys.path:
    sys.path.append(current_dir)

from teton_utils import initialize_logging
from transcription_caller import _metadata_path_for_media, update_task_for_media  # reused, not duplicated
import scene_split


def main() -> int:
    logger = initialize_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python bin/call_split_scenes.py <video_file_path>")
        return 1

    input_video = sys.argv[1]
    if not os.path.isfile(input_video):
        logger.error("Input video file does not exist: %s", input_video)
        return 1

    metadata_path = _metadata_path_for_media(input_video)
    if not metadata_path:
        logger.error("Could not find metadata for media: %s", input_video)
        return 1

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    watermarked_path = metadata.get("default_tasks", {}).get("apply_watermark")
    if not isinstance(watermarked_path, str) or not os.path.isfile(watermarked_path):
        logger.error(
            "No watermarked video on record for %s (apply_watermark not done yet?) - "
            "split_scenes needs the watermarked file, not the raw download.",
            input_video,
        )
        return 1

    video = Path(watermarked_path)
    out_dir = video.parent / "scene_clips"
    result = scene_split.run(video, out_dir, fps=5.0, threshold=50.0, flicker_threshold=2.0)

    update_task_for_media(input_video, "split_scenes", str(out_dir))
    logger.info(
        "Scene split complete: %d scenes from %d raw sub-frames -> %s",
        len(result.groups), len(result.raw_segments), out_dir,
    )
    print(str(out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
