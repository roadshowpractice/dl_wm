import logging
import os
import shlex
import subprocess
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


def run_transcription(input_path: str, output_path: str, output_format: str) -> bool:
    """Run configured transcription caller, returning True on success."""
    app_config = load_app_config()
    tx_cfg = app_config.get("transcription", {})

    command_template = tx_cfg.get("caller_command")
    if command_template:
        cmd = _format_command(command_template, input_path, output_path, output_format)
        logger.info("Running transcription command: %s", " ".join(cmd))
        result = subprocess.run(cmd)
        return result.returncode == 0 and os.path.exists(output_path)

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

    logger.error(
        "No transcription caller configured. Set transcription.caller_command or transcription.caller_module in conf/app_config.json"
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
