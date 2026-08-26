import json
import os

import yt_dlp

from lib.metadata_compactor import build_compact_metadata, write_raw_metadata
from lib.teton_utils import load_app_config
from lib.vendor_router import VENDOR_VIMEO, extract_vendor_id, metadata_filename


def download(url, output_dir, metadata_dir, registry_record, cookie_path, video_download=None):
    vendor_id = extract_vendor_id(VENDOR_VIMEO, url)
    if not vendor_id:
        raise ValueError("Could not extract Vimeo video ID from URL")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    output_template = os.path.join(output_dir, f"{VENDOR_VIMEO}__{vendor_id}.%(ext)s")
    metadata_path = os.path.join(metadata_dir, metadata_filename(VENDOR_VIMEO, vendor_id))

    video_download_cfg = video_download or {}
    app_config = load_app_config()

    ydl_opts = {
        "outtmpl": output_template,
        "cookiefile": cookie_path,
        "format": video_download_cfg.get("format", "bestvideo[height<=?1080]+bestaudio/best"),
        "noplaylist": video_download_cfg.get("noplaylist", True),
        "writeinfojson": False,
    }

    # Vimeo-specific settings live in their own config block (like youtube_download),
    # not the shared video_download block, since they're not meaningful for other vendors.
    vimeo_cfg = app_config.get("vimeo_download", {}) if isinstance(app_config, dict) else {}

    # Many Vimeo embeds (player.vimeo.com/video/<id>) are domain-restricted
    # and 401 without a Referer matching the page that embeds them.
    referer = vimeo_cfg.get("referer")
    if referer:
        ydl_opts["http_headers"] = {"Referer": referer}

    # Vimeo's edge also blocks non-browser TLS fingerprints outright (403 on the
    # player config endpoint regardless of Referer) — impersonation via curl_cffi
    # is required, not optional. Needs curl_cffi>=0.10,<0.16 (yt-dlp's supported range).
    impersonate = vimeo_cfg.get("impersonate")
    if impersonate:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        ydl_opts["impersonate"] = ImpersonateTarget.from_str(impersonate)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded_path = ydl.prepare_filename(info)

    ext = info.get("ext")
    if ext:
        candidate = os.path.join(output_dir, f"{VENDOR_VIMEO}__{vendor_id}.{ext}")
        if os.path.exists(candidate):
            downloaded_path = candidate

    compact = build_compact_metadata(
        info,
        url=url,
        vendor=VENDOR_VIMEO,
        vendor_id=vendor_id,
        downloaded_path=downloaded_path,
    )

    raw_mode = (app_config or {}).get("raw_metadata_mode", "gzip")
    raw_path = write_raw_metadata(
        info,
        metadata_dir=metadata_dir,
        vendor=VENDOR_VIMEO,
        vendor_id=vendor_id,
        mode=raw_mode,
    )
    if raw_path:
        compact["raw_metadata_path"] = raw_path

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, ensure_ascii=False)

    return {
        **(registry_record or {}),
        "vendor": VENDOR_VIMEO,
        "vendor_id": vendor_id,
        "metadata_file": os.path.basename(metadata_path),
        "metadata_path": metadata_path,
        "original_filename": downloaded_path,
        "to_process": downloaded_path,
    }
