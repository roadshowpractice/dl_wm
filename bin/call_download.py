import sys
import os
import traceback
from datetime import datetime

# Ensure we can import shared utilities
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from teton_utils import load_config, load_app_config, initialize_logging_from_config
import downloader5
import utilities1
import tasks_lib


def main():
    try:
        os.chdir(root_dir)
        platform_config = load_config()
        app_config = load_app_config()
        logging_config = {
            **platform_config.get("logging", {}),
            **app_config.get("logging", {}),
        }
        logger = initialize_logging_from_config(logging_config)

        output_dir = platform_config.get("output_dir") or platform_config.get("target_usb")
        if not output_dir:
            logger.error("No output directory configured. Set 'output_dir' in conf/config.json.")
            sys.exit(1)

        download_date = datetime.now().strftime("%Y-%m-%d")
        download_path = os.path.join(output_dir, download_date)

        if not os.path.exists(output_dir):
            logger.warning(f"Output directory {output_dir} does not exist. Creating it now.")
            os.makedirs(output_dir, exist_ok=True)

        if not os.path.exists(download_path):
            logger.warning(f"Download path {download_path} does not exist. Creating it now.")
            try:
                os.makedirs(download_path, exist_ok=True)
            except PermissionError:
                logger.error(f"Permission denied: Unable to create {download_path}")
                sys.exit(1)
        elif not os.access(download_path, os.W_OK):
            logger.error(f"Error: No write permission to {download_path}.")
            sys.exit(1)

        logger.info(f"Download directory confirmed: {download_path}")

        params = {
            "download_path": download_path,
            "cookie_path": platform_config.get("cookie_path")
            or app_config.get("video_download", {}).get("cookie_path"),
            "video_download": app_config.get("video_download", {}),
            "url": None,
            **platform_config.get("watermark_config", {}),
        }

        if len(sys.argv) < 2:
            logger.error("The URL is missing. Please provide a valid URL as a command-line argument.")
            sys.exit(1)

        params["url"] = sys.argv[1].strip()

        function_calls = [
            downloader5.mask_metadata,
            downloader5.create_original_filename,
            downloader5.download_video,
            utilities1.store_params_as_json,
            tasks_lib.write_masked_metadata_with_tasks,
        ]

        for func in function_calls:
            logger.info(f"Entering function: {func.__name__}")
            try:
                result = func(params)
                if result:
                    params.update(result)
            except Exception as e:
                logger.error(f"Error executing {func.__name__}: {e}")
                logger.debug(traceback.format_exc())

        original_filename = params.get("original_filename", "")
        if original_filename:
            logger.info(f"Returning original filename: {original_filename}")
            print(original_filename)
            return original_filename

        logger.warning("No original filename to return.")
        return None

    except Exception as e:
        print(f"Unexpected error: {e}")
        print(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
