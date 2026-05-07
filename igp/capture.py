import asyncio
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from igp.cookies import load_netscape_cookies
from igp.extract import build_post_model

IMAGE_EXTS = {".jpg", ".jpeg", ".webp", ".png"}
CANDIDATE_PATTERN = r"(?:https?:\\/\\/|https?:\\u002F\\u002F|https?://|//)[^\"'\s<>()]+"


@dataclass
class CaptureRequest:
    url: str
    shortcode: str
    cookie_file: Path
    outdir: Path
    requested_start: int | None = None
    requested_end: int | None = None
    headless: bool = True
    rounds: int = 1
    allow_fallback: bool = False


POST_QUERY_MARKERS = {
    "xdt_shortcode_media",
    "xdt_api__v1__media__shortcode__web_info",
    "PolarisPostActionLoadPostQueryQuery",
}

NON_POST_GRAPHQL_MARKERS = {
    "lightspeed",
    "inbox",
    "messaging",
}


def parse_capture_args(argv):
    if len(argv) < 4:
        raise ValueError("usage: capture URL SHORTCODE COOKIE_FILE OUTDIR [START] [END]")
    start = argv[4] if len(argv) > 4 else None
    end = argv[5] if len(argv) > 5 else None
    requested_start, requested_end = _parse_requested_range(start, end)
    return CaptureRequest(
        url=argv[0],
        shortcode=argv[1],
        cookie_file=Path(argv[2]),
        outdir=Path(argv[3]),
        requested_start=requested_start,
        requested_end=requested_end,
    )


def looks_like_junk(url):
    junk_bits = ["static.cdninstagram.com", "rsrc.php", "s150x150", "_s150x150", "profile_pic", "t51.2885-19", "t51.82787-19"]
    return any(bit in url for bit in junk_bits)


def media_group_key(url):
    return Path(urlparse(url).path).name or url


def normalize_media_url(url):
    normalized = html.unescape(url.strip())
    normalized = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), normalized)
    normalized = normalized.replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&").replace("\\u003D", "=")
    normalized = html.unescape(normalized)
    for _ in range(2):
        if "%" not in normalized:
            break
        decoded = unquote(normalized)
        if decoded == normalized:
            break
        normalized = decoded
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"
    return normalized


def allowed_media_host(host):
    host = host.lower()
    if host == "scontent.cdninstagram.com":
        return True
    if host.endswith(".cdninstagram.com"):
        return True
    if host.endswith(".fbcdn.net") and (host.startswith("instagram.") or host.startswith("scontent.")):
        return True
    return False


def is_media_url(url):
    parsed = urlparse(url)
    if not allowed_media_host(parsed.netloc) or looks_like_junk(url):
        return False
    ext = Path(parsed.path).suffix.lower()
    return ext in IMAGE_EXTS or ext == ".mp4"


def extract_candidate_urls(text):
    candidates, seen = [], set()
    for raw in re.findall(CANDIDATE_PATTERN, text):
        normalized = normalize_media_url(raw)
        if is_media_url(normalized) and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)
    return candidates


def parse_stp(url):
    return parse_qs(urlparse(url).query).get("stp", [""])[0]


def is_cropped_variant(url):
    return bool(re.search(r"c\d+\.\d+\.\d+\.\d+a_", parse_stp(url)))


def parse_square_size(url):
    match = re.search(r"s(\d+)x(\d+)", parse_stp(url))
    return min(int(match.group(1)), int(match.group(2))) if match else None


def variant_score(url):
    path = urlparse(url).path.lower()
    return (10000 if path.endswith(".mp4") else 0) + (2000 if not is_cropped_variant(url) else 0) + (parse_square_size(url) or 900)


def add_candidate(url, candidates_by_asset, discovery_order):
    normalized = normalize_media_url(url)
    if not is_media_url(normalized):
        return
    asset_key = media_group_key(normalized)
    if asset_key not in discovery_order:
        discovery_order[asset_key] = len(discovery_order) + 1
    variants = candidates_by_asset.setdefault(asset_key, [])
    if normalized not in variants:
        variants.append(normalized)


