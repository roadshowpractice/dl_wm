#!/usr/bin/env python
# -*- coding: utf-8 -*-
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
    "post_processed": "bin/convert_screenshots.py",
    "split_scenes": "bin/call_split_scenes.py",
    "render_reverse": "bin/call_render_reverse.py",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def is_image_media(found_data, downloaded_path):
    """Return True when metadata or download path indicates image media."""
    metadata_media_type = str(found_data.get("media_type", "")).strip().lower()
    if metadata_media_type == "image":
        return True

    extension = os.path.splitext(str(downloaded_path))[1].strip().lower()
    return extension in IMAGE_EXTENSIONS

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


def carousel_followup_items(found_data, to_process):
    """Video items after the first in a carousel post. The downloader records
    only the first file as perform_download, so without this every later slide
    stopped at download."""
    items = found_data.get("items") or []
    if len(items) < 2:
        return []
    media_dir = os.path.dirname(to_process)
    first = os.path.basename(to_process)
    return [
        os.path.join(media_dir, item["filename"])
        for item in items
        if item.get("type") == "video" and item.get("filename") and item["filename"] != first
    ]


def item_task_state(found_data, item_path, write=True):
    """Per-item task state, kept in a <media>.json sidecar next to the file.
    The task scripts look for that sidecar before searching metadata/, so each
    item records its own outputs. Created on first run from the post's
    metadata with completed tasks reset to pending; reused (resumed) after."""
    sidecar = os.path.splitext(item_path)[0] + ".json"
    if os.path.isfile(sidecar):
        with open(sidecar, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("default_tasks"), dict):
            return data["default_tasks"]

    data = {k: v for k, v in found_data.items() if k not in ("items", "manifest")}
    tasks = {
        task: (False if status is False else True)
        for task, status in (found_data.get("default_tasks") or {}).items()
    }
    tasks["perform_download"] = item_path
    data["default_tasks"] = tasks
    data["downloaded_file"] = item_path
    if write:
        with open(sidecar, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    return tasks


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

        followups = carousel_followup_items(found_data, to_process)
        first_is_image = is_image_media(found_data, to_process)
        if first_is_image and not followups:
            logger.info(
                "Image media detected; download complete. Skipping video/audio pipeline."
            )
            return

        default_tasks = found_data.get("default_tasks", {})
        if not default_tasks:
            logger.warning("No 'default_tasks' section found in metadata.")
            return

        if first_is_image:
            # Mixed carousel that opens on a photo: nothing to do for slide 1,
            # but its video slides still go through the pipeline below.
            logger.info("First carousel item is an image; processing its video items only.")
        else:
            logger.info("🛠 Tasks to evaluate: {}".format(list(default_tasks.keys())))
            execute_tasks(default_tasks, url, to_process, dry_run)

        for item_path in followups:
            if not os.path.isfile(item_path):
                logger.warning("Carousel item missing on disk, skipping: {}".format(item_path))
                continue
            logger.info("🎞 Carousel item: {}".format(item_path))
            execute_tasks(item_task_state(found_data, item_path, write=not dry_run), url, item_path, dry_run)

    except Exception as e:
        logging.error("Unexpected error in main(): {}".format(e))
        traceback.print_exc()


if __name__ == "__main__":
    main()
