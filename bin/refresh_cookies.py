#!/usr/bin/env python3
"""Refresh (export/check) browser cookies as a Netscape cookies.txt.

Borrowed from dl_wm's bin/export_browser_cookies.py and bin/check_cookie_file.py,
merged into one self-contained tool so every repo can regenerate its own cookie
file instead of committing one.

Cookie VALUES are never printed. Only names, domains, expiry and value length.

Export from a live browser profile (needs yt_dlp, already a repo dependency):

    bin/refresh_cookies.py instagram.com conf/instagram.cookies.<persona>.txt \
        [--browser chrome] [--profile "~/.config/google-chrome/Profile 2"]

Check an existing cookies.txt without exposing values:

    bin/refresh_cookies.py --check conf/instagram.cookies.<persona>.txt [instagram.com]

Safety:
  * output is chmod 0600
  * refuses to write a file git already tracks (or that git would track) unless
    --force; the whole point is that cookie files stay out of the repo
  * exits 1 if no cookie matched the domain, so a stale/empty export is obvious

Chrome must be closed for a clean export (the tool copies the DB, but a live
profile can hold the newest session in memory).
"""
import argparse
import os
import subprocess
import sys
from http.cookiejar import MozillaCookieJar

# Never commit cookie files; keep this suffix consistent across repos.
IGNORE_HINT = "*.cookies.txt"


def _git(args, cwd):
    try:
        return subprocess.run(
            ["git", "-C", str(cwd)] + args,
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return None


def _repo_root(path):
    cwd = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(cwd):
        return None
    r = _git(["rev-parse", "--show-toplevel"], cwd)
    if r is None or r.returncode != 0:
        return None
    return r.stdout.strip()


def _git_state(path):
    """Return ('tracked'|'ignored'|'untracked'|'no-repo', relpath)."""
    root = _repo_root(path)
    if not root:
        return "no-repo", path
    abs_path = os.path.abspath(path)
    rel = os.path.relpath(abs_path, root)
    tracked = _git(["ls-files", "--error-unmatch", "--", rel], root)
    if tracked is not None and tracked.returncode == 0:
        return "tracked", rel
    ignored = _git(["check-ignore", "-q", "--", rel], root)
    if ignored is not None and ignored.returncode == 0:
        return "ignored", rel
    return "untracked", rel


def export(domain, out_file, browser, profile, force):
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
    except Exception as exc:  # pragma: no cover - depends on env
        sys.exit(f"refresh_cookies: yt_dlp missing ({exc}); install repo requirements")

    state, rel = _git_state(out_file)
    if state == "tracked" and not force:
        sys.exit(
            f"refresh_cookies: refusing to overwrite git-tracked file {rel}.\n"
            f"  Untrack it first (it must not live in the repo), or pass --force."
        )

    prof = os.path.expanduser(profile) if profile else None
    try:
        jar = extract_cookies_from_browser(browser, prof)
    except Exception as exc:
        sys.exit(f"refresh_cookies: cannot read {browser} profile {prof or '(default)'}: {exc}")

    out = MozillaCookieJar(out_file)
    matched = 0
    for c in jar:
        if c.domain.lstrip(".").endswith(domain):
            out.set_cookie(c)
            matched += 1
    if not matched:
        sys.exit(f"refresh_cookies: no {domain} cookies in {browser} profile {prof or '(default)'}; nothing written")

    os.makedirs(os.path.dirname(os.path.abspath(out_file)) or ".", exist_ok=True)
    out.save(ignore_discard=True, ignore_expires=True)
    os.chmod(out_file, 0o600)

    state, rel = _git_state(out_file)
    where = {"tracked": "TRACKED BY GIT — fix now", "untracked": f"not ignored by git (add {IGNORE_HINT})",
             "ignored": "git-ignored", "no-repo": "outside a git repo"}[state]
    print(f"refresh_cookies: {matched} {domain} cookies -> {out_file} (mode 0600; {where})")
    print("  names: " + " ".join(sorted(c.name for c in out)))


def check(path, domain):
    jar = MozillaCookieJar(path)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as exc:
        sys.exit(f"refresh_cookies: cannot read {path}: {exc}")
    import time
    rows = [c for c in jar if not domain or c.domain.lstrip(".").endswith(domain)]
    if not rows:
        sys.exit(f"refresh_cookies: no {domain or 'any'} cookies in {path}")
    print(f"{path}: {len(rows)} cookies" + (f" for {domain}" if domain else ""))
    for c in sorted(rows, key=lambda x: (x.domain, x.name)):
        exp = c.expires
        if not exp:
            when = "session"
        elif exp > 32503680000:  # year 3000: Chrome-style units, not Unix seconds
            when = f"out-of-range(epoch={int(exp)})"
        else:
            when = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(exp))
        print(f"  {c.name:24} {c.domain:24} {c.path:4} secure={bool(c.secure)} "
              f"expires={when} len={len(str(c.value))}")
    print("  (values withheld)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export or check browser cookies (values never printed).")
    ap.add_argument("domain", nargs="?", help="domain suffix to export/check, e.g. instagram.com")
    ap.add_argument("out", nargs="?", help="output cookies.txt path (export mode)")
    ap.add_argument("--check", metavar="COOKIES_TXT", help="inspect an existing file instead of exporting")
    ap.add_argument("--browser", default="chrome",
                    help="chrome|chromium|brave|edge|firefox|... (default chrome)")
    ap.add_argument("--profile", default=None,
                    help='browser profile dir (default: the browser default), e.g. "~/.config/google-chrome/Profile 2"')
    ap.add_argument("--force", action="store_true",
                    help="allow overwriting a git-tracked file (normally refused)")
    a = ap.parse_args(argv)

    if a.check:
        check(a.check, a.domain)
        return 0
    if not a.domain or not a.out:
        ap.error("export needs <domain> <out_file> (or use --check FILE)")
    export(a.domain, a.out, a.browser, a.profile, a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
