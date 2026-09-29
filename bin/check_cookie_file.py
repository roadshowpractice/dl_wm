#!/usr/bin/env python3
"""Show what igp.cookies.load_netscape_cookies makes of a cookies.txt, without values:
name, domain, path, secure, httpOnly, expires, value length.
Usage: check_cookie_file.py <cookies.txt> [site, default instagram.com]"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from igp.cookies import load_netscape_cookies

for c in load_netscape_cookies(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "instagram.com"):
    exp = c.get("expires", -1)
    exps = "session" if exp in (-1, None) else time.strftime("%Y-%m-%d", time.gmtime(exp))
    print(f"{c['name']:12} {c.get('domain',''):16} {c.get('path',''):3} secure={c.get('secure')} httpOnly={c.get('httpOnly')} expires={exps} len={len(str(c.get('value','')))}")
