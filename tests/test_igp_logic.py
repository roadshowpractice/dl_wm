from pathlib import Path
from igp.extract import extract_shortcode, structured_extract, loose_extract_from_text
from igp.cookies import load_netscape_cookies
from igp.select import looks_like_junk, dedupe_pairs, dedupe_urls


def test_shortcode_extraction():
    assert extract_shortcode("https://www.instagram.com/p/ABC123xyz/") == "ABC123xyz"


def test_load_netscape_cookies(tmp_path: Path):
    p = tmp_path / "c.txt"
    p.write_text(".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tabc\n")
    cookies = load_netscape_cookies(p)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "sessionid"


def test_structured_extract_from_sample_json():
    obj = {"xdt_api__v1__media__shortcode__web_info": {"items": [{"code": "SC", "image_versions2": {"candidates": [{"url": "https://cdninstagram.com/a.jpg", "width": 10, "height": 10}]}}]}}
    out = structured_extract(obj, "SC")
    assert ("image", "https://cdninstagram.com/a.jpg") in out


def test_loose_extract():
    t = '"https://cdninstagram.com/x.jpg?x=1&y=2"'
    out = loose_extract_from_text(t)
    assert out == ["https://cdninstagram.com/x.jpg?x=1&y=2"]


def test_junk_filtering():
    assert looks_like_junk("https://static.cdninstagram.com/rsrc.php/x.png")
    assert not looks_like_junk("https://cdninstagram.com/media.mp4")


def test_dedupe_and_preference_helpers():
    assert dedupe_pairs([("image", "u1"), ("image", "u1")]) == [("image", "u1")]
    assert dedupe_urls(["u1", "u1", "u2"]) == ["u1", "u2"]
