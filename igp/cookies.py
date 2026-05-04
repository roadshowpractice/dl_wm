from pathlib import Path


def load_netscape_cookies(path: Path):
    cookies = []
    if not path.exists():
        print(f"WARNING: missing cookie file: {path}")
        return cookies

    for line in path.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue

        http_only = False
        if line.startswith("#HttpOnly_"):
            line = line.replace("#HttpOnly_", "", 1)
            http_only = True
        elif line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) != 7:
            continue

        domain, _flag, path_, secure, expires, name, value = parts
        if "instagram.com" not in domain:
            continue

        try:
            expires_i = int(expires)
        except Exception:
            expires_i = -1

        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path_ or "/",
                "secure": secure.upper() == "TRUE",
                "httpOnly": http_only,
                "expires": expires_i if expires_i > 0 else -1,
                "sameSite": "Lax",
            }
        )
    return cookies


if __name__ == "__main__":
    import sys
    p = Path(sys.argv[1])
    print(len(load_netscape_cookies(p)))
