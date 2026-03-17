import logging
import os
import shlex
import subprocess
import sys
import json
from importlib import import_module
from typing import Optional

from tasks_lib import update_task_output_path
from teton_utils import load_app_config

logger = logging.getLogger(__name__)


def _optional_int(value) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_command(template: str, input_path: str, output_path: str, output_format: str) -> list[str]:
    formatted = template.format(
        input=shlex.quote(input_path),
        output=shlex.quote(output_path),
        format=shlex.quote(output_format),
    )
    return shlex.split(formatted)


def _run_and_validate(cmd: list[str], output_path: str) -> bool:
    logger.warning("Running transcription command: %s", " ".join(cmd))
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        if result.returncode < 0:
            logger.error(
                "Transcription command was terminated by signal %s.",
                abs(result.returncode),
            )
            if abs(result.returncode) == 9:
                logger.error(
                    "Signal 9 usually indicates the OS killed the process (often out-of-memory). "
                    "Try a shorter clip, a smaller Whisper model, or disable extract_audio/generate_srt for this run."
                )
        else:
            logger.error("Transcription command failed with exit code %s", result.returncode)
        return False

    if not os.path.exists(output_path):
        logger.error("Transcription command completed but output was not created: %s", output_path)
        return False

    return True


def _ensure_no_legacy_flags(cmd: list[str]) -> None:
    if "--input" in cmd or "--output" in cmd:
        raise RuntimeError(
            "transcribe_media.py does not support --input/--output; "
            "use positional INPUT_MEDIA_PATH + --outdir"
        )


def _python_executable(app_config: dict) -> str:
    return (
        app_config.get("transcription", {}).get("python_path")
        or app_config.get("python_path")
        or sys.executable
    )


def _build_transcribe_media_command(
    python_bin: str,
    script_path: str,
    input_path: str,
    output_path: str,
    output_format: str,
    app_config: dict,
) -> tuple[list[str], str]:
    outdir = os.path.dirname(output_path) or "."
    stem = os.path.splitext(os.path.basename(input_path))[0]
    generated_output_path = os.path.join(outdir, f"{stem}.{output_format}")

    cmd = [python_bin, script_path, input_path, "--outdir", outdir]

    tx_cfg = app_config.get("transcription", {}) if isinstance(app_config, dict) else {}
    chunk_seconds = _optional_int(tx_cfg.get("chunk_seconds"))
    if chunk_seconds is not None and chunk_seconds >= 0:
        cmd.extend(["--chunk-seconds", str(chunk_seconds)])

    if output_format == "srt":
        cmd.extend(["--srt", "--no-txt"])
    elif output_format == "txt":
        cmd.append("--txt")
    elif output_format:
        cmd.append(f"--{output_format}")

    _ensure_no_legacy_flags(cmd)
    return cmd, generated_output_path


def _auto_transcribe_with_local_script(
    input_path: str,
    output_path: str,
    output_format: str,
    app_config: dict,
) -> bool:
    """Fallback: use bin/transcribe_media.py with canonical argument shape."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    script_path = os.path.join(repo_root, "bin", "transcribe_media.py")
    if not os.path.isfile(script_path):
        return False

    py = _python_executable(app_config)
    cmd, generated_output_path = _build_transcribe_media_command(
        py,
        script_path,
        input_path,
        output_path,
        output_format,
        app_config,
    )

    if not _run_and_validate(cmd, generated_output_path):
        return False

    if os.path.abspath(generated_output_path) != os.path.abspath(output_path):
        logger.warning(
            "Transcription output written to canonical path %s (requested path was %s)",
            generated_output_path,
            output_path,
        )

    return True


def run_transcription(input_path: str, output_path: str, output_format: str) -> bool:
    """Run configured transcription caller, returning True on success."""
    app_config = load_app_config()
    tx_cfg = app_config.get("transcription", {})

    command_template = tx_cfg.get("caller_command")
    if command_template:
        cmd = _format_command(command_template, input_path, output_path, output_format)
        return _run_and_validate(cmd, output_path)

    module_name = tx_cfg.get("caller_module")
    function_name = tx_cfg.get("caller_function", "transcribe")
    if module_name:
        try:
            module = import_module(module_name)
            func = getattr(module, function_name)
            response = func(input_path=input_path, output_path=output_path, output_format=output_format)
            return bool(response) and os.path.exists(output_path)
        except Exception as exc:
            logger.error("Configured transcription module call failed: %s", exc)
            return False

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    local_script_path = os.path.join(repo_root, "bin", "transcribe_media.py")
    local_script_exists = os.path.isfile(local_script_path)

    if local_script_exists:
        if _auto_transcribe_with_local_script(input_path, output_path, output_format, app_config):
            return True

        logger.error(
            "Automatic transcription via %s failed. "
            "Set transcription.caller_command/caller_module in conf/app_config.json to use a custom caller.",
            local_script_path,
        )
        return False

    logger.error(
        "No transcription caller configured. Set transcription.caller_command or transcription.caller_module in conf/app_config.json, "
        "or place bin/transcribe_media.py in this repo."
    )
    return False


def sidecar_metadata_path(media_path: str) -> str:
    base, _ = os.path.splitext(media_path)
    return f"{base}.json"


def _paths_match(path_a: str, path_b: str) -> bool:
    """Return True when two paths refer to the same file path string."""
    if not path_a or not path_b:
        return False

    norm_a = os.path.abspath(os.path.normpath(path_a))
    norm_b = os.path.abspath(os.path.normpath(path_b))
    if norm_a == norm_b:
        return True

    # Fall back to basename match because metadata can be moved between hosts.
    return os.path.basename(norm_a) == os.path.basename(norm_b)


def _metadata_path_for_media(media_path: str) -> Optional[str]:
    """Find the best metadata json for a media file path."""
    sidecar_path = sidecar_metadata_path(media_path)
    if os.path.isfile(sidecar_path):
        try:
            with open(sidecar_path, "r", encoding="utf-8") as f:
                sidecar_metadata = json.load(f)
            if isinstance(sidecar_metadata.get("default_tasks"), dict):
                return sidecar_path
        except (OSError, json.JSONDecodeError):
            pass

    app_config = load_app_config()
    metadata_dir = app_config.get("metadata_dir", "./metadata")
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if not os.path.isabs(metadata_dir):
        metadata_dir = os.path.join(repo_root, metadata_dir)

    if not os.path.isdir(metadata_dir):
        return None

    for filename in sorted(os.listdir(metadata_dir)):
        if not filename.endswith(".json"):
            continue

        metadata_path = os.path.join(metadata_dir, filename)
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        task_state = metadata.get("default_tasks", {})
        if not isinstance(task_state, dict):
            continue

        download_path = task_state.get("perform_download")
        if isinstance(download_path, str) and _paths_match(download_path, media_path):
            return metadata_path

        watermark_path = task_state.get("apply_watermark")
        if isinstance(watermark_path, str) and _paths_match(watermark_path, media_path):
            return metadata_path

        file_path = metadata.get("file_path")
        if isinstance(file_path, str) and _paths_match(file_path, media_path):
            return metadata_path

    if os.path.isfile(sidecar_path):
        return sidecar_path

    return None


def update_task_for_media(media_path: str, task_name: str, output_path: str) -> Optional[str]:
    metadata_path = _metadata_path_for_media(media_path)
    if not metadata_path:
        logger.warning("Could not update task '%s'; metadata not found for media: %s", task_name, media_path)
        return None

    result = update_task_output_path(metadata_path, task_name, output_path)
    return result.get("updated_metadata") if isinstance(result, dict) else None
