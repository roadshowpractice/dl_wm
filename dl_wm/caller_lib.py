"""
caller_lib.py — shared entry-point machinery for bin/call_*.py scripts.

Usage:
    from caller_lib import caller_main

    def run(input_path, logger):
        # do work, return output path or raise on failure
        ...
        return output_path

    if __name__ == "__main__":
        raise SystemExit(caller_main("task_name", run))

caller_main handles:
  - argv[1] presence and file-existence check
  - logging initialisation
  - task metadata update via update_task_for_media
  - printing the output path to stdout
  - returning 0 on success, 1 on failure
"""

import logging
import os
import sys

from dl_wm.teton_utils import initialize_logging
from dl_wm.transcription_caller import update_task_for_media

logger = logging.getLogger(__name__)


def caller_main(task_name: str, run_fn) -> int:
    """
    Standard entry point for a single-input caller script.

    task_name  — key written to the media's metadata default_tasks dict
    run_fn     — callable(input_path: str, logger) -> output_path: str
                 Should raise on failure rather than returning None/falsy.
    """
    log = initialize_logging()

    if len(sys.argv) < 2:
        log.error("Usage: %s <input_file>", os.path.basename(sys.argv[0]))
        return 1

    input_path = sys.argv[1]
    if not os.path.isfile(input_path):
        log.error("Input file does not exist: %s", input_path)
        return 1

    try:
        output_path = run_fn(input_path, log)
    except Exception as exc:
        log.error("%s failed: %s", task_name, exc)
        return 1

    if not output_path:
        log.error("%s returned no output path", task_name)
        return 1

    update_task_for_media(input_path, task_name, output_path)
    log.info("Output: %s", output_path)
    print(output_path)
    return 0
