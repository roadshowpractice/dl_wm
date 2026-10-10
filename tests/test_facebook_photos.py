import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT))

# Load by path: the call_download tests leave stub "downloaders.*" modules in sys.modules.
# Their lib stubs (vendor_router, tasks_lib, ...) are set aside while loading, then put back.
_STUBBED = ("vendor_router", "tasks_lib", "teton_utils", "lib.vendor_router", "lib.metadata_compactor", "lib.teton_utils")
_saved = {name: sys.modules.pop(name) for name in _STUBBED if name in sys.modules}
_spec = importlib.util.spec_from_file_location("facebook_photos_under_test", ROOT / "downloaders" / "facebook_photos.py")
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)
from lib.vendor_router import detect_vendor, extract_vendor_id, infer_kind
sys.modules.update(_saved)


def _photo(pid, w, h, full_w, full_h):
    return {
        "__typename": "Photo",
        "id": pid,
        "image": {"uri": f"https://scontent.example/{pid}_s.jpg", "width": w, "height": h},
        "viewer_image": {"height": full_h, "width": full_w, "uri": f"https://scontent.example/{pid}_full.jpg"},
    }


def _page(body):
    return "<html><head><title>Tim Ballard - Thank you Salt Lake Tribune</title></head><body><script>" + body + "</script></body></html>"


def test_multi_photo_post_uses_viewer_image_in_order_and_dedupes():
    nodes = [{"media": _photo("1", 536, 590, 884, 973)}, {"media": _photo("2", 536, 590, 3720, 4096)},
             {"media": _photo("1", 536, 590, 884, 973)}]
    html = _page('{"all_subattachments":' + json.dumps({"count": 3, "nodes": nodes}) + '}')
    photos = fp.extract_post_photos(html)
    assert [p["id"] for p in photos] == ["1", "2"]
    assert photos[1]["uri"].endswith("2_full.jpg")
    assert (photos[1]["width"], photos[1]["height"]) == (3720, 4096)


def test_single_photo_post_from_attachments():
    att = [{"media": {"__typename": "Photo", "id": "9"}, "styles": {"attachment": {"media": _photo("9", 600, 600, 2048, 2048)}}}]
    html = _page('{"attachments":' + json.dumps(att) + '}')
    photos = fp.extract_post_photos(html)
    assert len(photos) == 1 and photos[0]["uri"].endswith("9_full.jpg")


def test_photo_viewer_page_takes_largest_image():
    html = _page('"image":{"uri":"https:\\/\\/scontent.example\\/small.jpg","width":320,"height":320}'
                 '"image":{"uri":"https:\\/\\/scontent.example\\/big.jpg","width":3720,"height":4096}')
    photos = fp.extract_post_photos(html)
    assert photos == [{"id": None, "uri": "https://scontent.example/big.jpg", "width": 3720, "height": 4096}]


def test_video_post_has_no_photos():
    att = [{"media": {"__typename": "Video", "id": "5"}}]
    assert fp.extract_post_photos(_page('{"attachments":' + json.dumps(att) + '}')) == []


def test_post_meta():
    html = _page('{"message":{"ranges":[],"text":"Thank you Salt Lake Tribune"},"creation_time":1791498695,'
                 '"owning_profile":{"__typename":"User","name":"Tim Ballard","id":"1"}}')
    meta = fp.extract_post_meta(html)
    assert meta["caption"] == "Thank you Salt Lake Tribune"
    assert meta["owner"] == "Tim Ballard"
    assert meta["creation_time"].startswith("2026-10-08T")


@pytest.mark.parametrize("url,vid,kind", [
    ("https://www.facebook.com/officialtimballard/posts/pfbid02Kv", "pfbid02Kv", "post"),
    ("https://www.facebook.com/photo/?fbid=1669259094571234", "1669259094571234", "photo"),
    ("https://www.facebook.com/photo.php?fbid=42&set=a.1", "42", "photo"),
    ("https://www.facebook.com/share/p/19JuWspt1u/", "19JuWspt1u", "post"),
    ("https://www.facebook.com/permalink.php?story_fbid=123&id=4", "123", "post"),
    ("https://www.facebook.com/someone/videos/987/", "987", "video"),
])
def test_router_facebook_post_and_photo_urls(url, vid, kind):
    assert detect_vendor(url) == "facebook"
    assert extract_vendor_id("facebook", url) == vid
    assert infer_kind("facebook", url) == kind


def test_unavailable_page_raises_block_error(tmp_path, monkeypatch):
    class Resp:
        text = _page("This content isn't available right now")
        url = "https://www.facebook.com/x/posts/1"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fp.requests.Session, "get", lambda self, url, timeout=0: Resp())
    with pytest.raises(RuntimeError, match="content not available to this account"):
        fp.download("https://www.facebook.com/x/posts/1", str(tmp_path), str(tmp_path), {}, None)


def test_download_marks_perform_download_for_call_router(tmp_path, monkeypatch):
    nodes = [{"media": _photo("1", 536, 590, 884, 973)}, {"media": _photo("2", 536, 590, 3720, 4096)}]
    page = _page('{"creation_time":1791498695,"all_subattachments":' + json.dumps({"count": 2, "nodes": nodes}) + '}')

    class Resp:
        url = "https://www.facebook.com/x/posts/1"
        headers = {"Content-Type": "image/jpeg"}
        content = b"jpg"

        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fp.requests.Session, "get", lambda self, url, timeout=0: Resp(page))
    result = fp.download("https://www.facebook.com/x/posts/1", str(tmp_path / "out"), str(tmp_path / "meta"), {}, None)
    meta = json.loads(Path(result["metadata_path"]).read_text())
    assert meta["default_tasks"]["perform_download"] == result["files"][0]
    assert meta["video_date"] == "20261008"
    assert meta["url"] == "https://www.facebook.com/x/posts/1"
    assert [i["filename"] for i in meta["items"]] == ["facebook__1__01.jpg", "facebook__1__02.jpg"]
