import os
from glob import glob

from dl_wm.vendor_router import VENDOR_FACEBOOK, VENDOR_INSTAGRAM, VENDOR_YOUTUBE
from dl_wm.teton_utils import resolve_repo_path


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

    candidates.extend(_normalize_cookie_list(video_download_cfg.get(f"{vendor}_cookie_paths")))

    vendor_singular = {
        VENDOR_INSTAGRAM: "instagram_cookie_path",
        VENDOR_FACEBOOK: "facebook_cookie_path",
        VENDOR_YOUTUBE: "youtube_cookie_path",
    }.get(vendor)
    if vendor_singular:
        cookie_path = video_download_cfg.get(vendor_singular)
        if cookie_path:
            candidates.append(cookie_path)

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
                os.path.relpath(path, resolve_repo_path("."))
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
