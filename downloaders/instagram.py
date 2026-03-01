import json
import os

import yt_dlp

from lib.vendor_router import VENDOR_INSTAGRAM, extract_vendor_id, metadata_filename


def download(url, output_dir, metadata_dir, registry_record, cookie_path, video_download=None):
    vendor_id = extract_vendor_id(VENDOR_INSTAGRAM, url)
    if not vendor_id:
        raise ValueError("Could not extract Instagram shortcode from URL")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    output_template = os.path.join(output_dir, f"{VENDOR_INSTAGRAM}__{vendor_id}.%(ext)s")
    metadata_path = os.path.join(metadata_dir, metadata_filename(VENDOR_INSTAGRAM, vendor_id))

    ydl_opts = {
        "outtmpl": output_template,
        "cookiefile": cookie_path,
        "format": (video_download or {}).get("format", "bestvideo[height<=?1080]+bestaudio/best"),
        "noplaylist": (video_download or {}).get("noplaylist", True),
        "writeinfojson": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded_path = ydl.prepare_filename(info)

    ext = info.get("ext")
    if ext:
        candidate = os.path.join(output_dir, f"{VENDOR_INSTAGRAM}__{vendor_id}.{ext}")
        if os.path.exists(candidate):
            downloaded_path = candidate

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)

    info_json_src = os.path.splitext(downloaded_path)[0] + ".info.json"
    if os.path.exists(info_json_src) and os.path.abspath(info_json_src) != os.path.abspath(metadata_path):
        os.replace(info_json_src, metadata_path)

    record = {
        **(registry_record or {}),
        "vendor": VENDOR_INSTAGRAM,
        "vendor_id": vendor_id,
        "metadata_file": os.path.basename(metadata_path),
        "metadata_path": metadata_path,
        "original_filename": downloaded_path,
        "to_process": downloaded_path,
    }

    return record
