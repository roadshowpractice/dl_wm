import importlib.util
import pathlib
import sys
import types


def _load_call_download_module():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)

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

    cookies_path = pathlib.Path(__file__).resolve().parents[1] / "downloaders" / "cookies.py"
    cookies_spec = importlib.util.spec_from_file_location("downloaders.cookies", cookies_path)
    cookies_mod = importlib.util.module_from_spec(cookies_spec)
    cookies_spec.loader.exec_module(cookies_mod)
    sys.modules["downloaders.cookies"] = cookies_mod

    module_path = pathlib.Path(__file__).resolve().parents[1] / "bin" / "call_download.py"
    spec = importlib.util.spec_from_file_location("call_download_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


call_download = _load_call_download_module()


def test_cookie_block_error_detection_matches_common_markers():
    assert call_download.is_cookie_identity_blocked_error(RuntimeError("HTTP Error 429: Too Many Requests"))
    assert call_download.is_cookie_identity_blocked_error(RuntimeError("login required to view this content"))
    assert call_download.is_cookie_identity_blocked_error(RuntimeError("Instagram sent an empty media response"))
    assert not call_download.is_cookie_identity_blocked_error(RuntimeError("network unavailable"))