def rank_fallback_assets(captured):
    candidates_by_asset = {}
    discovery_order = {}
    for rec in captured:
        response_url = rec.get("url", "")
        add_candidate(response_url, candidates_by_asset, discovery_order)
        for candidate in extract_candidate_urls(rec.get("text", "")):
            add_candidate(candidate, candidates_by_asset, discovery_order)
    ordered_assets = sorted(discovery_order, key=discovery_order.get)
    ranked = []
    for asset_key in ordered_assets:
        variants = candidates_by_asset.get(asset_key, [])
        if not variants:
            continue
        best_variant = max(enumerate(variants), key=lambda item: (variant_score(item[1]), -item[0]))[1]
        ranked.append({"asset": asset_key, "url": best_variant, "variants": variants})
    return ranked


def select_target_assets(post_model, requested_start, requested_end):
    assets = post_model.get("assets", [])
    if requested_start is None and requested_end is None:
        return assets
    start = requested_start if requested_start is not None else 1
    end = requested_end if requested_end is not None else len(assets)
    if end < start:
        return []
    return [a for a in assets if start <= (a.get("carousel_index") or 0) <= end]


def _parse_requested_range(start_arg, end_arg):
    def _coerce(val):
        if val is None:
            return None
        iv = int(val)
        return iv if iv > 0 else None

    start = _coerce(start_arg)
    end = _coerce(end_arg)
    if start is None and end is None:
        return None, None
    if start is None:
        start = end
    if end is None:
        end = start
    return start, end


def _best_variant_for_asset(asset):
    vids = asset.get("candidates", {}).get("video_versions", [])
    imgs = asset.get("candidates", {}).get("image_candidates", [])
    media_type = asset.get("media_type")
    preferred = vids if media_type == "video" and vids else imgs
    variants = [v.get("url") for v in preferred if isinstance(v, dict) and v.get("url")]
    if not variants:
        return None, []
    best = max(enumerate(variants), key=lambda item: (variant_score(item[1]), -item[0]))[1]
    return best, variants


def find_post_model(captured, shortcode):
    for rec in captured:
        text = rec.get("text", "")
        lowered = text.lower()
        has_target_marker = any(marker in text for marker in POST_QUERY_MARKERS) or shortcode in text
        if not has_target_marker:
            continue
        if any(marker in lowered for marker in NON_POST_GRAPHQL_MARKERS):
            continue
        try:
            post_model = build_post_model(json.loads(text), shortcode)
        except Exception:
            post_model = build_post_model(text, shortcode)
        if post_model:
            return post_model
    return None


