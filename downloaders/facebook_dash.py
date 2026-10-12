"""Facebook reels/videos that yt-dlp can't parse ("Cannot parse data").

Plain-language write-up: docs/facebook_reels_cannot_parse.md.

Facebook serves some reel pages (all of Alan Mortensen's so far, 2026-10) with the video links in a
different place from where yt-dlp's extractor looks. The links are still on the page, in a list called
`all_video_dash_prefetch_representations`: the video in several sizes plus the sound as a separate
track (DASH). This module opens the page read-only in headless Chrome with the cookie file, reads that
list, downloads the best video (short side <= 1080, like the yt-dlp default format) and the audio, and
joins them with ffmpeg (stream copy, no re-encode). Date, uploader, caption and length come from the
post's own data on the same page. The page it read is kept next to the video as `<stem>.page.html`.
"""
import json
import logging
import os
import re
import shutil
import subprocess
from http.cookiejar import MozillaCookieJar

import requests

from lib.metadata_compactor import build_compact_metadata, write_raw_metadata
from lib.teton_utils import load_app_config
from lib.vendor_router import VENDOR_FACEBOOK, extract_vendor_id, metadata_filename

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
CHROME = "/usr/bin/google-chrome"
MAX_SHORT_SIDE = 1080


class NoStreamsFound(Exception):
    """The page loaded but has no DASH streams for this video id."""


def is_cannot_parse_error(exc):
    return "Cannot parse data" in str(exc)


def fetch_page(url, cookie_path, wait_ms=8000):
    """Open the page headless (read-only) and return [page html, graphql bodies...]."""
    from playwright.sync_api import sync_playwright

    cookies = []
    if cookie_path:
        jar = MozillaCookieJar(cookie_path)
        jar.load(ignore_discard=True, ignore_expires=True)
        cookies = [dict(name=c.name, value=c.value, domain=c.domain, path=c.path, secure=bool(c.secure)) for c in jar]
    bodies = []
    with sync_playwright() as p:
        kw = {"headless": True, "args": ["--headless=new"]}
        if os.path.exists(CHROME):
            kw["executable_path"] = CHROME
        browser = p.chromium.launch(**kw)
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US", user_agent=UA)
            if cookies:
                ctx.add_cookies(cookies)
            page = ctx.new_page()

            def on_resp(resp):
                if "/api/graphql" in resp.url:
                    try:
                        bodies.append(resp.text())
                    except Exception:
                        pass

            page.on("response", on_resp)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(wait_ms)
            bodies.insert(0, page.content())
        finally:
            browser.close()
    return bodies


def find_streams(bodies, video_id):
    """All DASH representations listed for video_id: (videos, audios), each a list of dicts."""
    dec = json.JSONDecoder()
    reps = {}
    for text in bodies:
        for m in re.finditer(r'"all_video_dash_prefetch_representations":', text):
            try:
                groups, _ = dec.raw_decode(text, m.end())
            except ValueError:
                continue
            for grp in groups if isinstance(groups, list) else []:
                if str(grp.get("video_id")) != str(video_id):
                    continue
                for rep in grp.get("representations") or []:
                    if rep.get("base_url"):
                        reps[rep["base_url"]] = rep
    videos = [r for r in reps.values() if "video" in str(r.get("mime_type", ""))]
    audios = [r for r in reps.values() if "audio" in str(r.get("mime_type", ""))]
    return videos, audios


def pick_streams(videos, audios, max_short_side=MAX_SHORT_SIDE):
    def dims(r):
        w, h = int(r.get("width") or 0), int(r.get("height") or 0)
        return w, h, min(w, h) if w and h else max(w, h)

    fitting = [r for r in videos if dims(r)[2] <= max_short_side] or videos
    video = max(fitting, key=lambda r: (dims(r)[2], int(r.get("bandwidth") or 0)))
    audio = max(audios, key=lambda r: int(r.get("bandwidth") or 0)) if audios else None
    return video, audio


def _json_blobs(text):
    dec = json.JSONDecoder()
    for m in re.finditer(r'<script type="application/json"[^>]*>', text):
        try:
            obj, _ = dec.raw_decode(text, m.end())
        except ValueError:
            continue
        yield obj
    if text.lstrip().startswith("{"):  # graphql responses: one or more JSON objects per line
        for line in text.splitlines():
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _first(obj, key):
    for d in _walk(obj):
        if key in d and d[key] not in (None, "", [], {}):
            return d[key]
    return None


