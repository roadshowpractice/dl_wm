#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from downloaders.instagram import inspect_image_candidates_diagnostics


def main():
    parser = argparse.ArgumentParser(description="Inspect Instagram HTML image candidates")
    parser.add_argument("url", help="Instagram post URL")
    parser.add_argument("--cookies", "--cookie-file", dest="cookie_file", default="", help="Optional cookie file path")
    args = parser.parse_args()

    diagnostics = inspect_image_candidates_diagnostics(args.url, cookie_path=args.cookie_file)
    print(f"HTTP status: {diagnostics['status_code']}")
    print(f"Cookies loaded: {diagnostics['cookies_loaded']}")
    print(f"Candidate count: {diagnostics['candidate_count']}")
    print("Candidate source names: og:image/display_url/thumbnail_src/image_versions2")
    for source in diagnostics["candidate_sources"]:
        print(f"- {source}")


if __name__ == "__main__":
    main()
