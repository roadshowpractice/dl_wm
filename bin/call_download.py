#!/usr/bin/env python
import os
import sys
import traceback
from datetime import datetime

import pathlib
_root = str(pathlib.Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from dl_wm.teton_utils import load_config, load_app_config, initialize_logging_from_config, resolve_repo_path
from dl_wm.vendor_router import (
    detect_vendor,
    VENDOR_FACEBOOK,
    VENDOR_INSTAGRAM,
    VENDOR_YOUTUBE,
    extract_vendor_id,
    metadata_filename,
    canonicalize_vendor_url,
)
from downloaders.instagram import download as download_instagram
from downloaders.facebook import download as download_facebook
from downloaders.youtube import download as download_youtube
from downloaders.cookies import resolve_cookie_paths, is_cookie_identity_blocked_error
from dl_wm.tasks_lib import upsert_index_record


def main():
    try:
        os.chdir(_root)
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
        if vendor not in {VENDOR_INSTAGRAM, VENDOR_FACEBOOK, VENDOR_YOUTUBE}:
            logger.error("Unsupported URL vendor. Supported vendors are Instagram, Facebook, and YouTube.")
            sys.exit(1)
        url = canonicalize_vendor_url(vendor, url)

        output_root = platform_config.get("output_dir") or platform_config.get("target_usb")
        if not output_root:
            logger.error("No output directory configured. Set 'output_dir' in conf/config.json.")
            sys.exit(1)

        output_root = resolve_repo_path(output_root)
        download_path = os.path.join(output_root, datetime.now().strftime("%Y-%m-%d"))
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

        cookie_paths = resolve_cookie_paths(platform_config, video_download_cfg, vendor)

        if vendor in {VENDOR_INSTAGRAM, VENDOR_FACEBOOK} and not cookie_paths:
            logger.error(
                "%s downloader requires at least one valid cookie file in conf/.",
                vendor.capitalize(),
            )
            sys.exit(1)

        if vendor == VENDOR_YOUTUBE and not cookie_paths:
            cookie_paths = [None]

        last_error = None
        for idx, cookie_path in enumerate(cookie_paths, start=1):
            try:
                if vendor == VENDOR_YOUTUBE:
                    result = download_youtube(url, download_path, metadata_dir, registry_record, cookie_path, video_download_cfg)
                    if not result.get("success", False):
                        raise RuntimeError(
                            "YouTube download failed"
                            f" (strategy={result.get('strategy')}, error={result.get('error')})\n"
                            f"stdout:\n{result.get('stdout', '')}\n"
                            f"stderr:\n{result.get('stderr', '')}"
                        )
                elif vendor == VENDOR_FACEBOOK:
                    logger.info("Facebook download attempt %s/%s using cookie file: %s", idx, len(cookie_paths), cookie_path)
                    result = download_facebook(url, download_path, metadata_dir, registry_record, cookie_path, video_download_cfg)
                else:
                    logger.info("Instagram download attempt %s/%s using cookie file: %s", idx, len(cookie_paths), cookie_path)
                    result = download_instagram(url, download_path, metadata_dir, registry_record, cookie_path, video_download_cfg)
                break
            except Exception as exc:
                last_error = exc
                has_more = idx < len(cookie_paths)
                if has_more and is_cookie_identity_blocked_error(exc):
                    logger.warning(
                        "Download failed due to cookie/account block on %s. Rotating to next cookie (%s/%s).",
                        cookie_path,
                        idx + 1,
                        len(cookie_paths),
                    )
                    continue
                raise
        else:
            if last_error:
                raise last_error

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
