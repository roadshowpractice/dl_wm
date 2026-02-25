import os
import sys
import json
import traceback
from datetime import datetime

# Ensure we can import shared utilities
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from tasks_lib import update_task_output_path
from teton_utils import load_app_config, initialize_logging_from_config
from watermarker2 import add_watermark, looks_like_filename


def _paths_match(path_a: str, path_b: str) -> bool:
    if not path_a or not path_b:
        return False

    norm_a = os.path.abspath(os.path.normpath(path_a))
    norm_b = os.path.abspath(os.path.normpath(path_b))
    if norm_a == norm_b:
        return True

    return os.path.basename(norm_a) == os.path.basename(norm_b)


def _metadata_path_for_media(input_video_path: str, metadata_dir: str) -> str:
    base_name = os.path.splitext(input_video_path)[0]
    sidecar_path = f"{base_name}.json"
    if os.path.isfile(sidecar_path):
        return sidecar_path

    if not os.path.isdir(metadata_dir):
        return ""

    for filename in sorted(os.listdir(metadata_dir)):
        if not filename.endswith(".json"):
            continue

        metadata_path = os.path.join(metadata_dir, filename)
        try:
            with open(metadata_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            continue

        default_tasks = data.get("default_tasks", {})
        if isinstance(default_tasks, dict):
            perform_download = default_tasks.get("perform_download")
            if isinstance(perform_download, str) and _paths_match(perform_download, input_video_path):
                return metadata_path

            apply_watermark = default_tasks.get("apply_watermark")
            if isinstance(apply_watermark, str) and _paths_match(apply_watermark, input_video_path):
                return metadata_path

        file_path = data.get("file_path")
        if isinstance(file_path, str) and _paths_match(file_path, input_video_path):
            return metadata_path

    return ""


def main():
    try:
        app_config = load_app_config()
        watermark_config = app_config.get("watermark_config", {})
        logger = initialize_logging_from_config(app_config.get("logging", {}))

        if len(sys.argv) < 2:
            logger.error("Usage: python call_watermark.py <video_file_path>")
            sys.exit(1)

        input_video_path = sys.argv[1]
        if not os.path.isfile(input_video_path):
            logger.error(f"Input video file does not exist: {input_video_path}")
            sys.exit(1)

        logger.info(f"Processing video file: {input_video_path}")

        metadata_dir = app_config.get("metadata_dir", "./metadata")
        if not os.path.isabs(metadata_dir):
            metadata_dir = os.path.join(root_dir, metadata_dir)

        json_path = _metadata_path_for_media(input_video_path, metadata_dir)
        if not json_path:
            logger.error(f"Metadata file not found for input video: {input_video_path}")
            sys.exit(1)

        logger.info(f"Loaded metadata from: {json_path}")

        try:
            with open(json_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            username = data.get("uploader", "")
            if looks_like_filename(username):
                logger.warning("Metadata uploader looks like a filename; skipping username watermark.")
                username = ""
            video_date = data.get("video_date", datetime.now().strftime("%Y-%m-%d"))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON metadata from {json_path}: {e}")
            sys.exit(1)

        params = {
            **dict(watermark_config),
            "input_video_path": input_video_path,
            "download_path": os.path.dirname(input_video_path),
            "username": username,
            "video_date": video_date,
        }

        logger.debug(f"Watermark configuration: {watermark_config}")
        logger.info("Starting watermarking process...")
        result = add_watermark(params)

        if result and "to_process" in result:
            update_task_output_path(json_path, "apply_watermark", result["to_process"])
            logger.info(f"Watermarked video created successfully: {result['to_process']}")
            print(result["to_process"])
            return

        logger.error("Watermarking process failed or did not return valid output.")
        sys.exit(1)

    except Exception as e:
        if "logger" in locals():
            logger.error(f"An unexpected error occurred: {e}")
            logger.debug(traceback.format_exc())
        else:
            print(f"Unexpected error: {e}")
            print(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
