"""Paginate a public IG profile's timeline via GraphQL response sniffing,
collecting {code, taken_at, caption, carousel_count} for every post reachable
by scrolling. Independent of igp/capture.py's single-post capture flow, but
shares its cookie loader.

Usage:
    python3 -m igp.profile_history <username> <cookie_file> <outdir> [max_rounds]

Writes <outdir>/<username>_timeline.jsonl, one record per post, oldest first.
"""
import asyncio
import json
import sys
from pathlib import Path

from igp.cookies import load_netscape_cookies


def extract_posts_from_json(obj, found):
    """Walk arbitrary nested JSON looking for post-like nodes.

    The private-API timeline schema (xdt_api__v1__feed__user_timeline_graphql_connection)
    keys the post id as "code" with caption/taken_at inline; older public
    GraphQL schemas use "shortcode" with edge_media_to_caption. Support both.
    """
    if isinstance(obj, dict):
        code = obj.get("code") or obj.get("shortcode")
        if code and ("taken_at" in obj or "taken_at_timestamp" in obj):
            taken = obj.get("taken_at") or obj.get("taken_at_timestamp")
            caption = obj.get("caption")
            if isinstance(caption, dict):
                caption = caption.get("text", "")
            elif caption is None:
                edges = (obj.get("edge_media_to_caption") or {}).get("edges") or []
                caption = edges[0]["node"]["text"] if edges else ""
            carousel_count = obj.get("carousel_media_count") or len(obj.get("carousel_media") or []) or 0
            collaborators = []
            for k in ("coauthor_producers", "invited_coauthor_producers"):
                for user in obj.get(k) or []:
                    if isinstance(user, dict) and user.get("username"):
                        collaborators.append(user["username"])
            found[code] = {
                "shortcode": code,
                "taken_at": taken,
                "caption": (caption or "")[:200],
                "carousel_count": carousel_count,
                "collaborators": sorted(set(collaborators)),
            }
        for v in obj.values():
            extract_posts_from_json(v, found)
    elif isinstance(obj, list):
        for item in obj:
            extract_posts_from_json(item, found)


async def scrape(username, cookie_file, max_rounds=150, stall_limit=6):
    from playwright.async_api import async_playwright

    found = {}
    stall_rounds = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 2200},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        )
        cookies = load_netscape_cookies(cookie_file)
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        async def on_response(response):
            try:
                if "instagram.com" not in response.url:
                    return
                if "json" not in response.headers.get("content-type", ""):
                    return
                text = await response.text()
                if '"taken_at"' not in text or '"caption"' not in text:
                    return
                before = len(found)
                extract_posts_from_json(json.loads(text), found)
                after = len(found)
                if after > before:
                    print(f"  +{after - before} posts (total {after})")
            except Exception:
                pass

        page.on("response", on_response)

        await page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(4)

        for i in range(max_rounds):
            before_count = len(found)
            await page.mouse.wheel(0, 4000)
            await asyncio.sleep(1.5)
            print(f"round {i+1}/{max_rounds}: total={len(found)}")
            if len(found) == before_count:
                stall_rounds += 1
            else:
                stall_rounds = 0
            if stall_rounds >= stall_limit:
                print(f"no new posts for {stall_limit} rounds in a row, assuming end of feed")
                break

        await browser.close()

    return found


def main():
    username = sys.argv[1]
    cookie_file = Path(sys.argv[2])
    outdir = Path(sys.argv[3])
    max_rounds = int(sys.argv[4]) if len(sys.argv) > 4 else 150
    outdir.mkdir(parents=True, exist_ok=True)

    found = asyncio.run(scrape(username, cookie_file, max_rounds))

    out_path = outdir / f"{username}_timeline.jsonl"
    with open(out_path, "w") as f:
        for rec in sorted(found.values(), key=lambda r: (r["taken_at"] or 0)):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nTotal unique posts collected: {len(found)}")
    print(f"Written to: {out_path}")


if __name__ == "__main__":
    main()
