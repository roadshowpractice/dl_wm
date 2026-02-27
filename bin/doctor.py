#!/usr/bin/env python
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent


def resolve_repo_path(path_value: str) -> str:
    if not path_value:
        return path_value
    if os.path.isabs(path_value):
        return path_value
    return str((repo_root / path_value).resolve())



def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return expand_paths(json.load(f)), None
    except Exception as exc:
        return None, str(exc)


def expand_paths(obj):
    if isinstance(obj, dict):
        return {k: expand_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_paths(item) for item in obj]
    if isinstance(obj, str):
        return os.path.expandvars(os.path.expanduser(obj))
    return obj


def check_imports():
    packages = [
        ("numpy", "numpy"),
        ("moviepy", "moviepy"),
        ("cv2", "opencv-python"),
        ("yt_dlp", "yt-dlp"),
        ("requests", "requests"),
        ("setuptools", "setuptools"),
        ("PIL", "Pillow"),
        ("imageio", "imageio"),
        ("imageio_ffmpeg", "imageio-ffmpeg"),
        ("decorator", "decorator"),
        ("tqdm", "tqdm"),
        ("proglog", "proglog"),
        ("dotenv", "python-dotenv"),
    ]
    ok = True
    for module_name, package_name in packages:
        try:
            importlib.import_module(module_name)
            print(f"[OK] import {module_name}")
        except Exception as exc:
            ok = False
            print(f"[ERR] import {module_name} failed ({package_name}): {exc}")
    return ok


def check_dir(label: str, path_value: str):
    try:
        os.makedirs(path_value, exist_ok=True)
        writable = os.access(path_value, os.W_OK)
        if writable:
            print(f"[OK] {label}: {path_value} exists and is writable")
            return True
        print(f"[ERR] {label}: {path_value} exists but is not writable")
        return False
    except Exception as exc:
        print(f"[ERR] {label}: failed to create/check {path_value}: {exc}")
        return False


def check_ffmpeg():
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        print("[ERR] ffmpeg not found on PATH")
        return False

    try:
        result = subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[OK] ffmpeg available: {ffmpeg_bin}")
            return True
        print(f"[ERR] ffmpeg returned non-zero exit code: {result.returncode}")
        return False
    except Exception as exc:
        print(f"[ERR] unable to execute ffmpeg: {exc}")
        return False


def resolve_output_dir(config):
    return config.get("output_dir") or config.get("target_usb")


def check_existing_file(label: str, path_value: str):
    if path_value and os.path.isfile(path_value):
        print(f"[OK] {label}: {path_value}")
        return True
    print(f"[WARN] {label} missing: {path_value}")
    return True


def check_parent_dir(label: str, file_path: str):
    parent_dir = os.path.dirname(file_path) if file_path else ""
    if parent_dir and os.path.isdir(parent_dir):
        print(f"[OK] {label} parent: {parent_dir}")
        return True
    print(f"[WARN] {label} parent missing: {parent_dir or '[none]'}")
    return True


def validate_optional_fonts(app_config: dict):
    font_checks = []
    watermark_font = app_config.get("watermark_config", {}).get("font")
    if watermark_font:
        font_checks.append(("watermark_config.font", watermark_font))

    subtitle_fonts_dir = app_config.get("subtitle_burn", {}).get("fonts_dir")
    if subtitle_fonts_dir:
        font_checks.append(("subtitle_burn.fonts_dir", subtitle_fonts_dir))

    for label, configured_path in font_checks:
        resolved_path = resolve_repo_path(configured_path)
        if os.path.exists(resolved_path):
            print(f"[OK] {label}: {resolved_path}")
        else:
            print(f"[WARN] {label} missing: {resolved_path}")


def main():
    app_config_path = repo_root / "conf" / "app_config.json"
    config_path = repo_root / "conf" / "config.json"

    app_config, app_error = load_json(app_config_path)
    platform_config_map, platform_error = load_json(config_path)

    status = True

    if app_error:
        print(f"[ERR] malformed app config {app_config_path}: {app_error}")
        return 1
    print(f"[OK] loaded app config: {app_config_path}")

    if platform_error:
        print(f"[ERR] malformed platform config {config_path}: {platform_error}")
        return 1
    print(f"[OK] loaded platform config: {config_path}")

    platform_name = "Darwin" if sys.platform == "darwin" else "Linux"
    platform_config = platform_config_map.get(platform_name)
    if not platform_config:
        print(f"[ERR] missing platform section '{platform_name}' in {config_path}")
        return 1

    output_dir = resolve_output_dir(platform_config)
    metadata_dir = app_config.get("metadata_dir")
    python_path = platform_config.get("python_path")
    log_filename = platform_config.get("logging", {}).get("log_filename")

    if output_dir:
        output_dir = resolve_repo_path(output_dir)
    if metadata_dir:
        metadata_dir = resolve_repo_path(metadata_dir)
    if log_filename:
        log_filename = resolve_repo_path(log_filename)

    if not output_dir:
        print("[ERR] output_dir missing in conf/config.json (target_usb fallback also empty)")
        status = False
    else:
        status = check_dir("output_dir", output_dir) and status

    if not metadata_dir:
        print("[ERR] metadata_dir missing in conf/app_config.json")
        status = False
    else:
        status = check_dir("metadata_dir", metadata_dir) and status

    if python_path:
        status = check_existing_file("python_path", python_path) and status
    else:
        print("[WARN] python_path not set in conf/config.json")

    if log_filename:
        status = check_parent_dir("log_filename", log_filename) and status
    else:
        print("[WARN] logging.log_filename not set in conf/config.json")

    validate_optional_fonts(app_config)

    status = check_imports() and status
    status = check_ffmpeg() and status

    print("[OK] doctor completed" if status else "[ERR] doctor found issues")
    return 0 if status else 2


if __name__ == "__main__":
    raise SystemExit(main())
