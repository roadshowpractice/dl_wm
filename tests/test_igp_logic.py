from pathlib import Path
from igp.extract import extract_shortcode, structured_extract, loose_extract_from_text
from igp.cookies import load_netscape_cookies
from igp.select import (
    looks_like_junk,
    dedupe_pairs,
    dedupe_urls,
    select_loose_urls,
)


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


def test_loose_selection_prefers_non_cropped_variant():
    cropped = "https://cdninstagram.com/v/t51.2885-15/684121759_18585559582042905_5411042431120702235_n.jpg?stp=c307.0.921.921a_dst-jpg_e35_s640x640&foo=1"
    uncropped = "https://cdninstagram.com/v/t51.2885-15/684121759_18585559582042905_5411042431120702235_n.jpg?stp=dst-jpg_e35_tt6&foo=2"
    out = select_loose_urls([cropped, uncropped])
    assert out == [uncropped]


def test_loose_selection_collapses_variants_to_single_best_size():
    s640 = "https://cdninstagram.com/v/t51.2885-15/684121759_18585559582042905_5411042431120702235_n.jpg?stp=dst-jpg_e35_s640x640"
    s720 = "https://cdninstagram.com/v/t51.2885-15/684121759_18585559582042905_5411042431120702235_n.jpg?stp=dst-jpg_e35_s720x720"
    s1080 = "https://cdninstagram.com/v/t51.2885-15/684121759_18585559582042905_5411042431120702235_n.jpg?stp=dst-jpg_e35_s1080x1080"
    out = select_loose_urls([s640, s1080, s720])
    assert out == [s1080]


def test_loose_selection_preserves_carousel_order_across_assets():
    a720 = "https://cdninstagram.com/v/t51.2885-15/111_n.jpg?stp=dst-jpg_e35_s720x720"
    a1080 = "https://cdninstagram.com/v/t51.2885-15/111_n.jpg?stp=dst-jpg_e35_s1080x1080"
    b640 = "https://cdninstagram.com/v/t51.2885-15/222_n.jpg?stp=dst-jpg_e35_s640x640"
    b1080 = "https://cdninstagram.com/v/t51.2885-15/222_n.jpg?stp=dst-jpg_e35_s1080x1080"
    out = select_loose_urls([a720, b640, a1080, b1080])
    assert out == [a1080, b1080]


def test_loose_selection_preserves_mp4_urls():
    img = "https://cdninstagram.com/v/t51.2885-15/333_n.jpg?stp=dst-jpg_e35_s1080x1080"
    mp4 = "https://cdninstagram.com/v/t50.2886-16/987654321_1.mp4?foo=bar"
    out = select_loose_urls([img, mp4])
    assert out == [img, mp4]
