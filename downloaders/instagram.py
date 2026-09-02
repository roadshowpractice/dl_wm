import json
import logging
import os
import re
import html as html_lib
from pathlib import Path

import requests
import yt_dlp

from lib.metadata_compactor import build_compact_metadata, write_raw_metadata
from lib.teton_utils import load_app_config
from lib.vendor_router import VENDOR_INSTAGRAM, extract_vendor_id, metadata_filename


logger = logging.getLogger(__name__)
INSTAGRAM_UA = "Mozilla/5.0"


def download_image(url, path):
    if not url:
        raise ValueError("No image URL provided")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, headers={"User-Agent": INSTAGRAM_UA}, timeout=30) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            handle.write(response.content)

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


def _decode_escaped(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value.replace("\\/", "/")


def _load_cookie_jar(cookie_path):
    jar = requests.cookies.RequestsCookieJar()
    if not cookie_path or not os.path.exists(cookie_path):
        return jar

    with open(cookie_path, "r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _, path, _, _, name, value = parts[:7]
            if not name:
                continue
            jar.set(name, value, domain=domain or None, path=path or "/")
    return jar


def extract_image_candidates_from_html(html):
    candidates = []
    seen = set()

    def add_candidate(url, source, width=None, height=None):
        clean_url = _decode_escaped(url)
        if isinstance(clean_url, str) and "&amp;" in clean_url:
            logger.warning("unescaped HTML entities in image URL")
        if isinstance(clean_url, str):
            clean_url = html_lib.unescape(clean_url)
        if not clean_url or clean_url in seen:
            return
        seen.add(clean_url)
        candidates.append(
            {
                "url": clean_url,
                "source": source,
                "width": width,
                "height": height,
            }
        )

    og_matches = re.findall(
        r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    for og_url in og_matches:
        add_candidate(og_url, "og:image")

    for key in ("display_url", "thumbnail_src"):
        for raw_url in re.findall(rf'"{key}"\s*:\s*"([^"]+)"', html):
            add_candidate(raw_url, key)

    for match in re.finditer(r'"image_versions2"\s*:\s*\{', html):
        block = html[match.start() : match.start() + 50000]
        candidates_match = re.search(r'"candidates"\s*:\s*\[(.*?)\]', block, flags=re.DOTALL)
        if not candidates_match:
            continue
        block_urls = re.finditer(
            r'"url"\s*:\s*"([^"]+)"(?:[^{}]{0,200}?"width"\s*:\s*(\d+))?(?:[^{}]{0,200}?"height"\s*:\s*(\d+))?',
            candidates_match.group(1),
        )
        for block_url in block_urls:
            width = int(block_url.group(2)) if block_url.group(2) else None
            height = int(block_url.group(3)) if block_url.group(3) else None
            add_candidate(block_url.group(1), "image_versions2", width=width, height=height)

    return candidates


def extract_page_metadata_from_html(html):
    caption = None
    uploader = None
    title = None

    caption_match = re.search(
        r'"edge_media_to_caption"\s*:\s*\{"edges"\s*:\s*\[\{"node"\s*:\s*\{"text"\s*:\s*"([^"]*)"',
        html,
    )
    if caption_match:
        caption = _decode_escaped(caption_match.group(1))

    username_match = re.search(r'"owner"\s*:\s*\{[^{}]*"username"\s*:\s*"([^"]+)"', html)
    if username_match:
        uploader = _decode_escaped(username_match.group(1))

    og_title_match = re.search(
        r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if og_title_match:
        title = _decode_escaped(og_title_match.group(1))

    return {"caption": caption, "uploader": uploader, "title": title}


def inspect_image_candidates(url, cookie_path=None):
    session = requests.Session()
    session.headers.update({"User-Agent": INSTAGRAM_UA})
    jar = _load_cookie_jar(cookie_path)
    session.cookies.update(jar)
    response = session.get(url, timeout=20)
    response.raise_for_status()
    return extract_image_candidates_from_html(response.text)


def inspect_image_candidates_diagnostics(url, cookie_path=None):
    session = requests.Session()
    session.headers.update({"User-Agent": INSTAGRAM_UA})
    jar = _load_cookie_jar(cookie_path)
    cookies_loaded = bool(jar)
    session.cookies.update(jar)
    response = session.get(url, timeout=20)
    response.raise_for_status()
    candidates = extract_image_candidates_from_html(response.text)
    return {
        "status_code": response.status_code,
        "cookies_loaded": cookies_loaded,
        "candidate_count": len(candidates),
        "candidate_sources": [candidate.get("source") for candidate in candidates],
        "candidates": candidates,
        "html": response.text,
        "session": session,
    }


def _choose_best_candidate(candidates):
    if not candidates:
        return None

    def rank(candidate):
        width = candidate.get("width") or 0
        height = candidate.get("height") or 0
        source = candidate.get("source") or ""
        source_bonus = 1000000 if source == "image_versions2" else 0
        return source_bonus + (width * height), width, height

    return max(candidates, key=rank)


def _rank_candidates(candidates):
    if not candidates:
        return []

    def rank(candidate):
        width = candidate.get("width") or 0
        height = candidate.get("height") or 0
        source = candidate.get("source") or ""
        source_bonus = 1000000 if source == "image_versions2" else 0
        return source_bonus + (width * height), width, height

    return sorted(candidates, key=rank, reverse=True)


def _ext_from_url_or_content_type(url, content_type):
    ext = Path((url or "").split("?")[0]).suffix.lstrip(".").lower()
    if ext and len(ext) <= 5:
        return "jpg" if ext == "jpeg" else ext

    ctype = (content_type or "").split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "image/avif": "avif",
        "image/svg+xml": "svg",
    }
    return mapping.get(ctype, "jpg")


def download_instagram_html_fallback(url, download_path, metadata_dir, cookie_path, registry_record):
    _ = metadata_dir
    _ = registry_record
    try:
        diagnostics = inspect_image_candidates_diagnostics(url, cookie_path=cookie_path)
    except requests.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
        logger.warning("Instagram HTML fallback HTTP status code: %s", status_code)
        return None
    except Exception as exc:
        logger.warning("Instagram HTML fallback failed before candidate extraction: %s", exc)
        return None

    candidates = diagnostics.get("candidates") or []
    logger.warning("Instagram HTML fallback HTTP status code: %s", diagnostics.get("status_code"))
    logger.warning("Instagram HTML fallback cookies loaded: %s", diagnostics.get("cookies_loaded"))
    logger.warning("Instagram HTML fallback image candidate count: %s", len(candidates))
    logger.warning(
        "Instagram HTML fallback first 3 candidate sources: %s",
        [candidate.get("source") for candidate in candidates[:3]],
    )

    if not candidates:
        return None

    session = diagnostics.get("session") or requests.Session()
    ordered_candidates = _rank_candidates(candidates)
    errors = []
    user_agent = (getattr(session, "headers", {}) or {}).get("User-Agent", INSTAGRAM_UA)
    page_metadata = extract_page_metadata_from_html(diagnostics.get("html") or "")

    for candidate in ordered_candidates:
        image_url = candidate.get("url")
        if isinstance(image_url, str) and "&amp;" in image_url:
            logger.warning("unescaped HTML entities in image URL")
        if isinstance(image_url, str):
            image_url = html_lib.unescape(image_url)
        source = candidate.get("source")
        image_headers = {
            "User-Agent": user_agent,
            "Referer": url,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        status_code = "unknown"
        content_type = ""
        try:
            with session.get(image_url, headers=image_headers, stream=True, timeout=30) as response:
                status_code = response.status_code
                content_type = response.headers.get("Content-Type", "")
                logger.warning(
                    "Instagram HTML fallback candidate download status source=%s status=%s content-type=%s",
                    source,
                    status_code,
                    content_type or "unknown",
                )
                response.raise_for_status()
                if not content_type.lower().startswith("image/"):
                    raise RuntimeError(f"unexpected content-type: {content_type or 'unknown'}")
                ext = _ext_from_url_or_content_type(image_url, content_type)
                target_path = str(Path(download_path).with_suffix(f".{ext}"))
                Path(target_path).parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            handle.write(chunk)
                return {
                    "downloaded_path": target_path,
                    "image_url": image_url,
                    "ext": ext,
                    "source": source,
                    "page_metadata": page_metadata,
                }
        except Exception as exc:
            response = getattr(exc, "response", None)
            if response is not None:
                status_code = getattr(response, "status_code", status_code)
                content_type = getattr(response, "headers", {}).get("Content-Type", content_type)
            logger.warning(
                "Instagram HTML fallback candidate failed source=%s status=%s content-type=%s error=%s",
                source,
                status_code,
                content_type or "unknown",
                exc,
            )
            errors.append(
                f"{source}(status={status_code}, content_type={content_type or 'unknown'}, error={exc})"
            )

    raise RuntimeError(
        "Instagram HTML fallback found image candidates but failed to download any of them: "
        + "; ".join(errors)
    )


def _download_video_entry(entry, media_dir, stem, cookie_path, video_download):
    output_template = os.path.join(media_dir, f"{stem}.%(ext)s")
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

    run_id = Path(output_dir).name

    inspect_opts = {
        "cookiefile": cookie_path,
        "format": (video_download or {}).get("format", "bestvideo[height<=?1080]+bestaudio/best"),
        "noplaylist": False,
        "ignoreerrors": True,
        "writeinfojson": False,
    }

    info = None
    page_metadata = {}
    used_html_fallback = False
    downloaded_files = []
    items = []
    is_carousel = False
    try:
        with yt_dlp.YoutubeDL(inspect_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        download_error_cls = getattr(getattr(yt_dlp, "utils", None), "DownloadError", None)
        is_download_error = bool(download_error_cls and isinstance(exc, download_error_cls))
        message = str(exc)
        if is_download_error:
            logger.warning("yt-dlp extract_info failed: %s", message)
        if is_download_error and "No video formats found" in message:
            logger.warning("No video formats found; trying Instagram HTML fallback")
            fallback = download_instagram_html_fallback(
                url=url,
                download_path=os.path.join(output_dir, f"{VENDOR_INSTAGRAM}__{vendor_id}.jpg"),
                metadata_dir=metadata_dir,
                cookie_path=cookie_path,
                registry_record=registry_record,
            )
            if fallback:
                page_metadata = fallback.get("page_metadata") or {}
                downloaded_path = fallback["downloaded_path"]
                ext = fallback.get("ext") or "jpg"
                info = {
                    "id": vendor_id,
                    "title": page_metadata.get("title") or page_metadata.get("caption"),
                    "uploader": page_metadata.get("uploader"),
                    "ext": ext,
                    "display_url": fallback.get("image_url"),
                }
                used_html_fallback = True
                items = [{"index": 1, "type": "image", "filename": os.path.basename(downloaded_path)}]
                downloaded_files = [downloaded_path]
                is_carousel = False
            else:
                raise RuntimeError("No downloadable Instagram media entries were found") from exc
        else:
            raise

    if not used_html_fallback:
        entries = _resolve_entries(info)
        is_carousel = len(entries) > 1

        media_dir = output_dir

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
                stem = f"{run_id}__{i:02d}" if is_carousel else run_id
                downloaded_path = _download_video_entry(entry, media_dir, stem, cookie_path, video_download)
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

            stem = f"{run_id}__{i:02d}" if is_carousel else run_id
            image_path = os.path.join(media_dir, f"{stem}.{ext}")
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
            logger.warning("No yt-dlp downloadable media entries; trying Instagram HTML fallback")
            fallback = download_instagram_html_fallback(
                url=url,
                download_path=os.path.join(output_dir, f"{VENDOR_INSTAGRAM}__{vendor_id}.jpg"),
                metadata_dir=metadata_dir,
                cookie_path=cookie_path,
                registry_record=registry_record,
            )
            if fallback:
                page_metadata = fallback.get("page_metadata") or {}
                downloaded_path = fallback["downloaded_path"]
                ext = fallback.get("ext") or "jpg"
                prior_title = info.get("title") if isinstance(info, dict) else None
                prior_uploader = info.get("uploader") if isinstance(info, dict) else None
                info = {
                    "id": vendor_id,
                    "title": page_metadata.get("title") or page_metadata.get("caption") or prior_title,
                    "uploader": prior_uploader or page_metadata.get("uploader"),
                    "ext": ext,
                    "display_url": fallback.get("image_url"),
                }
                used_html_fallback = True
                items = [{"index": 1, "type": "image", "filename": os.path.basename(downloaded_path)}]
                downloaded_files = [downloaded_path]
                is_carousel = False

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
    compact["source_url"] = url
    compact["media_type"] = "carousel" if len(items) > 1 else items[0]["type"]
    compact["downloaded_file"] = downloaded_path
    compact["shortcode"] = vendor_id
    compact["title"] = page_metadata.get("title") if page_metadata else (info.get("title") if isinstance(info, dict) else None)
    compact["caption"] = page_metadata.get("caption") if page_metadata else None
    compact["uploader"] = compact.get("uploader") or (page_metadata.get("uploader") if page_metadata else None)

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
