#!/usr/bin/env python
import os
import subprocess
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from teton_utils import initialize_logging, load_app_config
from transcription_caller import _metadata_path_for_media, update_task_for_media


def _escape_sub_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized.replace(":", "\\:").replace("'", "\\'")


def _escape_filter_arg(value: str) -> str:
    normalized = str(value).replace("\\", "/")
    return normalized.replace(":", "\\:").replace("'", "\\'")


def _ass_force_style_from_config(app_config: dict) -> tuple[str, str]:
    burn_cfg = app_config.get("subtitle_burn", {}) if isinstance(app_config, dict) else {}
    presets = app_config.get("subtitle_style_presets", {}) if isinstance(app_config, dict) else {}

    fonts_dir = burn_cfg.get("fonts_dir", "") or ""
    direct_force_style = burn_cfg.get("force_style", "") or ""
    if direct_force_style:
        return str(fonts_dir), str(direct_force_style)

    preset_name = burn_cfg.get("style_preset", "") or ""
    style_dict = presets.get(preset_name, {}) if preset_name else {}
    if not isinstance(style_dict, dict) or not style_dict:
        return str(fonts_dir), ""

    style_parts = []
    for key, value in style_dict.items():
        if str(key).startswith("_"):
            continue
        style_parts.append(f"{key}={value}")
    return str(fonts_dir), ",".join(style_parts)


def _resolve_inputs(input_video: str, app_config: dict, logger) -> tuple[str, str]:
    burn_cfg = app_config.get("subtitle_burn", {})
    video_task = burn_cfg.get("video_task", "apply_watermark")
    srt_task = burn_cfg.get("srt_task", "generate_srt")

    metadata_path = _metadata_path_for_media(input_video)
    if not metadata_path:
        raise RuntimeError(f"No metadata found for: {input_video}")

    import json
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    default_tasks = metadata.get("default_tasks", {}) if isinstance(metadata, dict) else {}

    source_video = default_tasks.get(video_task) if isinstance(default_tasks.get(video_task), str) else input_video
    source_srt = default_tasks.get(srt_task) if isinstance(default_tasks.get(srt_task), str) else ""

    if not source_srt:
        base, _ = os.path.splitext(source_video)
        source_srt = f"{base}.srt"

    if not os.path.isfile(source_video):
        raise RuntimeError(f"Source video does not exist: {source_video}")
    if not os.path.isfile(source_srt):
        raise RuntimeError(f"SRT file does not exist: {source_srt}")

    logger.info("Subtitle burn source video: %s", source_video)
    logger.info("Subtitle burn source srt: %s", source_srt)
    return source_video, source_srt


def _burn_subtitles(video_path: str, srt_path: str, app_config: dict) -> str:
    burn_cfg = app_config.get("subtitle_burn", {})
    suffix = burn_cfg.get("output_suffix", ".burned")
    codec = burn_cfg.get("video_codec", "libx264")
    crf = str(burn_cfg.get("crf", 18))
    preset = burn_cfg.get("preset", "medium")

    base, ext = os.path.splitext(video_path)
    output_video = f"{base}{suffix}{ext}"

    fonts_dir, force_style = _ass_force_style_from_config(app_config)
    subtitle_filter = f"subtitles='{_escape_sub_path(srt_path)}'"
    if fonts_dir:
        fonts_abs = os.path.abspath(os.path.join(root_dir, fonts_dir))
        subtitle_filter += f":fontsdir='{_escape_sub_path(fonts_abs)}'"
    if force_style:
        subtitle_filter += f":force_style='{_escape_filter_arg(force_style)}'"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vf",
        subtitle_filter,
        "-c:v",
        codec,
        "-crf",
        crf,
        "-preset",
        preset,
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        output_video,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg subtitle burn failed")

    return output_video


def main() -> int:
    logger = initialize_logging()
    if len(sys.argv) < 2:
        logger.error("Usage: python bin/call_burn_srt.py <video_file_path>")
        return 1

    input_video = sys.argv[1]
    if not os.path.isfile(input_video):
        logger.error("Input video file does not exist: %s", input_video)
        return 1

    app_config = load_app_config()

    try:
        source_video, srt_path = _resolve_inputs(input_video, app_config, logger)
        output_video = _burn_subtitles(source_video, srt_path, app_config)
    except Exception as exc:
        logger.error("Failed to burn subtitles: %s", exc)
        return 1

    update_task_for_media(input_video, "burn_srt", output_video)
    logger.info("Burned subtitle video created: %s", output_video)
    print(output_video)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
