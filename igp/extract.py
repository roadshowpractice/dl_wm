import json
import re
import sys
from pathlib import Path


def extract_shortcode(url):
    m = re.search(r"instagram\.com/p/([^/?#]+)", url)
    if not m:
        return ""
    return m.group(1)


def best_image(obj):
    candidates = obj.get("image_versions2", {}).get("candidates", [])
    if not candidates:
        return None
    best = max(candidates, key=lambda x: (x.get("width", 0) or 0) * (x.get("height", 0) or 0))
    return best.get("url")


def best_video(obj):
    versions = obj.get("video_versions", [])
    if not versions:
        return None
    best = max(versions, key=lambda x: (x.get("width", 0) or 0) * (x.get("height", 0) or 0))
    return best.get("url")


def structured_extract(obj, target):
    structured_items = []

    def add_structured_media(item):
        u = best_video(item)
        if u:
            structured_items.append(("video", u))
            return
        u = best_image(item)
        if u:
            structured_items.append(("image", u))

    def handle_item(item):
        if not isinstance(item, dict):
            return
        if item.get("code") != target:
            return
        carousel = item.get("carousel_media")
        if isinstance(carousel, list) and carousel:
            for child in carousel:
                if isinstance(child, dict):
                    add_structured_media(child)
        else:
            add_structured_media(item)

    def walk(x):
        if isinstance(x, dict):
            if "xdt_api__v1__media__shortcode__web_info" in x:
                info = x["xdt_api__v1__media__shortcode__web_info"]
                for item in info.get("items", []):
                    handle_item(item)
            if "xdt_shortcode_media" in x:
                handle_item(x["xdt_shortcode_media"])
            handle_item(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, str):
            if x.startswith("{") and (target in x or "image_versions2" in x or "video_versions" in x or "xdt_api__v1__media__shortcode__web_info" in x):
                try:
                    walk(json.loads(x))
                except Exception:
                    pass

    walk(obj)
    return structured_items


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
