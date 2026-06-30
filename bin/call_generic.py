#!/usr/bin/env python
"""
call_generic.py — template for a thin caller script.

Copy this file, rename it call_<task>.py, then:
  1. Replace TASK_NAME with the key from default_tasks (e.g. "generate_srt")
  2. Implement the run() function — do the work, return the output path, raise on failure
  3. Delete this docstring
"""
import os
import sys

import pathlib
_root = str(pathlib.Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from dl_wm.caller_lib import caller_main

TASK_NAME = "your_task_name_here"


def run(input_path, logger):
    # Do the work.
    # Return the output file path on success.
    # Raise an exception on failure — caller_main will catch it and exit 1.
    output_path = input_path  # replace with real output
    return output_path


if __name__ == "__main__":
    raise SystemExit(caller_main(TASK_NAME, run))
