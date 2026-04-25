from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .utils import (
    ensure_ffmpeg,
    load_json,
    normalized_anullsrc,
    normalized_audio_codec_args,
    normalized_concat_audio_filter,
    normalized_video_codec_args,
    run_cmd,
    validate_final_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 4: render final film from final_manifest.json")
    parser.add_argument("--manifest", required=True, help="final_manifest.json")
    parser.add_argument("--output", default="final_film.mp4")
    parser.add_argument("--black-seconds", type=float, default=0.0, help="Optional black spacer between segments")
    parser.add_argument("--work-dir", default=".pipeline_tmp")
    return parser


def prepare_make_final_film_inputs(manifest_path: Path, jsonl_path: Path, clip_dir: Path) -> tuple[Path, Path]:
    manifest = validate_final_manifest(load_json(manifest_path))
    clip_dir.mkdir(parents=True, exist_ok=True)

    jsonl_lines: list[str] = []
    ordered_segments = sorted(manifest.segments, key=lambda s: s.order)
    for segment in ordered_segments:
        src = Path(segment.path)
        if not src.exists():
            raise FileNotFoundError(f"Missing segment file: {src}")

        dst = clip_dir / f"{segment.clip_id}.mp4"
        if dst.exists() or dst.is_symlink():
            dst.unlink()

        os.symlink(src.resolve(), dst)
        jsonl_lines.append(json.dumps({"clip_id": segment.clip_id}, ensure_ascii=False))

    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.write_text("\n".join(jsonl_lines) + "\n", encoding="utf-8")
    return jsonl_path, clip_dir


def main() -> None:
    args = build_parser().parse_args()
    ensure_ffmpeg()

    manifest = validate_final_manifest(load_json(Path(args.manifest)))
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    black_mp4 = work_dir / "black_spacer.mp4"
    concat_txt = work_dir / "concat.txt"
    concat_lines: list[str] = []

    if manifest.title_image:
        title_mp4 = work_dir / "title_card.mp4"
        title_image = Path(manifest.title_image)
        if not title_image.exists():
            raise FileNotFoundError(f"title_image missing: {title_image}")

        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(title_image),
                "-f",
                "lavfi",
                "-i",
                normalized_anullsrc(),
                "-t",
                str(manifest.title_seconds),
                "-vf",
                f"scale={manifest.render.width}:{manifest.render.height}:force_original_aspect_ratio=decrease,"
                f"pad={manifest.render.width}:{manifest.render.height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"fps={manifest.render.fps},format=yuv420p",
                *normalized_video_codec_args(fps=manifest.render.fps, crf=manifest.render.crf),
                *normalized_audio_codec_args(),
                "-shortest",
                str(title_mp4),
            ]
        )
        concat_lines.append(f"file '{title_mp4.resolve()}'")

    if args.black_seconds > 0:
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={manifest.render.width}x{manifest.render.height}:r={manifest.render.fps}:d={args.black_seconds}",
                "-f",
                "lavfi",
                "-i",
                normalized_anullsrc(),
                *normalized_video_codec_args(fps=manifest.render.fps),
                *normalized_audio_codec_args(),
                "-shortest",
                str(black_mp4),
            ]
        )

    ordered_segments = sorted(manifest.segments, key=lambda s: s.order)
    for segment in ordered_segments:
        path = Path(segment.path)
        if not path.exists():
            raise FileNotFoundError(f"Missing segment file: {path}")

        normalized_segment = work_dir / f"{segment.clip_id}.normalized.mp4"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(path),
                "-vf",
                f"scale={manifest.render.width}:{manifest.render.height}:force_original_aspect_ratio=decrease,"
                f"pad={manifest.render.width}:{manifest.render.height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"fps={manifest.render.fps},format=yuv420p",
                *normalized_video_codec_args(fps=manifest.render.fps, crf=manifest.render.crf),
                *normalized_audio_codec_args(),
                str(normalized_segment),
            ]
        )

        if args.black_seconds > 0:
            concat_lines.append(f"file '{black_mp4.resolve()}'")
        concat_lines.append(f"file '{normalized_segment.resolve()}'")

    concat_txt.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            *normalized_video_codec_args(fps=manifest.render.fps, crf=manifest.render.crf),
            *normalized_audio_codec_args(),
            "-af",
            normalized_concat_audio_filter(),
            str(args.output),
        ]
    )

    print("\nStage 4 complete.")
    print(f"Output video: {args.output}")
    print(f"Used manifest: {args.manifest}")


if __name__ == "__main__":
    main()
