"""Facebook photo posts (single photo or multi-photo) -> full-size images.

yt-dlp only handles Facebook video, so photo posts come through here instead.
Facebook serves the full post data (Relay JSON inside the HTML) to a logged-in
request that looks like a real browser navigation; without the Sec-Fetch /
client-hint headers it returns an empty JS shell. Each photo node carries a
`viewer_image` (full resolution) next to the feed-size `image`, so one page
fetch is enough for every photo in the post.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from http.cookiejar import MozillaCookieJar

import requests

from lib.metadata_compactor import build_compact_metadata
from lib.vendor_router import VENDOR_FACEBOOK, extract_vendor_id, metadata_filename

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="141", "Google Chrome";v="141"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
}

# Shown instead of the post when the account is blocked by the page owner or the post is gone.
UNAVAILABLE_MARKERS = ("This content isn't available right now", "This content isn\\u2019t available")


class NoPhotosFound(Exception):
    """The page loaded but has no photo attachments (e.g. a video post)."""


def _decode_json_at(text, start):
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    return obj


def _best_image(media):
    for key in ("viewer_image", "photo_image", "image"):
        img = media.get(key)
        if isinstance(img, dict) and img.get("uri"):
            return img
    return None


def extract_post_photos(html):
    """Return [{id, uri, width, height}] for the first post on the page, in post order."""
    photos = []

    def add(media):
        if not isinstance(media, dict) or media.get("__typename") != "Photo":
            return
        img = _best_image(media)
        if img and not any(p["id"] == media.get("id") for p in photos):
            photos.append({"id": media.get("id"), "uri": img["uri"], "width": img.get("width"), "height": img.get("height")})

    # Multi-photo post: all_subattachments.nodes[].media
    m = re.search(r'"all_subattachments":\{', html)
    if m:
        block = _decode_json_at(html, m.end() - 1)
        for node in block.get("nodes") or []:
            add((node or {}).get("media"))
        if photos:
            return photos

    # Single-photo post: attachments[].media / styles.attachment.media
    for m in re.finditer(r'"attachments":\[\{', html):
        try:
            attachments = _decode_json_at(html, m.end() - 2)
        except ValueError:
            continue
        for att in attachments:
            add((att or {}).get("media"))
            add((((att or {}).get("styles") or {}).get("attachment") or {}).get("media"))
        if photos:
            return photos

    # Photo viewer page (/photo/?fbid=...): the largest "image" on the page.
    best = None
    for m in re.finditer(r'"image":\{"uri":"((?:[^"\\]|\\.)+)","width":(\d+),"height":(\d+)\}', html):
        w, h = int(m.group(2)), int(m.group(3))
        if not best or w * h > best["width"] * best["height"]:
            best = {"id": None, "uri": json.loads(f'"{m.group(1)}"'), "width": w, "height": h}
    if best and best["width"] >= 600:
        photos.append(best)
    return photos


def extract_post_meta(html):
    meta = {"caption": None, "owner": None, "creation_time": None, "title": None}
    t = re.search(r"<title>([^<]*)</title>", html)
    if t:
        meta["title"] = t.group(1)
    m = re.search(r'"message":\{', html)
    if m:
        try:
            meta["caption"] = _decode_json_at(html, m.end() - 1).get("text")
        except ValueError:
            pass
    c = re.search(r'"creation_time":(\d+)', html)
    if c:
        meta["creation_time"] = datetime.fromtimestamp(int(c.group(1)), tz=timezone.utc).isoformat()
    o = re.search(r'"owning_profile":\{"__typename":"(?:User|Page)","name":"((?:[^"\\]|\\.)*)"', html)
    if o:
        meta["owner"] = json.loads(f'"{o.group(1)}"')
    elif meta["title"] and " - " in meta["title"]:
        meta["owner"] = meta["title"].split(" - ", 1)[0]
    return meta


def _session(cookie_path):
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    if cookie_path:
        jar = MozillaCookieJar(cookie_path)
        jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies = jar
    return session


def download(url, output_dir, metadata_dir, registry_record, cookie_path, video_download=None):
    vendor_id = extract_vendor_id(VENDOR_FACEBOOK, url)
    if not vendor_id:
        raise ValueError("Could not extract Facebook post/photo ID from URL")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    session = _session(cookie_path)
    response = session.get(url, timeout=30)
    response.raise_for_status()
    html = response.text
    if any(marker in html for marker in UNAVAILABLE_MARKERS) and "all_subattachments" not in html:
        raise RuntimeError(f"Facebook: content not available to this account (blocked or deleted): {url}")

    photos = extract_post_photos(html)
    if not photos:
        raise NoPhotosFound(f"No photo attachments found at {url}")

    meta = extract_post_meta(html)
    multi = len(photos) > 1
    items, files = [], []
    session.headers.update({"Sec-Fetch-Dest": "image", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "cross-site"})
    for i, photo in enumerate(photos, start=1):
        img = session.get(photo["uri"], timeout=60)
        img.raise_for_status()
        ext = "png" if "image/png" in img.headers.get("Content-Type", "") else "jpg"
        stem = f"{VENDOR_FACEBOOK}__{vendor_id}__{i:02d}" if multi else f"{VENDOR_FACEBOOK}__{vendor_id}"
        dest = os.path.join(output_dir, f"{stem}.{ext}")
        with open(dest, "wb") as fh:
            fh.write(img.content)
        files.append(dest)
        items.append({"index": i, "type": "image", "photo_id": photo["id"], "width": photo["width"],
                      "height": photo["height"], "bytes": len(img.content), "filename": os.path.basename(dest)})
        logger.info("facebook photo %s/%s: %s (%sx%s)", i, len(photos), dest, photo["width"], photo["height"])

    metadata_path = os.path.join(metadata_dir, metadata_filename(VENDOR_FACEBOOK, vendor_id))
    # Same compact shape as the yt-dlp downloaders, so default_tasks.perform_download is set
    # and call_router counts the download as done.
    created = int(datetime.fromisoformat(meta["creation_time"]).timestamp()) if meta["creation_time"] else None
    info = {"id": vendor_id, "title": meta["title"], "uploader": meta["owner"], "timestamp": created,
            "ext": os.path.splitext(files[0])[1].lstrip("."),
            "width": photos[0]["width"], "height": photos[0]["height"]}
    compact = build_compact_metadata(info, url=url, vendor=VENDOR_FACEBOOK, vendor_id=vendor_id, downloaded_path=files[0])
    compact.update({
        "source_url": url,
        "final_url": response.url,
        "vendor": VENDOR_FACEBOOK,
        "vendor_id": vendor_id,
        "media_type": "carousel" if multi else "image",
        "title": meta["title"],
        "caption": meta["caption"],
        "uploader": meta["owner"],
        "creation_time": meta["creation_time"],
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "downloaded_file": files[0],
        "items": items,
    })
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, ensure_ascii=False)

    return {
        **(registry_record or {}),
        "vendor": VENDOR_FACEBOOK,
        "vendor_id": vendor_id,
        "metadata_file": os.path.basename(metadata_path),
        "metadata_path": metadata_path,
        "original_filename": files[0],
        "to_process": files[0],
        "files": files,
    }