async def capture_responses(request: CaptureRequest):
    from playwright.async_api import async_playwright

    captured = []
    request.outdir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=request.headless, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(viewport={"width": 1280, "height": 900}, user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
        cookies = load_netscape_cookies(request.cookie_file)
        if cookies:
            await context.add_cookies(cookies)
        page = await context.new_page()

        async def on_response(response):
            try:
                response_url = response.url
                if not ("instagram.com" in response_url or "fbcdn.net" in response_url or "cdninstagram.com" in response_url):
                    return
                text = await response.text()
                if not (request.shortcode in text or "image_versions2" in text or "video_versions" in text or "xdt_api__v1__media__shortcode__web_info" in text or ".mp4" in text or ".jpg" in text or ".webp" in text):
                    return
                captured.append({"url": response_url, "status": response.status, "content_type": response.headers.get("content-type", ""), "text": text})
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto(request.url, wait_until="domcontentloaded", timeout=60000)
        for _ in range(request.rounds):
            await page.wait_for_timeout(2500)
            try:
                await page.mouse.wheel(0, 700)
                await page.wait_for_timeout(500)
                await page.mouse.wheel(0, -700)
            except Exception:
                pass
            for label in ["Next", "Go to next", "Next photo"]:
                try:
                    loc = page.get_by_label(label)
                    if await loc.count():
                        await loc.first.click(timeout=1000)
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass
        await browser.close()
    return captured


async def download_structured_assets(context, assets, outdir, request, post_model):
    rows = []
    for asset in assets:
        best_url, variants = _best_variant_for_asset(asset)
        if not best_url:
            continue
        idx = asset.get("carousel_index")
        ext = Path(urlparse(best_url).path).suffix.lower() or ".bin"
        dest = outdir / f"{idx:03d}{ext}"
        status = "ok"
        try:
            resp = await context.request.get(best_url)
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status}")
            dest.write_bytes(await resp.body())
        except Exception as e:
            status = f"error: {e}"
        rows.append({"shortcode": request.shortcode, "requested_start": request.requested_start, "requested_end": request.requested_end, "carousel_index": idx, "carousel_count": post_model.get("carousel_count", 0), "source_shortcode": post_model.get("shortcode"), "source_media_id": post_model.get("media_id"), "parent_shortcode": post_model.get("shortcode"), "media_type": asset.get("media_type"), "extraction_reason": "target_post_asset", "path": dest.name, "selected_url": best_url, "variants_considered": len(variants), "owner": post_model.get("owner"), "collaborators": post_model.get("collaborators", []), "caption": post_model.get("caption", ""), "status": status})
    return rows


async def download_fallback_assets(context, assets, outdir):
    rows = []
    for index, asset in enumerate(assets, 1):
        best_url = asset["url"]
        ext = Path(urlparse(best_url).path).suffix.lower() or ".bin"
        dest = outdir / f"{index:03d}{ext}"
        status = "ok"
        try:
            resp = await context.request.get(best_url)
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status}")
            dest.write_bytes(await resp.body())
        except Exception as e:
            status = f"error: {e}"
        rows.append({"index": index, "asset": asset["asset"], "url": best_url, "path": dest.name, "status": status, "variants_considered": len(asset["variants"])})
    return rows


def write_manifest(rows, manifest_path):
    with Path(manifest_path).open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_metadata(post_model, metadata_path):
    Path(metadata_path).write_text(json.dumps({"shortcode": post_model.get("shortcode"), "caption": post_model.get("caption"), "owner": post_model.get("owner"), "collaborators": post_model.get("collaborators", []), "carousel_count": post_model.get("carousel_count", 0)}, ensure_ascii=False, indent=2))


async def run_capture(request: CaptureRequest):
    out = request.outdir
    out.mkdir(parents=True, exist_ok=True)
    captured = await capture_responses(request)
    post_model = find_post_model(captured, request.shortcode)

    context = None
    browser = None
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=request.headless, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context()
            rows = await _decide_and_download(request, captured, post_model, context, out)
            await browser.close()
    except ModuleNotFoundError:
        rows = await _decide_and_download(request, captured, post_model, context, out)

    write_manifest(rows, out / "manifest.jsonl")
    (out / "captured_responses.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in captured), encoding="utf-8")


async def _decide_and_download(request, captured, post_model, context, out):
    if post_model:
        selected = select_target_assets(post_model, request.requested_start, request.requested_end)
        rows = await download_structured_assets(context, selected, out, request, post_model)
        write_metadata(post_model, out / "post_metadata.json")
        return rows
    if request.allow_fallback:
        fallback_assets = rank_fallback_assets(captured)
        rows = await download_fallback_assets(context, fallback_assets, out)
        metadata_path = out / "post_metadata.json"
        if metadata_path.exists():
            metadata_path.unlink()
        if not rows:
            return [{"status": "no_candidates", "responses_saved": len(captured), "extracted_candidates": 0}]
        return rows
    return [{"status": "no_post_model", "shortcode": request.shortcode, "responses_saved": len(captured)}]


if __name__ == "__main__":
    req = parse_capture_args(sys.argv[1:])
    asyncio.run(run_capture(req))
