import importlib.util
import pathlib
import subprocess
import sys
import types


def _load_youtube_module():
    lib_pkg = types.ModuleType("lib")
    lib_pkg.__path__ = []
    sys.modules.setdefault("lib", lib_pkg)

    metadata_compactor = types.ModuleType("lib.metadata_compactor")
    metadata_compactor.build_compact_metadata = lambda *args, **kwargs: {}
    metadata_compactor.write_raw_metadata = lambda *args, **kwargs: None
    sys.modules["lib.metadata_compactor"] = metadata_compactor

    teton_utils = types.ModuleType("lib.teton_utils")
    teton_utils.load_app_config = lambda: {}
    sys.modules["lib.teton_utils"] = teton_utils

    vendor_router = types.ModuleType("lib.vendor_router")
    vendor_router.VENDOR_YOUTUBE = "youtube"
    vendor_router.extract_vendor_id = lambda *_args, **_kwargs: "abc123"
    vendor_router.metadata_filename = lambda *_args, **_kwargs: "dummy.json"
    sys.modules["lib.vendor_router"] = vendor_router

    module_path = pathlib.Path(__file__).resolve().parents[1] / "downloaders" / "youtube.py"
    spec = importlib.util.spec_from_file_location("youtube_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


youtube_module = _load_youtube_module()


class _Result:
    def __init__(self, stdout="{}"):
        self.stdout = stdout


def test_version_key_parses_standard_versions():
    assert youtube_module._version_key("2025.02.19") == (2025, 2, 19)
    assert youtube_module._version_key("2025.02.19.post1") == (2025, 2, 19)


def test_ensure_supported_yt_dlp_rejects_old_versions(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        return _Result(stdout="2023.07.06\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    try:
        youtube_module._ensure_supported_yt_dlp("2024.10.22")
    except RuntimeError as err:
        assert "too old" in str(err)
    else:
        raise AssertionError("Expected RuntimeError")


def test_ensure_supported_yt_dlp_accepts_newer_versions(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        return _Result(stdout="2025.02.19\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    youtube_module._ensure_supported_yt_dlp("2024.10.22")


def test_run_yt_dlp_falls_back_when_remote_components_unsupported(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(
                2,
                cmd,
                stderr="yt-dlp: error: no such option: --remote-components",
            )
        return _Result(stdout='{"id":"abc"}')

    monkeypatch.setattr(subprocess, "run", fake_run)

    cmd = ["yt-dlp", "--remote-components", "ejs:github", "--print-json", "https://example.com"]
    result = youtube_module._run_yt_dlp(cmd)

    assert result.stdout == '{"id":"abc"}'
    assert calls[1] == ["yt-dlp", "--print-json", "https://example.com"]


def test_run_yt_dlp_raises_for_other_errors(monkeypatch):
    def fake_run(cmd, capture_output, text, check):
        raise subprocess.CalledProcessError(1, cmd, stderr="network unavailable")

    monkeypatch.setattr(subprocess, "run", fake_run)

    cmd = ["yt-dlp", "--remote-components", "ejs:github", "--print-json", "https://example.com"]

    try:
        youtube_module._run_yt_dlp(cmd)
    except subprocess.CalledProcessError as err:
        assert err.returncode == 1
    else:
        raise AssertionError("Expected CalledProcessError")
