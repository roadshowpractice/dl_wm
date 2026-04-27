import importlib.util
import pathlib
import sys
import types


def _load_call_router_module():
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
    spec.loader.exec_module(module)
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
