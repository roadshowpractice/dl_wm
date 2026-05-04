import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def dedupe_pairs(pairs):
    seen = set()
    out = []
    for kind, u in pairs:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append((kind, u))
    return out


def dedupe_urls(urls):
    seen = set()
    out = []
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def looks_like_junk(u):
    junk_bits = ["static.cdninstagram.com", "rsrc.php", "s150x150", "_s150x150", "profile_pic", "t51.2885-19", "t51.82787-19"]
    return any(bit in u for bit in junk_bits)


def media_group_key(u):
    return Path(urlparse(u).path).name or u


def parse_stp(u):
    stp = parse_qs(urlparse(u).query).get("stp", [""])[0]
    return stp


def is_cropped_variant(u):
    stp = parse_stp(u)
    return bool(re.search(r"c\d+\.\d+\.\d+\.\d+a_", stp))


def parse_square_size(u):
    stp = parse_stp(u)
    m = re.search(r"s(\d+)x(\d+)", stp)
    if not m:
        return None
    return min(int(m.group(1)), int(m.group(2)))


def variant_score(u):
    base = 10000 if ".mp4" in urlparse(u).path.lower() else 0
    cropped = is_cropped_variant(u)
    size = parse_square_size(u)

    # Prefer non-cropped first, then highest available size.
    uncropped_score = 2000 if not cropped else 0
    size_score = size if size is not None else 900
    return base + uncropped_score + size_score


def select_loose_urls(loose_raw):
    loose_clean = [u for u in dedupe_urls(loose_raw) if not looks_like_junk(u)]
    groups = []
    by_key = {}
    for u in loose_clean:
        key = media_group_key(u)
        if key not in by_key:
            by_key[key] = []
            groups.append(key)
        by_key[key].append(u)

    selected = []
    for key in groups:
        candidates = by_key[key]
        best = max(enumerate(candidates), key=lambda it: (variant_score(it[1]), -it[0]))[1]
        selected.append(best)
    return selected


def run(outdir, shortcode):
    out = Path(outdir)
    structured = [("video" if ".mp4" in u.split("?")[0].lower() else "image", u) for u in (out / "structured_media_urls.txt").read_text(errors="ignore").splitlines() if u.strip()]
    loose_raw = [u for u in (out / "loose_media_urls.txt").read_text(errors="ignore").splitlines() if u.strip()]
    structured_clean = dedupe_pairs(structured)
    if structured_clean:
        final = structured_clean
        mode = "structured"
    else:
        final = [("video" if ".mp4" in u.split("?")[0].lower() else "image", u) for u in select_loose_urls(loose_raw)]
        mode = "loose"
    (out / "media_urls.txt").write_text("\n".join(u for _, u in final) + ("\n" if final else ""))
    with (out / "selected_items.jsonl").open("w") as f:
        for i, (kind, u) in enumerate(final, 1):
            f.write(json.dumps({"n": i, "shortcode": shortcode, "kind": kind, "mode": mode, "url": u}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
