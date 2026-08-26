"""Real, non-mocked run of the actual download pipeline against the
tbfrescue.org Vimeo videos (inputs/tbfrescue_vimeo.json).

No stubbed subprocess, no faked config, no mocked yt-dlp output — this
imports the real lib.vendor_router and downloaders modules and calls them
exactly as bin/call_download.py does, then reports what actually happened.
Hits live network.
"""
import json
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "lib"))

from lib.vendor_router import detect_vendor, VENDOR_INSTAGRAM, VENDOR_FACEBOOK, VENDOR_YOUTUBE
from downloaders.instagram import download as download_instagram
from downloaders.facebook import download as download_facebook
from downloaders.youtube import download as download_youtube

INPUT_FILE = os.path.join(root_dir, "inputs", "tbfrescue_vimeo.json")
OUTPUT_DIR = os.path.join(root_dir, "outputs", "tbfrescue_vimeo_live_test")
METADATA_DIR = os.path.join(root_dir, "metadata", "tbfrescue_vimeo_live_test")


def main():
    videos = json.load(open(INPUT_FILE))["videos"]
    results = []

    for v in videos:
        url = v["embed_url"]
        vendor = detect_vendor(url)

        if vendor not in {VENDOR_INSTAGRAM, VENDOR_FACEBOOK, VENDOR_YOUTUBE}:
            result = {
                "id": v["id"],
                "url": url,
                "vendor_detected": vendor,
                "success": False,
                "error": f"detect_vendor() returned {vendor!r} — no supported downloader for this URL",
            }
        else:
            downloader = {
                VENDOR_INSTAGRAM: download_instagram,
                VENDOR_FACEBOOK: download_facebook,
                VENDOR_YOUTUBE: download_youtube,
            }[vendor]
            real_result = downloader(url, OUTPUT_DIR, METADATA_DIR, {}, None, {})
            result = {"id": v["id"], "url": url, "vendor_detected": vendor, **real_result}

        results.append(result)
        status = "OK" if result.get("success") else "FAIL"
        print(f"[{status}] {v['id']} ({v['section']}): {result.get('error') or 'downloaded'}")

    n_ok = sum(r.get("success") for r in results)
    print(f"\n{n_ok}/{len(results)} actually downloaded via the real pipeline.")
    return results


if __name__ == "__main__":
    main()
