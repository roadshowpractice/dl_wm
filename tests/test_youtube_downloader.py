import importlib.util
import json
import pathlib
import subprocess
import sys
import types


def _load_youtube_module():
    lib_pkg = types.ModuleType("lib")
    lib_pkg.__path__ = []
    sys.modules.setdefault("lib", lib_pkg)

    metadata_compactor = types.ModuleType("lib.metadata_compactor")
    metadata_compactor.build_compact_metadata = lambda *args, **kwargs: {"ok": True}
    metadata_compactor.write_raw_metadata = lambda *args, **kwargs: None
    sys.modules["lib.metadata_compactor"] = metadata_compactor

    teton_utils = types.ModuleType("lib.teton_utils")
    teton_utils.load_app_config = lambda: {
        "youtube_download": {
            "strategies": [
                {
                    "name": "web_cookie_file",
                    "use_remote_components": True,
                    "cookies_mode": "file",
                    "format": "bestvideo+bestaudio/best",
                },
                {
                    "name": "android_fallback",
                    "use_remote_components": False,
                    "cookies_mode": "none",
                    "extractor_arg": "youtube:player_client=android",
                    "format": "best",
                },
            ],
            "browser_cookie_order": ["firefox"],
        }
    }
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
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


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


def test_contains_retryable_marker_detects_known_messages():
    assert youtube_module._contains_retryable_marker("", "Only images are available for download")
    assert youtube_module._contains_retryable_marker("n challenge solving failed", "")
    assert not youtube_module._contains_retryable_marker("ok", "different error")


def test_build_command_skips_remote_components_when_unsupported(monkeypatch):
    youtube_module._REMOTE_COMPONENTS_SUPPORTED = None

    def fake_run(cmd, capture_output, text, check):
        if cmd[:2] == ["yt-dlp", "--help"]:
            return _Result(stdout="yt-dlp options list without remote components", stderr="", returncode=0)
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    command = youtube_module._build_command(
        url="https://www.youtube.com/watch?v=abc123",
        output_template="/tmp/youtube__abc123.%(ext)s",
        fmt="best",
        strategy={"use_remote_components": True},
    )

    assert "--remote-components" not in command


def test_download_falls_through_to_android_strategy(monkeypatch, tmp_path):
    download_dir = tmp_path / "out"
    metadata_dir = tmp_path / "meta"
    video_file = download_dir / "youtube__abc123.mp4"

    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if cmd[:2] == ["yt-dlp", "--version"]:
            return _Result(stdout="2025.02.19\n")
        if "--extractor-args" in cmd:
            video_file.parent.mkdir(parents=True, exist_ok=True)
            video_file.write_text("x")
            payload = json.dumps({"id": "abc123", "ext": "mp4", "_filename": str(video_file)})
            return _Result(stdout=payload + "\n", stderr="", returncode=0)
        return _Result(
            stdout="",
            stderr="Only images are available for download",
            returncode=1,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(youtube_module, "_load_platform_config", lambda: {})

    result = youtube_module.download(
        "https://www.youtube.com/watch?v=abc123",
        str(download_dir),
        str(metadata_dir),
        registry_record={},
        cookie_path=None,
        video_download={"youtube_cookie_files": []},
    )

    assert result["success"] is True
    assert result["strategy"] == "android_fallback"
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["retryable"] is True
    assert any("--extractor-args" in c for c in calls)
