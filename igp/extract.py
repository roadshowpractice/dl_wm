import json
import html
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def extract_shortcode(url):
    m = re.search(r"instagram\.com/p/([^/?#]+)", url)
    if not m:
        return ""
    return m.group(1)


def parse_requested_img_index(url):
    vals = parse_qs(urlparse(url).query).get("img_index", [])
    if not vals:
        return None
    try:
        parsed = int(vals[0])
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _best_candidate(candidates):
    if not candidates:
        return None
    return max(candidates, key=lambda x: (x.get("width", 0) or 0) * (x.get("height", 0) or 0))


def _extract_caption(item):
    caption = (item.get("caption") or {}).get("text")
    if caption:
        return caption
    edges = (((item.get("edge_media_to_caption") or {}).get("edges")) or [])
    for edge in edges:
        text = ((edge or {}).get("node") or {}).get("text")
        if text:
            return text
    return ""


def _extract_owner(item):
    return item.get("user") or item.get("owner") or {}


def _extract_collaborators(item):
    out = []
    for k in ["coauthor_producers", "invited_coauthor_producers"]:
        for user in item.get(k) or []:
            if isinstance(user, dict):
                out.append(user)
    deduped = []
    seen = set()
    for user in out:
        key = user.get("id") or user.get("username") or json.dumps(user, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(user)
    return deduped


def _asset_from_item(child, idx):
    videos = child.get("video_versions") or []
    images = ((child.get("image_versions2") or {}).get("candidates")) or []
    media_type = "video" if videos else "image"
    return {
        "carousel_index": idx,
        "media_type": media_type,
        "candidates": {"video_versions": videos, "image_candidates": images},
    }


def build_post_model(obj, shortcode):
    post = None

    def _item_shortcode(item):
        return item.get("code") or item.get("shortcode")

    def _item_permalink_shortcode(item):
        permalink = item.get("permalink") or item.get("link")
        if not isinstance(permalink, str):
            return ""
        return extract_shortcode(permalink)

    def _item_matches_shortcode(item):
        if not isinstance(item, dict):
            return False
        item_shortcode = _item_shortcode(item)
        if item_shortcode == shortcode:
            return True
        if _item_permalink_shortcode(item) == shortcode:
            return True
        # Newer payloads sometimes nest the canonical media object.
        media = item.get("media") or item.get("node")
        if not isinstance(media, dict):
            return False
        return _item_shortcode(media) == shortcode or _item_permalink_shortcode(media) == shortcode

    def maybe_extract(item):
        nonlocal post
        if not isinstance(item, dict) or post is not None:
            return
        if not _item_matches_shortcode(item):
            return
        if isinstance(item.get("media"), dict):
            item = item["media"]
        elif isinstance(item.get("node"), dict):
            item = item["node"]
        carousel = item.get("carousel_media") if isinstance(item.get("carousel_media"), list) else None
        if not carousel:
            edges = (((item.get("edge_sidecar_to_children") or {}).get("edges")) or [])
            carousel = [((edge or {}).get("node") or {}) for edge in edges if isinstance(edge, dict)]
        children = carousel or [item]
        assets = [_asset_from_item(child, i) for i, child in enumerate(children, 1) if isinstance(child, dict)]
        post = {
            "shortcode": _item_shortcode(item) or shortcode,
            "media_id": item.get("pk") or item.get("id"),
            "taken_at": item.get("taken_at") or item.get("taken_at_timestamp"),
            "owner": _extract_owner(item),
            "caption": _extract_caption(item),
            "collaborators": _extract_collaborators(item),
            "carousel_count": item.get("carousel_media_count") or len(assets),
            "assets": assets,
        }

    def walk(x):
        if isinstance(x, dict):
            if "xdt_api__v1__media__shortcode__web_info" in x:
                info = x["xdt_api__v1__media__shortcode__web_info"] or {}
                for item in info.get("items", []):
                    maybe_extract(item)
                if isinstance(info.get("item"), dict):
                    maybe_extract(info.get("item"))
            if "xdt_shortcode_media" in x:
                maybe_extract(x["xdt_shortcode_media"])
            maybe_extract(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, str):
            if x.startswith("{") and shortcode in x:
                try:
                    walk(json.loads(x))
                except Exception:
                    pass

    def _extract_embedded_json_blobs(text):
        blobs = []
        for attrs, body in re.findall(r"(<script[^>]*>)(.*?)</script>", text, flags=re.IGNORECASE | re.DOTALL):
            if "application/json" in attrs or "__NEXT_DATA__" in attrs or "data-sjs" in attrs:
                body = (body or "").strip()
                if body.startswith("{") or body.startswith("["):
                    blobs.append(body)
        for marker in ["window._sharedData", "window.__additionalDataLoaded"]:
            for m in re.finditer(rf"{re.escape(marker)}\s*=\s*(\{{.*?\}});", text, flags=re.DOTALL):
                blobs.append(m.group(1))
        return blobs

    walk(obj)
    if post is None and isinstance(obj, str) and "<script" in obj and shortcode in obj:
        for blob in _extract_embedded_json_blobs(obj):
            try:
                walk(json.loads(html.unescape(blob)))
            except Exception:
                continue
    return post


def structured_extract(obj, target):
    model = build_post_model(obj, target)
    if not model:
        return []
    out = []
    for asset in model["assets"]:
        vids = asset["candidates"]["video_versions"]
        imgs = asset["candidates"]["image_candidates"]
        best = _best_candidate(vids) if vids else _best_candidate(imgs)
        if best and best.get("url"):
            out.append((asset["media_type"], best["url"]))
    return out


def loose_extract_from_text(text):
    out = []
    pat = r'https://[^"\\\s<>]+?\.(?:jpg|jpeg|webp|png|mp4)[^"\\\s<>]*'
    for u in re.findall(pat, text):
        u = u.replace("\\u0026", "&").replace("\\/", "/").replace("&amp;", "&")
        if "cdninstagram" in u or "fbcdn" in u:
            out.append(u)
    return out


def cmd_shortcode(url):
    sc = extract_shortcode(url)
    if not sc:
        raise SystemExit(f"ERROR: could not extract shortcode from URL: {url}")
    print(sc)


def cmd_media(captured_jsonl, shortcode, outdir):
    captured = Path(captured_jsonl)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    structured = []
    loose = []
    for line in captured.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        text = rec.get("text", "")
        loose.extend(loose_extract_from_text(text))
        try:
            structured.extend(structured_extract(json.loads(text), shortcode))
        except Exception:
            structured.extend(structured_extract(text, shortcode))

    (out / "structured_media_urls.txt").write_text("\n".join(u for _, u in structured) + ("\n" if structured else ""))
    (out / "loose_media_urls.txt").write_text("\n".join(loose) + ("\n" if loose else ""))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("Usage: python -m igp.extract shortcode URL | media captured_responses.jsonl SHORTCODE OUTDIR")
    mode = sys.argv[1]
    if mode == "shortcode":
        cmd_shortcode(sys.argv[2])
    elif mode == "media":
        cmd_media(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        raise SystemExit(f"unknown mode: {mode}")
