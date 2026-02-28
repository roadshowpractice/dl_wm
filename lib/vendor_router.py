import re
from urllib.parse import parse_qs, urlparse


INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
VENDOR_INSTAGRAM = "instagram"
VENDOR_YOUTUBE = "youtube"


def detect_vendor(url: str):
    """Detect content vendor from a URL hostname/path."""
    if not url:
        return None

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").strip("/")

    if host in INSTAGRAM_HOSTS:
        if path.startswith("reel/") or path.startswith("p/"):
            return VENDOR_INSTAGRAM

    if host in YOUTUBE_HOSTS:
        if host == "youtu.be":
            return VENDOR_YOUTUBE
        if path.startswith("watch") or path.startswith("shorts/"):
            return VENDOR_YOUTUBE

    return None


def extract_vendor_id(vendor: str, url: str):
    """Extract vendor-specific media ID from supported URL patterns."""
    if not vendor or not url:
        return None

    parsed = urlparse(url)
    path = (parsed.path or "").strip("/")

    if vendor == VENDOR_INSTAGRAM:
        match = re.match(r"^(?:reel|p)/([^/?#]+)/?", path)
        return match.group(1) if match else None

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

    return None


def infer_kind(vendor: str, url: str):
    """Infer optional media kind from URL."""
    parsed = urlparse(url or "")
    path = (parsed.path or "").strip("/")

    if vendor == VENDOR_INSTAGRAM:
        if path.startswith("reel/"):
            return "reel"
        if path.startswith("p/"):
            return "post"

    if vendor == VENDOR_YOUTUBE:
        if path.startswith("shorts/"):
            return "short"
        if path.startswith("watch") or (parsed.hostname or "").lower() == "youtu.be":
            return "video"

    return None


def metadata_filename(vendor: str, vendor_id: str, fallback: str = "unknown") -> str:
    resolved_vendor = vendor or fallback
    resolved_vendor_id = vendor_id or fallback
    return f"{resolved_vendor}__{resolved_vendor_id}.json"


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
