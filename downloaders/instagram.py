import json
import logging
import os
from pathlib import Path
from urllib.request import Request, urlopen

import yt_dlp

from lib.metadata_compactor import build_compact_metadata, write_raw_metadata
from lib.teton_utils import load_app_config
from lib.vendor_router import VENDOR_INSTAGRAM, extract_vendor_id, metadata_filename


logger = logging.getLogger(__name__)


def download_image(url, path):
    if not url:
        raise ValueError("No image URL provided")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request) as response, target.open("wb") as handle:
        handle.write(response.read())

    return str(target)


def _resolve_entries(info):
    entries = info.get("entries") if isinstance(info, dict) else None
    if isinstance(entries, list):
        return entries
    return [info] if isinstance(info, dict) else []


def _extract_image_url(entry):
    if not isinstance(entry, dict):
        return None

    direct = entry.get("url") or entry.get("display_url") or entry.get("thumbnail")
    if direct:
        return direct

    thumbnails = entry.get("thumbnails")
    if isinstance(thumbnails, list):
        for thumb in reversed(thumbnails):
            if isinstance(thumb, dict) and thumb.get("url"):
                return thumb["url"]

    image_versions = entry.get("image_versions2")
    if isinstance(image_versions, dict):
        candidates = image_versions.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("url"):
                    return candidate["url"]

    return None


def _download_video_entry(entry, media_dir, index, cookie_path, video_download):
    output_template = os.path.join(media_dir, f"{index:03d}.%(ext)s")
    ydl_opts = {
        "outtmpl": output_template,
        "cookiefile": cookie_path,
        "format": (video_download or {}).get("format", "bestvideo[height<=?1080]+bestaudio/best"),
        "noplaylist": True,
        "ignoreerrors": True,
        "writeinfojson": False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        processed = ydl.process_ie_result(entry, download=True)
        if not processed:
            return None
        return ydl.prepare_filename(processed)


def download(url, output_dir, metadata_dir, registry_record, cookie_path, video_download=None):
    vendor_id = extract_vendor_id(VENDOR_INSTAGRAM, url)
    if not vendor_id:
        raise ValueError("Could not extract Instagram shortcode from URL")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    metadata_path = os.path.join(metadata_dir, metadata_filename(VENDOR_INSTAGRAM, vendor_id))

    app_config = load_app_config() or {}
    instagram_cfg = app_config.get("instagram") if isinstance(app_config, dict) else {}
    if not isinstance(instagram_cfg, dict):
        instagram_cfg = {}
    download_images = instagram_cfg.get("download_images", True)
    download_videos = instagram_cfg.get("download_videos", True)

    inspect_opts = {
        "cookiefile": cookie_path,
        "format": (video_download or {}).get("format", "bestvideo[height<=?1080]+bestaudio/best"),
        "noplaylist": False,
        "ignoreerrors": True,
        "writeinfojson": False,
    }

    with yt_dlp.YoutubeDL(inspect_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = _resolve_entries(info)
    is_carousel = len(entries) > 1

    if is_carousel:
        media_dir = os.path.join(output_dir, "media")
        os.makedirs(media_dir, exist_ok=True)
    else:
        media_dir = output_dir

    items = []
    downloaded_files = []

    for i, entry in enumerate(entries, start=1):
        if entry is None:
            logger.warning("Skipping empty playlist entry at index %s", i)
            continue

        is_video = bool(entry.get("formats"))

        if is_video and not download_videos:
            logger.info("Skipping video entry %s due to configuration", i)
            continue
        if not is_video and not download_images:
            logger.info("Skipping non-video entry (image) %s due to configuration", i)
            continue

        if is_video:
            downloaded_path = _download_video_entry(entry, media_dir, i, cookie_path, video_download)
            if not downloaded_path:
                logger.warning("Skipping video entry %s (download failed)", i)
                continue

            filename = os.path.basename(downloaded_path)
            downloaded_files.append(downloaded_path)
            items.append(
                {
                    "index": i,
                    "type": "video",
                    "filename": filename,
                    "duration": entry.get("duration"),
                }
            )
            logger.info("Downloaded video entry %s", i)
            continue

        logger.info("Skipping non-video entry (image) for video pipeline entry %s", i)
        image_url = _extract_image_url(entry)
        if not image_url:
            logger.warning("Skipping image entry %s (missing url/thumbnail)", i)
            continue

        ext = (entry.get("ext") or "jpg").split("?")[0].lower()
        if not ext or len(ext) > 5:
            ext = "jpg"

        image_path = os.path.join(media_dir, f"{i:03d}.{ext}")
        download_image(image_url, image_path)

        filename = os.path.basename(image_path)
        downloaded_files.append(image_path)
        items.append(
            {
                "index": i,
                "type": "image",
                "filename": filename,
            }
        )
        logger.info("Downloaded image entry %s", i)

    if not downloaded_files:
        raise RuntimeError("No downloadable Instagram media entries were found")

    downloaded_path = downloaded_files[0]

    if not is_carousel and len(items) == 1 and items[0]["type"] == "video":
        ext = info.get("ext")
        if ext:
            candidate = os.path.join(output_dir, f"{VENDOR_INSTAGRAM}__{vendor_id}.{ext}")
            if os.path.exists(candidate):
                downloaded_path = candidate

    compact = build_compact_metadata(
        info,
        url=url,
        vendor=VENDOR_INSTAGRAM,
        vendor_id=vendor_id,
        downloaded_path=downloaded_path,
    )

    if items:
        compact["items"] = items

    if is_carousel:
        compact["manifest"] = {
            "source_url": url,
            "platform": VENDOR_INSTAGRAM,
            "post_id": vendor_id,
            "items": items,
        }

    raw_mode = (app_config or {}).get("raw_metadata_mode", "gzip")
    raw_path = write_raw_metadata(
        info,
        metadata_dir=metadata_dir,
        vendor=VENDOR_INSTAGRAM,
        vendor_id=vendor_id,
        mode=raw_mode,
    )
    if raw_path:
        compact["raw_metadata_path"] = raw_path

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, ensure_ascii=False)

    return {
        **(registry_record or {}),
        "vendor": VENDOR_INSTAGRAM,
        "vendor_id": vendor_id,
        "metadata_file": os.path.basename(metadata_path),
        "metadata_path": metadata_path,
        "original_filename": downloaded_path,
        "to_process": downloaded_path,
    }
