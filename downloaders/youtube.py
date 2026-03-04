import json
import os
import subprocess

from lib.metadata_compactor import build_compact_metadata, write_raw_metadata
from lib.teton_utils import load_app_config
from lib.vendor_router import VENDOR_YOUTUBE, extract_vendor_id, metadata_filename


def download(url, output_dir, metadata_dir, registry_record):
    vendor_id = extract_vendor_id(VENDOR_YOUTUBE, url)
    if not vendor_id:
        raise ValueError("Could not extract YouTube video ID from URL")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    output_template = os.path.join(output_dir, f"{VENDOR_YOUTUBE}__{vendor_id}.%(ext)s")
    metadata_path = os.path.join(metadata_dir, metadata_filename(VENDOR_YOUTUBE, vendor_id))

    cmd = [
        "yt-dlp",
        "--remote-components",
        "ejs:github",
        "--print-json",
        "--format",
        "bestvideo+bestaudio/best",
        "--merge-output-format",
        "mp4",
        "--no-playlist",
        "--output",
        output_template,
    ]

    cookies_path = os.path.join("conf", "youtube.cookies.txt")
    if os.path.exists(cookies_path):
        cmd.extend(["--cookies", cookies_path])

    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = None
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
            break
        except json.JSONDecodeError:
            continue

    if not info:
        raise RuntimeError("yt-dlp did not return JSON metadata for YouTube download")

    downloaded_path = info.get("_filename")

    ext = info.get("ext")
    if ext:
        candidate = os.path.join(output_dir, f"{VENDOR_YOUTUBE}__{vendor_id}.{ext}")
        if os.path.exists(candidate):
            downloaded_path = candidate

    if not downloaded_path:
        raise RuntimeError("Could not determine downloaded YouTube file path")

    app_config = load_app_config()
    compact = build_compact_metadata(
        info,
        url=url,
        vendor=VENDOR_YOUTUBE,
        vendor_id=vendor_id,
        downloaded_path=downloaded_path,
    )

    raw_mode = (app_config or {}).get("raw_metadata_mode", "gzip")
    raw_path = write_raw_metadata(
        info,
        metadata_dir=metadata_dir,
        vendor=VENDOR_YOUTUBE,
        vendor_id=vendor_id,
        mode=raw_mode,
    )
    if raw_path:
        compact["raw_metadata_path"] = raw_path

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, ensure_ascii=False)

    record = {
        **(registry_record or {}),
        "vendor": VENDOR_YOUTUBE,
        "vendor_id": vendor_id,
        "metadata_file": os.path.basename(metadata_path),
        "metadata_path": metadata_path,
        "original_filename": downloaded_path,
        "to_process": downloaded_path,
    }

    return record
