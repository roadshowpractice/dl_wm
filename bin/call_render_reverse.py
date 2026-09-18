#!/usr/bin/env python
"""Router-callable wrapper: render_scene_cards.py + render_labeled_scene_video.py
(reverse order only), reading split_scenes' output dir from metadata.

Only builds the reverse-chronological labeled video, per the default_tasks
name - render_scene_cards.py writes both scenes_forward.jsonl and
scenes_reverse.jsonl as a side effect either way, but only the reverse one
gets rendered to mp4 here. Add a parallel call_render_forward.py later if a
forward-order labeled video is ever wanted as its own default task.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from teton_utils import initialize_logging
from transcription_caller import _metadata_path_for_media, update_task_for_media  # reused, not duplicated


def main() -> int:
    logger = initialize_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python bin/call_render_reverse.py <video_file_path>")
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

    scene_dir = metadata.get("default_tasks", {}).get("split_scenes")
    if not isinstance(scene_dir, str) or not os.path.isdir(scene_dir):
        logger.error(
            "No scene_clips dir on record for %s (split_scenes not done yet?) - "
            "render_reverse needs scene_split's output.",
            input_video,
        )
        return 1

    scene_dir_path = Path(scene_dir)

    cards_result = subprocess.run(
        [sys.executable, os.path.join(root_dir, "bin", "render_scene_cards.py"), str(scene_dir_path)],
        cwd=root_dir,
    )
    if cards_result.returncode != 0:
        logger.error("render_scene_cards.py failed (exit %s)", cards_result.returncode)
        return 1

    reverse_jsonl = scene_dir_path / "scenes_reverse.jsonl"
    output_video = scene_dir_path / "clips_labeled_reverse.mp4"
    video_result = subprocess.run(
        [
            sys.executable, os.path.join(root_dir, "bin", "render_labeled_scene_video.py"),
            str(scene_dir_path), str(reverse_jsonl), str(output_video),
        ],
        cwd=root_dir,
    )
    if video_result.returncode != 0:
        logger.error("render_labeled_scene_video.py failed (exit %s)", video_result.returncode)
        return 1

    update_task_for_media(input_video, "render_reverse", str(output_video))
    logger.info("Reverse labeled video written: %s", output_video)
    print(str(output_video))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
