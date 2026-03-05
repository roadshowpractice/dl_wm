import json
import os
import sys
import traceback
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if root_dir not in sys.path:
    sys.path.append(root_dir)
if lib_path not in sys.path:
    sys.path.append(lib_path)

from teton_utils import load_config, load_app_config, initialize_logging_from_config, resolve_repo_path
from vendor_router import (
    detect_vendor,
    VENDOR_INSTAGRAM,
    VENDOR_YOUTUBE,
    extract_vendor_id,
    metadata_filename,
    canonicalize_vendor_url,
)
from downloaders.instagram import download as download_instagram
from downloaders.youtube import download as download_youtube


def resolve_cookie_path(platform_config, video_download_cfg, vendor):
    if not isinstance(video_download_cfg, dict):
        video_download_cfg = {}

    cookie_path = None
    if vendor == VENDOR_INSTAGRAM:
        cookie_path = video_download_cfg.get("instagram_cookie_path")
    elif vendor == VENDOR_YOUTUBE:
        cookie_path = video_download_cfg.get("youtube_cookie_path")

    # Backward compatibility for old nested cookie mapping.
    if not cookie_path:
        vendor_cookie_map = video_download_cfg.get("cookie_paths")
        if isinstance(vendor_cookie_map, dict):
            cookie_path = vendor_cookie_map.get(vendor)

    cookie_path = cookie_path or platform_config.get("cookie_path") or video_download_cfg.get("cookie_path")
    return resolve_repo_path(cookie_path) if cookie_path else None


def upsert_index_record(index_path, record):
    os.makedirs(os.path.dirname(index_path), exist_ok=True)

    rows = []
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))

    updated = False
    for i, row in enumerate(rows):
        if row.get("vendor") == record.get("vendor") and row.get("vendor_id") == record.get("vendor_id"):
            rows[i] = {**row, **record}
            updated = True
            break

    if not updated:
        rows.append(record)

    with open(index_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


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

        if len(sys.argv) < 2:
            logger.error("The URL is missing. Please provide a valid URL as a command-line argument.")
            sys.exit(1)

        url = sys.argv[1].strip()
        vendor = detect_vendor(url)
        if vendor not in {VENDOR_INSTAGRAM, VENDOR_YOUTUBE}:
            logger.error("Unsupported URL vendor. Supported vendors are Instagram and YouTube.")
            sys.exit(1)
        url = canonicalize_vendor_url(vendor, url)

        output_root = platform_config.get("output_dir") or platform_config.get("target_usb")
        if not output_root:
            logger.error("No output directory configured. Set 'output_dir' in conf/config.json.")
            sys.exit(1)

        output_root = resolve_repo_path(output_root)
        download_date = datetime.now().strftime("%Y-%m-%d")
        download_path = os.path.join(output_root, download_date)
        metadata_dir = resolve_repo_path(app_config.get("metadata_dir", "./metadata"))
        os.makedirs(download_path, exist_ok=True)
        os.makedirs(metadata_dir, exist_ok=True)

        video_download_cfg = app_config.get("video_download", {}) if isinstance(app_config.get("video_download"), dict) else {}
        registry_record = {
            "url": url,
            "vendor": vendor,
            "vendor_id": extract_vendor_id(vendor, url),
            "metadata_file": metadata_filename(vendor, extract_vendor_id(vendor, url)),
        }

        cookie_path = resolve_cookie_path(platform_config, video_download_cfg, vendor)

        if vendor == VENDOR_YOUTUBE:
            result = download_youtube(url, download_path, metadata_dir, registry_record, cookie_path, video_download_cfg)
        else:
            if not cookie_path or not os.path.exists(cookie_path):
                logger.error("Instagram downloader requires a valid cookie file path (e.g., conf/instagram.cookies.txt).")
                sys.exit(1)
            result = download_instagram(url, download_path, metadata_dir, registry_record, cookie_path, video_download_cfg)

        upsert_index_record(
            os.path.join(metadata_dir, "index.jsonl"),
            {
                "url": url,
                "vendor": result["vendor"],
                "vendor_id": result["vendor_id"],
                "metadata_file": result["metadata_file"],
            },
        )

        logger.info("Download complete: %s", result["original_filename"])
        print(result["original_filename"])
        return result["original_filename"]

    except Exception as exc:
        print(f"Unexpected error: {exc}")
        print(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