def find_post_info(bodies, video_id):
    """Date, uploader, caption and length of the post that carries video_id.

    The post is the smallest object with a `creation_time` whose data contains the video id as an
    `id` (a page also carries suggested reels, each in its own post object).
    """
    best = None
    for text in bodies:
        for blob in _json_blobs(text):
            for d in _walk(blob):
                if "creation_time" not in d:
                    continue
                s = json.dumps(d, ensure_ascii=False)
                if f'"id": "{video_id}"' not in s:
                    continue
                if best is None or len(s) < best[0]:
                    best = (len(s), d)
    info = {}
    if best:
        post = best[1]
        info["timestamp"] = post.get("creation_time")
        actors = post.get("actors") or []
        if actors and isinstance(actors[0], dict):
            info["uploader"] = actors[0].get("name")
            info["uploader_id"] = actors[0].get("id")
        msg = _first(post, "message")
        if isinstance(msg, dict):
            info["description"] = msg.get("text")
    for text in bodies:  # the length sits on the Video node, which may be outside the post object
        m = re.search(r'"id":"%s"[^{}]{0,4000}?"length_in_second":([\d.]+)|"length_in_second":([\d.]+)[^{}]{0,4000}?"id":"%s"'
                      % (video_id, video_id), text)
        if m:
            info["duration"] = float(m.group(1) or m.group(2))
            break
    return info


def _fetch(url, path):
    with requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                          "-of", "json", path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def download(url, output_dir, metadata_dir, registry_record, cookie_path, video_download=None, bodies=None):
    """Same contract as downloaders.facebook.download. `bodies` = already-fetched page texts (tests)."""
    vendor_id = extract_vendor_id(VENDOR_FACEBOOK, url)
    if not vendor_id:
        raise ValueError("Could not extract Facebook video ID from URL")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not on PATH (needed to join the video and audio streams)")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)
    stem = f"{VENDOR_FACEBOOK}__{vendor_id}"

    if bodies is None:
        logger.info("Facebook page read (DASH fallback) for %s", url)
        bodies = fetch_page(url, cookie_path)
    with open(os.path.join(output_dir, f"{stem}.page.html"), "w", encoding="utf-8") as f:
        f.write(bodies[0])

    videos, audios = find_streams(bodies, vendor_id)
    logger.info("DASH fallback: %s video + %s audio streams for %s", len(videos), len(audios), vendor_id)
    if not videos:
        raise NoStreamsFound(f"no DASH video streams for {vendor_id} on the page (saved as {stem}.page.html)")
    video, audio = pick_streams(videos, audios)

    final = os.path.join(output_dir, f"{stem}.mp4")
    vpart, apart = final + ".video.part", final + ".audio.part"
    _fetch(video["base_url"], vpart)
    if audio:
        _fetch(audio["base_url"], apart)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", vpart, "-i", apart, "-c", "copy",
                        "-map", "0:v:0", "-map", "1:a:0", "-movflags", "+faststart", final], check=True)
        os.remove(apart)
        os.remove(vpart)
    else:
        logger.warning("DASH fallback: no audio stream listed for %s; video only", vendor_id)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", vpart, "-c", "copy", "-movflags", "+faststart", final], check=True)
        os.remove(vpart)

    probe = _probe(final)
    vstream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
    post = find_post_info(bodies, vendor_id)
    info = {
        "id": vendor_id,
        "title": (post.get("description") or "").split("\n")[0][:120] or f"Facebook video {vendor_id}",
        "description": post.get("description"),
        "timestamp": post.get("timestamp"),
        "uploader": post.get("uploader"),
        "uploader_id": post.get("uploader_id"),
        "duration": post.get("duration") or float(probe.get("format", {}).get("duration") or 0) or None,
        "width": vstream.get("width"),
        "height": vstream.get("height"),
        "ext": "mp4",
        "filesize": os.path.getsize(final),
        "webpage_url": url,
        "extractor": "dl_wm facebook_dash (page read; yt-dlp could not parse)",
        "formats_chosen": {
            "video": {k: video.get(k) for k in ("representation_id", "width", "height", "bandwidth", "codecs")},
            "audio": {k: audio.get(k) for k in ("representation_id", "bandwidth", "codecs")} if audio else None,
        },
        "has_audio": bool(audio),
    }

    compact = build_compact_metadata(info, url=url, vendor=VENDOR_FACEBOOK, vendor_id=vendor_id, downloaded_path=final)
    compact["download_method"] = "facebook_dash"
    raw_mode = (load_app_config() or {}).get("raw_metadata_mode", "gzip")
    raw_path = write_raw_metadata(info, metadata_dir=metadata_dir, vendor=VENDOR_FACEBOOK, vendor_id=vendor_id, mode=raw_mode)
    if raw_path:
        compact["raw_metadata_path"] = raw_path
    metadata_path = os.path.join(metadata_dir, metadata_filename(VENDOR_FACEBOOK, vendor_id))
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, ensure_ascii=False)

    return {
        **(registry_record or {}),
        "vendor": VENDOR_FACEBOOK,
        "vendor_id": vendor_id,
        "metadata_file": os.path.basename(metadata_path),
        "metadata_path": metadata_path,
        "original_filename": final,
        "to_process": final,
    }
