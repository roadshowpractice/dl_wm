import json
import sys
from pathlib import Path


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


def run(outdir, shortcode):
    out = Path(outdir)
    structured = [("video" if ".mp4" in u.split("?")[0].lower() else "image", u) for u in (out / "structured_media_urls.txt").read_text(errors="ignore").splitlines() if u.strip()]
    loose_raw = [u for u in (out / "loose_media_urls.txt").read_text(errors="ignore").splitlines() if u.strip()]
    structured_clean = dedupe_pairs(structured)
    loose_clean = [u for u in dedupe_urls(loose_raw) if not looks_like_junk(u)]
    if structured_clean:
        final = structured_clean
        mode = "structured"
    else:
        final = [("video" if ".mp4" in u.split("?")[0].lower() else "image", u) for u in loose_clean]
        mode = "loose"
    (out / "media_urls.txt").write_text("\n".join(u for _, u in final) + ("\n" if final else ""))
    with (out / "selected_items.jsonl").open("w") as f:
        for i, (kind, u) in enumerate(final, 1):
            f.write(json.dumps({"n": i, "shortcode": shortcode, "kind": kind, "mode": mode, "url": u}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
