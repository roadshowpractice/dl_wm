#!/usr/bin/env python
import os
import sys
import json
import traceback
import argparse
from datetime import datetime

import pathlib
_root = str(pathlib.Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from dl_wm.tasks_lib import update_task_output_path
from dl_wm.teton_utils import load_app_config, load_config, initialize_logging_from_config
from dl_wm.watermarker2 import add_watermark, build_source_label, looks_like_filename
from dl_wm.transcription_caller import _metadata_path_for_media


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
        logging_config = {
            **platform_config.get("logging", {}),
            **app_config.get("logging", {}),
        }
        logger = initialize_logging_from_config(logging_config)
        watermark_config = app_config.get("watermark_config", {})

        args = _parse_args(sys.argv[1:])
        input_video_path = args.input_video
        if not os.path.isfile(input_video_path):
            logger.error(f"Input video file does not exist: {input_video_path}")
            sys.exit(1)

        logger.info(f"Processing video file: {input_video_path}")

        username = args.uploader or ""
        video_date = args.upload_date or datetime.now().strftime("%Y-%m-%d")
        video_title = args.title or ""
        json_path = ""

        if not (args.uploader and args.upload_date and args.title):
            json_path = _metadata_path_for_media(input_video_path) or ""
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
            elif not (args.uploader and args.upload_date and args.title):
                logger.error(
                    "Metadata file not found for input video and manual metadata is incomplete. "
                    "Provide --uploader, --upload-date, and --title."
                )
                sys.exit(1)

        if looks_like_filename(username):
            logger.warning("Uploader looks like a filename; skipping username watermark.")
            username = ""

        source_label = build_source_label(username, video_date, video_title) if video_title else ""

        params = {
            **dict(watermark_config),
            "input_video_path": input_video_path,
            "download_path": os.path.dirname(input_video_path),
            "username": username,
            "video_date": video_date,
            "source_label": source_label,
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
