import re
from urllib.parse import parse_qs, urlparse


INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com"}
FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}
VENDOR_INSTAGRAM = "instagram"
VENDOR_FACEBOOK = "facebook"
VENDOR_YOUTUBE = "youtube"
VENDOR_VIMEO = "vimeo"


def detect_vendor(url: str):
    """Detect content vendor from a URL hostname/path."""
    if not url:
        return None

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").strip("/")

    if host in INSTAGRAM_HOSTS:
        if path.startswith("reel/") or path.startswith("reels/") or path.startswith("p/"):
            return VENDOR_INSTAGRAM

    if host in FACEBOOK_HOSTS:
        if (
            host == "fb.watch"
            or path.startswith("watch/")
            or path.startswith("reel/")
            or path.startswith("share/r/")
            or path.startswith("share/v/")
            or "/videos/" in path
        ):
            return VENDOR_FACEBOOK

    if host in YOUTUBE_HOSTS:
        if host == "youtu.be":
            return VENDOR_YOUTUBE
        if path.startswith("watch") or path.startswith("shorts/"):
            return VENDOR_YOUTUBE

    if host in VIMEO_HOSTS:
        if host == "player.vimeo.com":
            if path.startswith("video/"):
                return VENDOR_VIMEO
        elif re.match(r"^\d+", path):
            return VENDOR_VIMEO

    return None


def extract_vendor_id(vendor: str, url: str):
    """Extract vendor-specific media ID from supported URL patterns."""
    if not vendor or not url:
        return None

    parsed = urlparse(url)
    path = (parsed.path or "").strip("/")

    if vendor == VENDOR_INSTAGRAM:
        match = re.match(r"^(?:reel|reels|p)/([^/?#]+)/?", path)
        return match.group(1) if match else None

    if vendor == VENDOR_FACEBOOK:
        host = (parsed.hostname or "").lower()
        if host == "fb.watch":
            token = path.split("/")[0] if path else ""
            return token or None

        for pattern in [
            r"^reel/([^/?#]+)/?",
            r"^watch/\?v=([^/?#&]+)",
            r"^share/r/([^/?#]+)/?",
            r"^share/v/([^/?#]+)/?",
            r"^.+/videos/([^/?#]+)/?",
            r"^videos/([^/?#]+)/?",
        ]:
            if pattern.startswith("^watch/"):
                video_id = parse_qs(parsed.query).get("v", [None])[0]
                if video_id:
                    return video_id
                continue
            match = re.match(pattern, path)
            if match:
                return match.group(1)

    if vendor == VENDOR_YOUTUBE:
        host = (parsed.hostname or "").lower()
        if host == "youtu.be":
            token = path.split("/")[0] if path else ""
            return token or None

        if path == "watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            return video_id

        match = re.match(r"^shorts/([^/?#]+)/?", path)
        return match.group(1) if match else None

    if vendor == VENDOR_VIMEO:
        match = re.match(r"^(?:video/)?(\d+)", path)
        return match.group(1) if match else None

    return None


def infer_kind(vendor: str, url: str):
    """Infer optional media kind from URL."""
    parsed = urlparse(url or "")
    path = (parsed.path or "").strip("/")

    if vendor == VENDOR_INSTAGRAM:
        if path.startswith("reel/") or path.startswith("reels/"):
            return "reel"
        if path.startswith("p/"):
            return "post"

    if vendor == VENDOR_FACEBOOK:
        if path.startswith("reel/") or path.startswith("share/r/"):
            return "reel"
        if path.startswith("watch") or "/videos/" in path or path.startswith("share/v/"):
            return "video"

    if vendor == VENDOR_YOUTUBE:
        if path.startswith("shorts/"):
            return "short"
        if path.startswith("watch") or (parsed.hostname or "").lower() == "youtu.be":
            return "video"

    if vendor == VENDOR_VIMEO:
        return "video"

    return None


def metadata_filename(vendor: str, vendor_id: str, fallback: str = "unknown") -> str:
    resolved_vendor = vendor or fallback
    resolved_vendor_id = vendor_id or fallback
    return f"{resolved_vendor}__{resolved_vendor_id}.json"


def canonicalize_vendor_url(vendor: str, url: str):
    """Return a normalized URL for known vendors when possible."""
    if not vendor or not url:
        return url

    if vendor == VENDOR_YOUTUBE:
        vendor_id = extract_vendor_id(vendor, url)
        if vendor_id:
            return f"https://www.youtube.com/watch?v={vendor_id}"

    return url


def format_shortcode(vendor: str, token: str):
    """Normalize shortcode/index token to include vendor context.

    Returns `<vendor>__<token>` when both values are present. If `token` already
    has the exact vendor prefix, it is returned unchanged.
    """
    if not vendor or not token:
        return token

    prefix = f"{vendor}__"
    if token.startswith(prefix):
        return token

    return f"{prefix}{token}"
