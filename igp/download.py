import json, subprocess, hashlib, sys
from pathlib import Path


def run(outdir, shortcode, cookie_file):
    out = Path(outdir)
    manifest = out / "manifest.jsonl"
    urls = [u.strip() for u in (out / "media_urls.txt").read_text(errors="ignore").splitlines() if u.strip()]
    n = ok = fail = 0
    for url in urls:
        n += 1
        clean = url.split("?", 1)[0]
        ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else "bin"
        if ext not in {"jpg", "jpeg", "png", "webp", "mp4"}:
            ext = "bin"
        file = out / f"{n:03d}.{ext}"
        cmd = ["curl", "-L", "--silent", "--show-error", "--fail", "-A", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "-e", "https://www.instagram.com/", "-H", "Referer: https://www.instagram.com/", "-H", "Origin: https://www.instagram.com", "-H", "Accept: */*", "-b", cookie_file, url, "-o", str(file)]
        if subprocess.run(cmd).returncode != 0:
            file.unlink(missing_ok=True)
            fail += 1
            continue
        sha = hashlib.sha256(file.read_bytes()).hexdigest()
        size = file.stat().st_size
        mime = subprocess.run(["file", "-b", "--mime-type", str(file)], capture_output=True, text=True).stdout.strip()
        with manifest.open("a") as mf:
            mf.write(json.dumps({"n": n, "shortcode": shortcode, "file": str(file), "sha256": sha, "size": size, "mime": mime, "url": url}, ensure_ascii=False) + "\n")
        ok += 1
    print(f"download_ok={ok}")
    print(f"download_failed={fail}")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3])
