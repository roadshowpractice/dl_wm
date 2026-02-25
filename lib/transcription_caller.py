import logging
import os
import shlex
import subprocess
import sys
from importlib import import_module
from typing import Optional

from tasks_lib import update_task_output_path
from teton_utils import load_app_config

logger = logging.getLogger(__name__)


def _format_command(template: str, input_path: str, output_path: str, output_format: str) -> list[str]:
    formatted = template.format(
        input=shlex.quote(input_path),
        output=shlex.quote(output_path),
        format=shlex.quote(output_format),
    )
    return shlex.split(formatted)


def _run_and_validate(cmd: list[str], output_path: str) -> bool:
    logger.info("Running transcription command: %s", " ".join(cmd))
    result = subprocess.run(cmd)
    return result.returncode == 0 and os.path.exists(output_path)


def _python_executable(app_config: dict) -> str:
    return (
        app_config.get("transcription", {}).get("python_path")
        or app_config.get("python_path")
        or sys.executable
    )


def _help_text(script_path: str, python_bin: str) -> str:
    try:
        result = subprocess.run(
            [python_bin, script_path, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return f"{result.stdout}\n{result.stderr}".lower()
    except Exception:
        return ""


def _auto_transcribe_with_local_script(
    input_path: str,
    output_path: str,
    output_format: str,
    app_config: dict,
) -> bool:
    """Fallback: use bin/transcribe_media.py with inferred argument shape."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    script_path = os.path.join(repo_root, "bin", "transcribe_media.py")
    if not os.path.isfile(script_path):
        return False

    py = _python_executable(app_config)
    help_blob = _help_text(script_path, py)
    cmd_candidates = []

    has_input = "--input" in help_blob
    has_output = "--output" in help_blob
    has_format = "--format" in help_blob

    if has_input and has_output and has_format:
        cmd_candidates.append(
            [py, script_path, "--input", input_path, "--output", output_path, "--format", output_format]
        )
    if has_input and has_output:
        cmd_candidates.append([py, script_path, "--input", input_path, "--output", output_path])
    if "--srt" in help_blob and output_format == "srt":
        cmd_candidates.append([py, script_path, "--input", input_path, "--output", output_path, "--srt"])
    if "--txt" in help_blob and output_format == "txt":
        cmd_candidates.append([py, script_path, "--input", input_path, "--output", output_path, "--txt"])

    # Generic fallbacks for common script signatures.
    cmd_candidates.extend(
        [
            [py, script_path, input_path, "--output", output_path, "--format", output_format],
            [py, script_path, input_path, "--output", output_path],
            [py, script_path, input_path, output_path, output_format],
            [py, script_path, input_path, output_path],
        ]
    )

    for cmd in cmd_candidates:
        if _run_and_validate(cmd, output_path):
            return True

    return False


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

    if _auto_transcribe_with_local_script(input_path, output_path, output_format, app_config):
        return True

    logger.error(
        "No transcription caller configured. Set transcription.caller_command or transcription.caller_module in conf/app_config.json, "
        "or place bin/transcribe_media.py in this repo."
    )
    return False


def sidecar_metadata_path(media_path: str) -> str:
    base, _ = os.path.splitext(media_path)
    return f"{base}.json"


def update_task_for_media(media_path: str, task_name: str, output_path: str) -> Optional[str]:
    metadata_path = sidecar_metadata_path(media_path)
    if not os.path.isfile(metadata_path):
        logger.warning("Could not update task '%s'; metadata sidecar not found: %s", task_name, metadata_path)
        return None

    result = update_task_output_path(metadata_path, task_name, output_path)
    return result.get("updated_metadata") if isinstance(result, dict) else None
