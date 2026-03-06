#!/usr/bin/env python
import sys
import os
import json
import logging
import traceback
import subprocess
import time

# Add lib path to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
sys.path.append(lib_path)

# Import utilities
from teton_utils import initialize_logging, load_config, load_app_config, resolve_repo_path
from tasks_lib import find_url_json
from vendor_router import detect_vendor, canonicalize_vendor_url

# Map tasks to their respective scripts
TASK_DISPATCH = {
    "perform_download": "bin/call_download.py",
    "apply_watermark": "bin/call_watermark.py",
    "extract_audio": "bin/call_extract_audio.py",
    "generate_srt": "bin/call_captions.py",
    "burn_srt": "bin/call_burn_srt.py",
    # Convert screenshot timestamps after all other tasks
    "post_processed": "bin/convert_screenshots.py"
}

def execute_tasks(task_config, url, to_process, dry_run=False):
    """Run appropriate script for each task based on its config."""
    for task, status in task_config.items():
        script = TASK_DISPATCH.get(task)

        if not script:
            logging.warning("No script defined for task: {}".format(task))
            continue

        # Use URL for download; use file path for all others
        task_input = url if task == "perform_download" else to_process

        if status is True:
            logging.info("🚀 Running task: {} -> {}".format(task, script))
            script_path = os.path.join(root_dir, script)
            if not os.path.isfile(script_path):
                logging.warning(
                    "Skipping task {}; script not found: {}".format(task, script_path)
                )
                continue
            if dry_run:
                logging.info(
                    "[Dry Run] Would run: {} {} {}".format(
                        sys.executable, script_path, task_input
                    )
                )
            else:
                result = subprocess.run([sys.executable, script_path, task_input], cwd=root_dir)
                if result.returncode != 0:
                    logging.error(
                        "Task failed: {} (exit code: {})".format(
                            task, result.returncode
                        )
                    )
        elif isinstance(status, str):
            logging.info("✅ Task already completed: {} @ {}".format(task, status))
        else:
            logging.info("⏭️  Skipping task: {}".format(task))


def run_my_existing_downloader(url, logger):
    """Calls the known-good downloader script for the given URL."""
    logger.info("📥 Initiating download for: {}".format(url))

    script_path = os.path.join(root_dir, "bin/call_download.py")
    logger.info("📡 Streaming downloader output...")
    result = subprocess.run([sys.executable, script_path, url], cwd=root_dir)

    if result.returncode != 0:
        logger.error("Download script failed with exit code {}.".format(result.returncode))
        return False

    logger.info("✅ Downloader completed successfully.")
    return True


def wait_for_download_file(to_process, logger, timeout_seconds=90, poll_interval=3):
    """Wait briefly for downloader finalization when a temporary .part file exists."""
    if os.path.exists(to_process):
        return True

    directory = os.path.dirname(to_process) or "."
    base_name = os.path.splitext(os.path.basename(to_process))[0]
    candidates = [
        name
        for name in os.listdir(directory)
        if name.startswith(base_name) and name.endswith(".part")
    ] if os.path.isdir(directory) else []

    if not candidates:
        return False

    logger.info(
        "⏳ Found partial download(s) for {}; waiting up to {}s for final file...".format(
            base_name, timeout_seconds
        )
    )
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if os.path.exists(to_process):
            logger.info("✅ Finalized download detected: {}".format(to_process))
            return True
        time.sleep(poll_interval)

    logger.warning(
        "⚠️ Download is still incomplete (.part file present). "
        "Wait for download to finish, then rerun call_router."
    )
    return False

def main():
    try:
        os.chdir(root_dir)
        dry_run = "--dry-run" in sys.argv
        url_args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]

        if len(url_args) < 1:
            print("Usage: python call_router.py <url> [--dry-run]")
            sys.exit(1)

        raw_url = url_args[0].strip()
        vendor = detect_vendor(raw_url)
        url = canonicalize_vendor_url(vendor, raw_url) if vendor else raw_url

        config = load_config()
        logger = initialize_logging()

        if url != raw_url:
            logger.info(
                "🔗 Normalized URL for metadata matching: {} -> {}".format(raw_url, url)
            )
        app_config = load_app_config()
        metadata_dir = resolve_repo_path(app_config.get("metadata_dir", "./metadata"))
        # Ensure metadata directory exists before searching index/files.
        os.makedirs(metadata_dir, exist_ok=True)
        logger.info("🔁 Task Router Started")

        found_file, found_data = find_url_json(url, metadata_dir=metadata_dir)

        perform_download_done = (
            found_data.get("default_tasks", {}).get("perform_download")
            if found_data
            else None
        )

        if not found_file or not perform_download_done:
            logger.info("📥 No completed download or metadata found — running downloader...")
            download_success = run_my_existing_downloader(url, logger)
            if not download_success:
                logger.error(
                    "❌ Downloader failed before metadata was generated. "
                    "Fix downloader errors above, then rerun call_router."
                )
                return
            found_file, found_data = find_url_json(url, metadata_dir=metadata_dir)
            perform_download_done = (
                found_data.get("default_tasks", {}).get("perform_download")
                if found_data
                else None
            )

        if not found_data:
            logger.error("❌ No metadata found after attempted download.")
            return

        print("Found in: {}".format(found_file))
        visible_fields = {
            "video_title": found_data.get("video_title"),
            "video_date": found_data.get("video_date"),
            "uploader": found_data.get("uploader"),
            "url": found_data.get("url"),
            "default_tasks": found_data.get("default_tasks", {}),
        }
        print(json.dumps(visible_fields, indent=2))

        if isinstance(perform_download_done, str):
            to_process = perform_download_done
        else:
            logger.error("Download task not completed and no output path recorded.")
            return

        if not wait_for_download_file(to_process, logger):
            logger.error("Input file does not exist: {}".format(to_process))
            return

        default_tasks = found_data.get("default_tasks", {})
        if not default_tasks:
            logger.warning("No 'default_tasks' section found in metadata.")
            return

        logger.info("🛠 Tasks to evaluate: {}".format(list(default_tasks.keys())))
        execute_tasks(default_tasks, url, to_process, dry_run)

    except Exception as e:
        logging.error("Unexpected error in main(): {}".format(e))
        traceback.print_exc()


if __name__ == "__main__":
    main()
