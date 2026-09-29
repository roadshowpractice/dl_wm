#!/usr/bin/env python3
"""Export one site's cookies from a local Chrome profile to a Netscape cookies.txt
(for bin/fb_post.py, yt-dlp, igp). Prints cookie names only, never values.
Usage: export_browser_cookies.py <domain_suffix> <out_file> [chrome_profile_dir]
  e.g. export_browser_cookies.py facebook.com conf/facebook.merrill.cookies.txt "~/.config/google-chrome/Profile 2"
"""
import os, sys
from http.cookiejar import MozillaCookieJar
from yt_dlp.cookies import extract_cookies_from_browser

dom, out = sys.argv[1], sys.argv[2]
prof = os.path.expanduser(sys.argv[3] if len(sys.argv) > 3 else "~/.config/google-chrome/Profile 2")
jar = extract_cookies_from_browser("chrome", prof)
o = MozillaCookieJar(out)
for c in jar:
    if c.domain.lstrip(".").endswith(dom):
        o.set_cookie(c)
o.save(ignore_discard=True, ignore_expires=True)
os.chmod(out, 0o600)
print(len(o), "cookies ->", out, ":", " ".join(sorted(c.name for c in o)))
