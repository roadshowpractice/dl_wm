import importlib.util
import pathlib
import sys
import types


def _load_call_download_module():
    teton_utils = types.ModuleType("teton_utils")
    teton_utils.load_config = lambda: {}
    teton_utils.load_app_config = lambda: {}
    teton_utils.initialize_logging_from_config = lambda *_args, **_kwargs: None
    teton_utils.resolve_repo_path = lambda p: p
    sys.modules["teton_utils"] = teton_utils

    vendor_router = types.ModuleType("vendor_router")
    vendor_router.detect_vendor = lambda *_args, **_kwargs: "instagram"
    vendor_router.VENDOR_FACEBOOK = "facebook"
    vendor_router.VENDOR_INSTAGRAM = "instagram"
    vendor_router.VENDOR_YOUTUBE = "youtube"
    vendor_router.extract_vendor_id = lambda *_args, **_kwargs: "DXaslzKDRiD"
    vendor_router.metadata_filename = lambda *_args, **_kwargs: "instagram__DXaslzKDRiD.json"
    vendor_router.canonicalize_vendor_url = lambda _vendor, url: url
    sys.modules["vendor_router"] = vendor_router

    dl_pkg = types.ModuleType("downloaders")
    dl_pkg.__path__ = []
    sys.modules.setdefault("downloaders", dl_pkg)

    ig = types.ModuleType("downloaders.instagram")
    ig.download = lambda *_args, **_kwargs: {}
    sys.modules["downloaders.instagram"] = ig

    yt = types.ModuleType("downloaders.youtube")
    yt.download = lambda *_args, **_kwargs: {}
    sys.modules["downloaders.youtube"] = yt

    fb = types.ModuleType("downloaders.facebook")
    fb.download = lambda *_args, **_kwargs: {}
    sys.modules["downloaders.facebook"] = fb

    module_path = pathlib.Path(__file__).resolve().parents[1] / "bin" / "call_download.py"
    spec = importlib.util.spec_from_file_location("call_download_run_dir_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


call_download = _load_call_download_module()


def test_build_run_name_and_slug():
    assert call_download.safe_slug("Eduardo Post!! 2026") == "eduardo_post_2026"
    assert call_download.build_run_name("instagram", "DXaslzKDRiD") == "instagram__DXaslzKDRiD"
    assert (
        call_download.build_run_name("instagram", "DXaslzKDRiD", "Eduardo Post!! 2026")
        == "instagram__DXaslzKDRiD__eduardo_post_2026"
    )


def test_main_uses_per_download_run_directory(monkeypatch, tmp_path):
    output_root = tmp_path / "outputs"
    metadata_root = tmp_path / "metadata"

    class _Logger:
        def info(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(call_download, "load_config", lambda: {"output_dir": str(output_root)})
    monkeypatch.setattr(call_download, "load_app_config", lambda: {"metadata_dir": str(metadata_root)})
    monkeypatch.setattr(call_download, "initialize_logging_from_config", lambda *_args, **_kwargs: _Logger())
    monkeypatch.setattr(call_download, "resolve_repo_path", lambda p: p)
    monkeypatch.setattr(call_download, "resolve_cookie_paths", lambda *_args, **_kwargs: ["/tmp/cookie.txt"])
    monkeypatch.setattr(call_download, "upsert_index_record", lambda *_args, **_kwargs: None)

    captured = {}

    def _fake_download(url, output_dir, metadata_dir, registry_record, cookie_path, video_download_cfg):
        captured["output_dir"] = output_dir
        file_path = pathlib.Path(output_dir) / "instagram__DXaslzKDRiD.mp4"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("video")
        return {
            "vendor": "instagram",
            "vendor_id": "DXaslzKDRiD",
            "metadata_file": "instagram__DXaslzKDRiD.json",
            "original_filename": str(file_path),
        }

    monkeypatch.setattr(call_download, "download_instagram", _fake_download)
    monkeypatch.setattr(call_download.sys, "argv", ["call_download.py", "https://www.instagram.com/p/DXaslzKDRiD/"])

    returned = call_download.main()
    expected_run_dir = pathlib.Path(captured["output_dir"])

    assert returned.endswith("instagram__DXaslzKDRiD.mp4")
    assert expected_run_dir.parent.parent == output_root
    assert expected_run_dir.name == "instagram__DXaslzKDRiD"
    assert expected_run_dir.exists()
