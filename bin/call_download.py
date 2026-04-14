import json
import os
import sys
import traceback
from glob import glob
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


def _normalize_cookie_list(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _cookie_discovery_patterns(vendor):
    if vendor == VENDOR_INSTAGRAM:
        return ["*instagram*cookie*.txt", "*insta*cookie*.txt", "*instagram*.txt", "*insta*.txt"]
    if vendor == VENDOR_FACEBOOK:
        return ["*facebook*cookie*.txt", "*fb*cookie*.txt", "*facebook*.txt", "*fb*.txt"]
    if vendor == VENDOR_YOUTUBE:
        return ["*youtube*cookie*.txt", "*yt*cookie*.txt", "*youtube*.txt", "*yt*.txt"]
    return []


def resolve_cookie_paths(platform_config, video_download_cfg, vendor):
    if not isinstance(video_download_cfg, dict):
        video_download_cfg = {}

    candidates = []
    cookie_hierarchy = video_download_cfg.get("cookie_hierarchy")
    if isinstance(cookie_hierarchy, dict):
        candidates.extend(_normalize_cookie_list(cookie_hierarchy.get(vendor)))

    plural_key = f"{vendor}_cookie_paths"
    candidates.extend(_normalize_cookie_list(video_download_cfg.get(plural_key)))

    cookie_path = None
    if vendor == VENDOR_INSTAGRAM:
        cookie_path = video_download_cfg.get("instagram_cookie_path")
    elif vendor == VENDOR_FACEBOOK:
        cookie_path = video_download_cfg.get("facebook_cookie_path")
    elif vendor == VENDOR_YOUTUBE:
        cookie_path = video_download_cfg.get("youtube_cookie_path")
    if cookie_path:
        candidates.append(cookie_path)

    # Backward compatibility for old nested cookie mapping.
    vendor_cookie_map = video_download_cfg.get("cookie_paths")
    if isinstance(vendor_cookie_map, dict):
        candidates.extend(_normalize_cookie_list(vendor_cookie_map.get(vendor)))

    fallback_cookie = platform_config.get("cookie_path") or video_download_cfg.get("cookie_path")
    if fallback_cookie:
        candidates.append(fallback_cookie)

    conf_dir = resolve_repo_path("conf")
    if os.path.isdir(conf_dir):
        for pattern in _cookie_discovery_patterns(vendor):
            candidates.extend(
                os.path.relpath(path, root_dir)
                for path in sorted(glob(os.path.join(conf_dir, pattern)))
            )

    resolved = []
    seen = set()
    for candidate in candidates:
        path = resolve_repo_path(candidate) if candidate else None
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.exists(path):
            resolved.append(path)

    return resolved


def is_cookie_identity_blocked_error(exc):
    message_parts = [str(exc)]

    if hasattr(exc, "stderr") and exc.stderr:
        message_parts.append(str(exc.stderr))

    if hasattr(exc, "msg") and exc.msg:
        message_parts.append(str(exc.msg))

    text = "\n".join(message_parts).lower()
    block_markers = [
        "http error 429",
        "too many requests",
        "temporarily blocked",
        "rate limit",
        "rate-limit",
        "challenge_required",
        "checkpoint required",
        "login required",
        "sign in to",
        "instagram api is not granting access",
        "instagram sent an empty media response",
    ]
    return any(marker in text for marker in block_markers)


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
        if vendor not in {VENDOR_INSTAGRAM, VENDOR_FACEBOOK, VENDOR_YOUTUBE}:
            logger.error("Unsupported URL vendor. Supported vendors are Instagram, Facebook, and YouTube.")
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
