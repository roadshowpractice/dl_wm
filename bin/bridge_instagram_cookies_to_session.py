"""Bridge a Netscape-format Instagram cookies.txt (yt-dlp/browser-exported)
into a native instaloader session file.

Not a blind format conversion: it loads the cookies into a real instaloader
context and calls context.test_login(), which makes a live request to
Instagram to confirm the session is actually authenticated and to resolve
the real username straight from Instagram's own answer, before anything is
trusted or saved. A cookie file with an expired/missing sessionid fails
loudly here instead of silently producing a session file that doesn't work.

Usage:
    python bin/bridge_instagram_cookies_to_session.py conf/instagram.cookies.txt
    python bin/bridge_instagram_cookies_to_session.py conf/instagram.cookies.txt --out conf/instaloader_session_justin
"""
import argparse
import http.cookiejar
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.append(root_dir)

import instaloader
from instaloader.instaloader import get_default_session_filename


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cookie_file", help="Path to a Netscape-format cookies.txt")
    parser.add_argument("--out", help="Explicit session file output path (default: instaloader's own default location for the resolved username)")
    args = parser.parse_args()

    if not os.path.exists(args.cookie_file):
        print(f"FAILED: cookie file not found: {args.cookie_file}", file=sys.stderr)
        sys.exit(1)

    jar = http.cookiejar.MozillaCookieJar()
    jar.load(args.cookie_file, ignore_discard=True, ignore_expires=True)

    L = instaloader.Instaloader(quiet=True)
    L.context.update_cookies(jar)

    username = L.context.test_login()
    if not username:
        print(
            f"FAILED: cookies in {args.cookie_file} are not a valid/active Instagram login. "
            f"test_login() got no user back from Instagram — session is expired, was never fully "
            f"authenticated (e.g. missing sessionid), or was revoked. Re-export cookies from a real "
            f"logged-in browser session and try again.",
            file=sys.stderr,
        )
        sys.exit(1)

    L.context.username = username
    L.save_session_to_file(args.out)

    saved_path = args.out or get_default_session_filename(username)
    print(f"OK: verified live session for @{username} (source: {args.cookie_file})")
    print(f"Saved instaloader session to: {saved_path}")
    print(
        f'Add to conf/app_config.json -> "instagram": '
        f'{{"username": "{username}", "session_file": "{saved_path}"}}'
    )


if __name__ == "__main__":
    main()
