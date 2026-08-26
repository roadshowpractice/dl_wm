import logging
import os
from pathlib import Path

import instaloader
import requests

from lib.metadata_compactor import build_compact_metadata, write_raw_metadata
from lib.teton_utils import load_app_config
from lib.vendor_router import VENDOR_INSTAGRAM, extract_vendor_id, metadata_filename


logger = logging.getLogger(__name__)


def _build_context(instagram_cfg):
    L = instaloader.Instaloader(quiet=True, download_comments=False, save_metadata=False)

    username = instagram_cfg.get("username")
    session_file = instagram_cfg.get("session_file")

    if username:
        try:
            L.load_session_from_file(username, filename=session_file)
            logger.info("Loaded Instagram session for %s", username)
            return L.context
        except FileNotFoundError:
            raise RuntimeError(
                f"No saved Instaloader session for '{username}'. Create one yourself (not through this "
                f"pipeline) with: instaloader --login={username} — this logs in interactively and saves "
                f"a session file instaloader will reuse. Configure the path via "
                f"conf/app_config.json -> \"instagram\": {{\"username\": ..., \"session_file\": ...}} if "
                f"it's not in instaloader's default location."
            )

    logger.warning(
        "No Instagram username/session configured (conf/app_config.json -> \"instagram\") — "
        "proceeding without login. Instagram aggressively rate-limits/blocks anonymous requests."
    )
    return L.context


def _sidecar_items(post):
    if post.typename == "GraphSidecar":
        return list(post.get_sidecar_nodes())
    return [post]


def _download_media(session, media_url, target_path, referer):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
    }
    with session.get(media_url, headers=headers, stream=True, timeout=30) as response:
        response.raise_for_status()
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    handle.write(chunk)
    return target_path


def download(url, output_dir, metadata_dir, registry_record, cookie_path, video_download=None):
    _ = cookie_path  # instaloader auth is a session file, not a Netscape cookie jar — see conf/app_config.json "instagram"
    _ = video_download

    vendor_id = extract_vendor_id(VENDOR_INSTAGRAM, url)
    if not vendor_id:
        raise ValueError("Could not extract Instagram shortcode from URL")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    metadata_path = os.path.join(metadata_dir, metadata_filename(VENDOR_INSTAGRAM, vendor_id))

    app_config = load_app_config() or {}
    instagram_cfg = app_config.get("instagram") if isinstance(app_config.get("instagram"), dict) else {}
    download_images = instagram_cfg.get("download_images", True)
    download_videos = instagram_cfg.get("download_videos", True)

    context = _build_context(instagram_cfg)
    post = instaloader.Post.from_shortcode(context, vendor_id)

    run_id = Path(output_dir).name
    entries = _sidecar_items(post)
    is_carousel = len(entries) > 1

    items = []
    downloaded_files = []

    for i, entry in enumerate(entries, start=1):
        is_video = entry.is_video
        if is_video and not download_videos:
            logger.info("Skipping video entry %s due to configuration", i)
            continue
        if not is_video and not download_images:
            logger.info("Skipping image entry %s due to configuration", i)
            continue

        media_url = entry.video_url if is_video else entry.display_url
        ext = "mp4" if is_video else "jpg"
        stem = f"{run_id}__{i:02d}" if is_carousel else run_id
        target_path = os.path.join(output_dir, f"{stem}.{ext}")

        _download_media(context._session, media_url, target_path, referer=url)

        downloaded_files.append(target_path)
        items.append(
            {
                "index": i,
                "type": "video" if is_video else "image",
                "filename": os.path.basename(target_path),
                "duration": getattr(entry, "video_duration", None) if is_video else None,
            }
        )
        logger.info("Downloaded %s entry %s", "video" if is_video else "image", i)

    if not downloaded_files:
        raise RuntimeError("No downloadable Instagram media entries were found (all filtered out or post empty)")

    downloaded_path = downloaded_files[0]

    info = {
        "id": vendor_id,
        "title": post.caption,
        "uploader": post.owner_username,
        "timestamp": post.date_utc.timestamp(),
        "duration": post.video_duration if post.is_video else None,
        "ext": Path(downloaded_path).suffix.lstrip("."),
        "filesize": os.path.getsize(downloaded_path) if os.path.exists(downloaded_path) else None,
        "view_count": post.video_view_count if post.is_video else None,
        "like_count": post.likes,
        "comment_count": post.comments,
    }

    compact = build_compact_metadata(
        info,
        url=url,
        vendor=VENDOR_INSTAGRAM,
        vendor_id=vendor_id,
        downloaded_path=downloaded_path,
    )
    compact["source_url"] = url
    compact["media_type"] = "carousel" if is_carousel else items[0]["type"]
    compact["downloaded_file"] = downloaded_path
    compact["shortcode"] = vendor_id
    compact["caption"] = post.caption
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
        {
            "shortcode": vendor_id,
            "caption": post.caption,
            "owner_username": post.owner_username,
            "date_utc": str(post.date_utc),
            "likes": post.likes,
            "comments": post.comments,
            "is_video": post.is_video,
            "typename": post.typename,
            "mediacount": getattr(post, "mediacount", 1),
        },
        metadata_dir=metadata_dir,
        vendor=VENDOR_INSTAGRAM,
        vendor_id=vendor_id,
        mode=raw_mode,
    )
    if raw_path:
        compact["raw_metadata_path"] = raw_path

    import json
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
