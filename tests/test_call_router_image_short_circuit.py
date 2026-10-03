import json
import importlib.util
import pathlib
import sys
import types


def _load_call_router_module():
    # These stubs would otherwise leak into sys.modules for the rest of the
    # test session, shadowing the real modules for later test files.
    stub_names = ("teton_utils", "tasks_lib", "vendor_router")
    previous_modules = {name: sys.modules.get(name) for name in stub_names}

    teton_utils = types.ModuleType("teton_utils")
    teton_utils.load_config = lambda: {}
    teton_utils.load_app_config = lambda: {"metadata_dir": "./metadata"}
    teton_utils.resolve_repo_path = lambda p: p
    teton_utils.initialize_logging = lambda: types.SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    sys.modules["teton_utils"] = teton_utils

    tasks_lib = types.ModuleType("tasks_lib")
    tasks_lib.find_url_json = lambda *_args, **_kwargs: (None, None)
    sys.modules["tasks_lib"] = tasks_lib

    vendor_router = types.ModuleType("vendor_router")
    vendor_router.detect_vendor = lambda *_args, **_kwargs: "instagram"
    vendor_router.canonicalize_vendor_url = lambda _vendor, url: url
    sys.modules["vendor_router"] = vendor_router

    module_path = pathlib.Path(__file__).resolve().parents[1] / "bin" / "call_router.py"
    spec = importlib.util.spec_from_file_location("call_router_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


call_router = _load_call_router_module()


def test_image_media_short_circuits_pipeline(monkeypatch, capsys):
    metadata = {
        "url": "https://www.instagram.com/p/DW9hy3kidPl/",
        "media_type": "image",
        "default_tasks": {"perform_download": "/tmp/downloaded_image.jpg"},
    }

    monkeypatch.setattr(
        call_router,
        "find_url_json",
        lambda *_args, **_kwargs: ("metadata/file.json", metadata),
    )
    monkeypatch.setattr(call_router, "wait_for_download_file", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        call_router,
        "execute_tasks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("execute_tasks should not run for image media")
        ),
    )

    log_messages = []
    logger = types.SimpleNamespace(
        info=lambda message: log_messages.append(message),
        warning=lambda message: log_messages.append(message),
        error=lambda message: log_messages.append(message),
    )
    monkeypatch.setattr(call_router, "initialize_logging", lambda: logger)
    monkeypatch.setattr(call_router.sys, "argv", ["call_router.py", metadata["url"]])

    call_router.main()

    assert any(
        "Image media detected; download complete. Skipping video/audio pipeline." in message
        for message in log_messages
    )
    output = capsys.readouterr().out
    assert "Found in: metadata/file.json" in output


def test_carousel_followup_items_get_their_own_task_state(tmp_path):
    module = _load_call_router_module()
    first = tmp_path / "post__01.mp4"
    second = tmp_path / "post__02.mp4"
    found_data = {
        "uploader": "someone",
        "items": [
            {"index": 1, "type": "video", "filename": "post__01.mp4"},
            {"index": 2, "type": "video", "filename": "post__02.mp4"},
            {"index": 3, "type": "image", "filename": "post__03.jpg"},
        ],
        "default_tasks": {
            "perform_download": str(first),
            "apply_watermark": str(tmp_path / "post__01_watermarked.mp4"),
            "extract_audio": True,
            "burn_srt": False,
        },
    }

    assert module.carousel_followup_items(found_data, str(first)) == [str(second)]

    tasks = module.item_task_state(found_data, str(second))
    assert tasks == {"perform_download": str(second), "apply_watermark": True, "extract_audio": True, "burn_srt": False}
    sidecar = tmp_path / "post__02.json"
    data = json.loads(sidecar.read_text())
    assert data["uploader"] == "someone" and "items" not in data

    # a second run resumes from the sidecar instead of resetting it
    data["default_tasks"]["apply_watermark"] = "done.mp4"
    sidecar.write_text(json.dumps(data))
    assert module.item_task_state(found_data, str(second))["apply_watermark"] == "done.mp4"


def test_single_item_post_has_no_followups(tmp_path):
    module = _load_call_router_module()
    assert module.carousel_followup_items({"items": [{"type": "video", "filename": "a.mp4"}]}, str(tmp_path / "a.mp4")) == []


def test_mixed_carousel_starting_with_image_runs_video_items(monkeypatch, tmp_path):
    image = tmp_path / "post__01.jpg"
    video = tmp_path / "post__02.mp4"
    image.write_bytes(b"i")
    video.write_bytes(b"v")
    metadata = {
        "url": "https://www.instagram.com/p/MIXED/",
        "media_type": "carousel",
        "items": [
            {"index": 1, "type": "image", "filename": image.name},
            {"index": 2, "type": "video", "filename": video.name},
        ],
        "default_tasks": {"perform_download": str(image), "apply_watermark": True},
    }
    monkeypatch.setattr(call_router, "find_url_json", lambda *_a, **_k: ("metadata/file.json", metadata))
    monkeypatch.setattr(call_router, "wait_for_download_file", lambda *_a, **_k: True)
    ran = []
    monkeypatch.setattr(call_router, "execute_tasks", lambda tasks, url, path, dry_run=False: ran.append(path))
    noop = lambda *_a, **_k: None
    monkeypatch.setattr(call_router, "initialize_logging", lambda: types.SimpleNamespace(info=noop, warning=noop, error=noop))
    monkeypatch.setattr(call_router.sys, "argv", ["call_router.py", metadata["url"]])

    call_router.main()

    assert ran == [str(video)]
    assert (tmp_path / "post__02.json").exists()
