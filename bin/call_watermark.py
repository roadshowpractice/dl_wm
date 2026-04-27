import os
import sys
import json
import traceback
import argparse
from datetime import datetime

# Ensure we can import shared utilities
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from tasks_lib import update_task_output_path
from teton_utils import load_app_config, load_config, initialize_logging_from_config
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
        try:
            with open(sidecar_path, "r", encoding="utf-8") as file:
                sidecar_data = json.load(file)
            if isinstance(sidecar_data.get("default_tasks"), dict):
                return sidecar_path
        except (json.JSONDecodeError, OSError):
            pass

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

    if os.path.isfile(sidecar_path):
        return sidecar_path

    return ""


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description=(
            "Apply watermark overlays to a video. Supports legacy metadata-json mode and "
            "standalone manual metadata mode."
        )
    )
    parser.add_argument(
        "legacy_input",
        nargs="?",
        help="Legacy input video path (metadata sidecar lookup mode).",
    )
    parser.add_argument("--input", dest="input_video", help="Input video path.")
    parser.add_argument(
        "--output",
        dest="output_video",
        help="Output video path (optional; defaults to *_watermarked beside input).",
    )
    parser.add_argument("--uploader", dest="uploader", help="Uploader/source handle.")
    parser.add_argument("--upload-date", dest="upload_date", help="Upload date string.")
    parser.add_argument("--title", dest="title", help="Video title.")
    args = parser.parse_args(argv)

    input_video_path = args.input_video or args.legacy_input
    if not input_video_path:
        parser.error("Missing input video path. Provide legacy positional path or --input.")
    args.input_video = input_video_path
    return args


def main():
    try:
        platform_config = load_config()
        app_config = load_app_config()
        watermark_config = app_config.get("watermark_config", {})
        logging_config = {
            **platform_config.get("logging", {}),
            **app_config.get("logging", {}),
        }
        logger = initialize_logging_from_config(logging_config)

        args = _parse_args(sys.argv[1:])
        input_video_path = args.input_video
        if not os.path.isfile(input_video_path):
            logger.error(f"Input video file does not exist: {input_video_path}")
            sys.exit(1)

        logger.info(f"Processing video file: {input_video_path}")

        json_path = ""
        username = args.uploader or ""
        video_date = args.upload_date or datetime.now().strftime("%Y-%m-%d")
        video_title = args.title or ""

        if not (args.uploader and args.upload_date):
            metadata_dir = app_config.get("metadata_dir", "./metadata")
            if not os.path.isabs(metadata_dir):
                metadata_dir = os.path.join(root_dir, metadata_dir)

            json_path = _metadata_path_for_media(input_video_path, metadata_dir)
            if json_path:
                logger.info(f"Loaded metadata from: {json_path}")
                try:
                    with open(json_path, "r", encoding="utf-8") as file:
                        data = json.load(file)
                    username = username or data.get("uploader", "")
                    video_date = args.upload_date or data.get("video_date", video_date)
                    video_title = video_title or data.get("video_title") or data.get("title", "")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON metadata from {json_path}: {e}")
                    sys.exit(1)
            elif not (args.uploader and args.upload_date):
                logger.error(
                    "Metadata file not found for input video and manual metadata is incomplete. "
                    "Provide --uploader and --upload-date."
                )
                sys.exit(1)

        if looks_like_filename(username):
            logger.warning("Uploader looks like a filename; skipping username watermark.")
            username = ""

        params = {
            **dict(watermark_config),
            "input_video_path": input_video_path,
            "download_path": os.path.dirname(input_video_path),
            "username": username,
            "video_date": video_date,
        }
        if args.output_video:
            params["output_video_path"] = args.output_video

        logger.debug(f"Watermark configuration: {watermark_config}")
        logger.info("Starting watermarking process...")
        result = add_watermark(params)

        if result and "to_process" in result:
            if json_path:
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
