import gzip
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dl_wm.tasks_lib import load_default_tasks


logger = logging.getLogger(__name__)


def _json_fallback(value):
    """Best-effort fallback for values that are not natively JSON serializable."""
    return str(value)


def _normalize_video_date(info: dict):
    upload_date = info.get("upload_date")
    if upload_date:
        return str(upload_date)

    timestamp = info.get("timestamp")
    if isinstance(timestamp, (int, float)):
        return datetime.utcfromtimestamp(timestamp).strftime("%Y%m%d")

    release_ts = info.get("release_timestamp")
    if isinstance(release_ts, (int, float)):
        return datetime.utcfromtimestamp(release_ts).strftime("%Y%m%d")

    return None


def _build_default_tasks(downloaded_path: str):
    default_tasks = load_default_tasks()
    if not isinstance(default_tasks, dict):
        default_tasks = {}

    if downloaded_path and os.path.exists(downloaded_path):
        default_tasks["perform_download"] = downloaded_path

    return default_tasks


def build_compact_metadata(info: dict, *, url: str, vendor: str, vendor_id: str, downloaded_path: str) -> dict:
    width = info.get("width")
    height = info.get("height")

    compact = {
        "url": url,
        "vendor": vendor,
        "vendor_id": vendor_id,
        "id": info.get("id") or vendor_id,
        "shortcode": vendor_id if vendor == "instagram" else None,
        "video_title": info.get("title"),
        "video_date": _normalize_video_date(info),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "width": width,
        "height": height,
        "resolution": info.get("resolution") or (f"{width}x{height}" if width and height else None),
        "fps": info.get("fps"),
        "ext": info.get("ext"),
        "filesize": info.get("filesize") or info.get("filesize_approx"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "default_tasks": _build_default_tasks(downloaded_path),
    }

    return compact


def write_raw_metadata(
    info: dict,
    *,
    metadata_dir: str,
    vendor: str,
    vendor_id: str,
    mode: str = "gzip",
    stem: str | None = None,
):
    if mode not in {"gzip", "json"}:
        return None

    base_dir = Path(metadata_dir) / "raw" / f"{vendor}__{vendor_id}"
    base_dir.mkdir(parents=True, exist_ok=True)

    if stem is not None and not str(stem).strip():
        raise ValueError("Invalid metadata filename stem (empty)")

    resolved_stem = str(stem).strip() if stem is not None else ""
    if not resolved_stem:
        resolved_stem = f"{vendor}__{vendor_id}" or "raw"

    suffix = ".raw.json.gz" if mode == "gzip" else ".raw.json"
    raw_path = base_dir / f"{resolved_stem}{suffix}"
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Writing raw metadata to: %s", raw_path)

    if mode == "gzip":
        with gzip.open(raw_path, "wt", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, default=_json_fallback)
    else:
        with raw_path.open("w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, default=_json_fallback)

    return str(raw_path)
