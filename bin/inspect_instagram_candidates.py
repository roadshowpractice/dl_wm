#!/usr/bin/env python3
import argparse
import json

from downloaders.instagram import inspect_image_candidates


def main():
    parser = argparse.ArgumentParser(description="Inspect Instagram HTML image candidates")
    parser.add_argument("url", help="Instagram post URL")
    parser.add_argument("--cookie-file", default="", help="Optional cookie file path")
    args = parser.parse_args()

    candidates = inspect_image_candidates(args.url, cookie_path=args.cookie_file)
    print(json.dumps(candidates, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
