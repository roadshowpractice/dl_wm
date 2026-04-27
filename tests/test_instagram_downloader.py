import importlib.util
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.modules.setdefault("yt_dlp", types.SimpleNamespace(YoutubeDL=None))
sys.modules.setdefault("tasks_lib", types.SimpleNamespace(load_default_tasks=lambda: {}))


class _FakeCookieJar(dict):
    def set(self, name, value, domain=None, path="/"):
        self[name] = value


class _FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, *_args, **_kwargs):
        raise AssertionError("Session.get should be monkeypatched in tests")


sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        Session=_FakeSession,
        cookies=types.SimpleNamespace(RequestsCookieJar=_FakeCookieJar),
    ),
)

MODULE_PATH = Path(__file__).resolve().parents[1] / "downloaders" / "instagram.py"
spec = importlib.util.spec_from_file_location("ig_downloader_test", MODULE_PATH)
ig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ig)


class FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=False):
        if download:
            raise AssertionError("extract_info should be inspection-only")
        return {
            "id": "ABC123",
            "title": "carousel",
            "entries": [
                {"id": "img1", "url": "https://cdn.example/1.jpg", "ext": "jpg"},
                {"id": "vid2", "formats": [{"format_id": "18"}], "ext": "mp4", "duration": 7},
                None,
                {"id": "img4", "thumbnail": "https://cdn.example/4.jpg", "ext": "jpg"},
            ],
        }

    def process_ie_result(self, entry, download=True):
        assert download is True
        return {"ext": "mp4", "id": entry.get("id")}

    def prepare_filename(self, info):
        template = self.opts["outtmpl"]
        ext = info.get("ext", "mp4")
        path = template.replace("%(ext)s", ext)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"video")
        return path


class FakeSingleImageYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=False):
        if download:
            raise AssertionError("extract_info should be inspection-only")
        return {
            "id": "IMGONLY1",
            "title": "single image post",
            "display_url": "https://cdn.example/main.jpg",
            "thumbnails": [
                {"url": "https://cdn.example/thumb-small.jpg"},
                {"url": "https://cdn.example/thumb-large.jpg"},
            ],
        }


class FakeDownloadError(Exception):
    pass


class FakeFailingYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=False):
        raise FakeDownloadError("No video formats found!")


def test_instagram_carousel_downloads_images_and_videos(monkeypatch, tmp_path):
    out_dir = tmp_path / "out"
    metadata_dir = tmp_path / "meta"

    monkeypatch.setattr(ig, "load_app_config", lambda: {"raw_metadata_mode": "json"})
    monkeypatch.setattr(ig, "extract_vendor_id", lambda *_: "ABC123")
    monkeypatch.setattr(ig.yt_dlp, "YoutubeDL", FakeYDL)

    def fake_image(url, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"img")
        return path

    monkeypatch.setattr(ig, "download_image", fake_image)

    record = ig.download(
        "https://www.instagram.com/p/ABC123/",
        str(out_dir),
        str(metadata_dir),
        {},
        cookie_path="",
        video_download={"format": "best"},
    )

    data = json.loads(Path(record["metadata_path"]).read_text(encoding="utf-8"))

    assert [item["index"] for item in data["items"]] == [1, 2, 4]
    assert [item["type"] for item in data["items"]] == ["image", "video", "image"]
    assert data["items"][0]["filename"].startswith("001")
    assert data["items"][1]["filename"].startswith("002")
    assert data["items"][2]["filename"].startswith("004")
    assert "manifest" in data
    assert record["to_process"].endswith("001.jpg")


def test_instagram_single_image_uses_display_url(monkeypatch, tmp_path):
    out_dir = tmp_path / "out"
    metadata_dir = tmp_path / "meta"

    monkeypatch.setattr(ig, "load_app_config", lambda: {"raw_metadata_mode": "json"})
    monkeypatch.setattr(ig, "extract_vendor_id", lambda *_: "IMGONLY1")
    monkeypatch.setattr(ig.yt_dlp, "YoutubeDL", FakeSingleImageYDL)

    downloaded = {}

    def fake_image(url, path):
        downloaded["url"] = url
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"img")
        return path

    monkeypatch.setattr(ig, "download_image", fake_image)

    record = ig.download(
        "https://www.instagram.com/p/IMGONLY1/",
        str(out_dir),
        str(metadata_dir),
        {},
        cookie_path="",
        video_download={"format": "best"},
    )

    data = json.loads(Path(record["metadata_path"]).read_text(encoding="utf-8"))
    assert downloaded["url"] == "https://cdn.example/main.jpg"
    assert len(data["items"]) == 1
    assert data["items"][0]["type"] == "image"
    assert "manifest" not in data
    assert record["to_process"].endswith(".jpg")


def test_instagram_html_fallback_on_no_video_formats(monkeypatch, tmp_path):
    out_dir = tmp_path / "out"
    metadata_dir = tmp_path / "meta"

    monkeypatch.setattr(ig, "load_app_config", lambda: {"raw_metadata_mode": "json"})
    monkeypatch.setattr(ig, "extract_vendor_id", lambda *_: "DW9hy3kidPl")
    monkeypatch.setattr(ig.yt_dlp, "YoutubeDL", FakeFailingYDL)
    monkeypatch.setattr(
        ig.yt_dlp,
        "utils",
        types.SimpleNamespace(DownloadError=FakeDownloadError),
        raising=False,
    )

    html = """
    <html>
      <head>
        <meta property="og:image" content="https://cdn.example/og-image.jpg" />
        <meta property="og:title" content="OG Caption" />
      </head>
      <body>
        <script type="application/json">
          {"owner":{"username":"fallback_user"}}
        </script>
      </body>
    </html>
    """

    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, cookies=None, timeout=20):
            return FakeResponse(html)

    monkeypatch.setattr(ig.requests, "Session", FakeSession)

    downloaded = {}

    def fake_image(url, path):
        downloaded["url"] = url
        downloaded["path"] = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"img")
        return path

    monkeypatch.setattr(ig, "download_image", fake_image)

    record = ig.download(
        "https://www.instagram.com/p/DW9hy3kidPl/",
        str(out_dir),
        str(metadata_dir),
        {},
        cookie_path="",
        video_download={"format": "best"},
    )

    data = json.loads(Path(record["metadata_path"]).read_text(encoding="utf-8"))
    assert downloaded["url"] == "https://cdn.example/og-image.jpg"
    assert record["to_process"].endswith("instagram__DW9hy3kidPl.jpg")
    assert data["media_type"] == "image"
    assert data["uploader"] == "fallback_user"
    assert "manifest" not in data


def test_extract_image_candidates_from_html_uses_multiple_sources():
    html = """
    <meta property="og:image" content="https://cdn.example/og.jpg" />
    <script>
      {"display_url":"https:\\/\\/cdn.example\\/display.jpg","thumbnail_src":"https:\\/\\/cdn.example\\/thumb.jpg","image_versions2":{"candidates":[{"url":"https:\\/\\/cdn.example\\/hi.jpg","width":1080,"height":1920}]}}
    </script>
    """

    candidates = ig.extract_image_candidates_from_html(html)
    urls = {item["url"] for item in candidates}
    assert "https://cdn.example/og.jpg" in urls
    assert "https://cdn.example/display.jpg" in urls
    assert "https://cdn.example/thumb.jpg" in urls
    assert "https://cdn.example/hi.jpg" in urls
