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

    vendor_router = types.ModuleType("vendor_router")
    vendor_router.detect_vendor = lambda *_args, **_kwargs: "instagram"
    vendor_router.VENDOR_FACEBOOK = "facebook"
    vendor_router.VENDOR_INSTAGRAM = "instagram"
    vendor_router.VENDOR_YOUTUBE = "youtube"
    vendor_router.extract_vendor_id = lambda *_args, **_kwargs: "id"
    vendor_router.metadata_filename = lambda *_args, **_kwargs: "id.json"
    vendor_router.canonicalize_vendor_url = lambda _vendor, url: url

    dl_pkg = types.ModuleType("downloaders")
    dl_pkg.__path__ = []

    ig = types.ModuleType("downloaders.instagram")
    ig.download = lambda *_args, **_kwargs: {}

    yt = types.ModuleType("downloaders.youtube")
    yt.download = lambda *_args, **_kwargs: {}

    fb = types.ModuleType("downloaders.facebook")
    fb.download = lambda *_args, **_kwargs: {}

    stubs = {
        "teton_utils": teton_utils,
        "vendor_router": vendor_router,
        "downloaders": dl_pkg,
        "downloaders.instagram": ig,
        "downloaders.youtube": yt,
        "downloaders.facebook": fb,
    }

    # Stash whatever (if anything) real modules already occupy these names so
    # they can be restored after exec_module runs — otherwise these stubs
    # leak into sys.modules for the rest of the pytest session and break
    # any other test file that needs the real module.
    previous = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        module_path = pathlib.Path(__file__).resolve().parents[1] / "bin" / "call_download.py"
        spec = importlib.util.spec_from_file_location("call_download_module", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
    finally:
        for name, mod in previous.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
    return module


call_download = _load_call_download_module()


def test_cookie_block_error_detection_matches_common_markers():
    assert call_download.is_cookie_identity_blocked_error(RuntimeError("HTTP Error 429: Too Many Requests"))
    assert call_download.is_cookie_identity_blocked_error(RuntimeError("login required to view this content"))
    assert call_download.is_cookie_identity_blocked_error(RuntimeError("Instagram sent an empty media response"))
    assert not call_download.is_cookie_identity_blocked_error(RuntimeError("network unavailable"))


def test_resolve_cookie_paths_prefers_hierarchy_then_discovers_conf_files(tmp_path, monkeypatch):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir(parents=True)
    first = conf_dir / "instagram.cookies.txt"
    second = conf_dir / "instagram.cookies.2.txt"
    discovered = conf_dir / "insta.justin.txt"
    for p in (first, second, discovered):
        p.write_text("cookie")

    def fake_resolve_repo_path(path):
        if path == "conf":
            return str(conf_dir)
        return str(tmp_path / path)

    monkeypatch.setattr(call_download, "resolve_repo_path", fake_resolve_repo_path)
    monkeypatch.setattr(call_download, "root_dir", str(tmp_path))

    video_download_cfg = {
        "cookie_hierarchy": {
            "instagram": [
                "conf/instagram.cookies.txt",
                "conf/instagram.cookies.2.txt",
            ]
        }
    }

    resolved = call_download.resolve_cookie_paths({}, video_download_cfg, "instagram")

    assert resolved[0] == str(first)
    assert resolved[1] == str(second)
    assert str(discovered) in resolved


def test_resolve_cookie_paths_uses_vendor_specific_facebook_cookie_path(tmp_path, monkeypatch):
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir(parents=True)
    fb_cookie = conf_dir / "facebook.cookies.txt"
    fb_cookie.write_text("cookie")

    def fake_resolve_repo_path(path):
        if path == "conf":
            return str(conf_dir)
        return str(tmp_path / path)

    monkeypatch.setattr(call_download, "resolve_repo_path", fake_resolve_repo_path)
    monkeypatch.setattr(call_download, "root_dir", str(tmp_path))

    resolved = call_download.resolve_cookie_paths(
        {},
        {"facebook_cookie_path": "conf/facebook.cookies.txt"},
        "facebook",
    )

    assert resolved[0] == str(fb_cookie)
