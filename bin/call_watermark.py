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

from teton_utils import load_app_config, initialize_logging_from_config
from watermarker2 import add_watermark, looks_like_filename


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

        base_name = os.path.splitext(input_video_path)[0]
        json_path = f"{base_name}.json"
        logger.info(f"Looking for metadata file: {json_path}")

        if not os.path.isfile(json_path):
            logger.error(f"Metadata file not found: {json_path}")
            sys.exit(1)

        try:
            with open(json_path, "r") as file:
                data = json.load(file)
            logger.info(f"Loaded metadata from: {json_path}")
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
