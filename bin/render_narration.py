#!/usr/bin/env python3
"""
render_narration.py — Convert narration.jsonl lines into Piper-generated WAV files.

Part of the dl_wm (Dunlop Watermark) pipeline.

Usage:
    python bin/render_narration.py narration.jsonl --outdir audio/narration --model en_US-lessac-medium.onnx

Input format (narration.jsonl):
    One JSON object per line, matching the clip .jsonl convention used by
    clip_driver.sh:

        {"id": "clip_001", "text": "Welcome to this walkthrough of the setup."}
        {"id": "clip_002", "text": "Next, we'll look at how the pipeline handles watermarking."}

    - id:   matches the existing clip ID scheme so output WAVs pair up
            cleanly with clip_driver.sh
    - text: the plain narration line, one sentence or one clip's worth

Output:
    <outdir>/<id>.wav for each line, ready to hand to the existing ffmpeg
    mux step.
"""
import argparse
import json
import subprocess
from pathlib import Path


def render_line(text: str, model: str, out_path: Path) -> None:
    """Pipe text into piper and write a wav file."""
    proc = subprocess.run(
        ["piper", "--model", model, "--output_file", str(out_path)],
        input=text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"piper failed for {out_path.name}: {proc.stderr.decode().strip()}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Render narration.jsonl to WAV via Piper"
    )
    parser.add_argument("jsonl_path", type=Path, help="Path to narration.jsonl")
    parser.add_argument(
        "--outdir", type=Path, required=True, help="Output directory for WAV files"
    )
    parser.add_argument(
        "--model", type=Path, required=True, help="Path to Piper .onnx voice model"
    )
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    with args.jsonl_path.open() as f:
        lines = [json.loads(line) for line in f if line.strip()]

    for entry in lines:
        clip_id = entry["id"]
        text = entry["text"]
        out_path = args.outdir / f"{clip_id}.wav"
        print(f"Rendering {clip_id} -> {out_path}")
        render_line(text, str(args.model), out_path)

    print(f"Done. {len(lines)} narration file(s) written to {args.outdir}")


if __name__ == "__main__":
    main()
