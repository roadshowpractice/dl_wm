from __future__ import annotations

import argparse
from pathlib import Path

from .utils import ensure_ffmpeg, load_json, run_cmd, validate_final_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 4: render final film from final_manifest.json")
    parser.add_argument("--manifest", required=True, help="final_manifest.json")
    parser.add_argument("--output", default="final_film.mp4")
    parser.add_argument("--black-seconds", type=float, default=0.0, help="Optional black spacer between segments")
    parser.add_argument("--work-dir", default=".pipeline_tmp")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ensure_ffmpeg()

    manifest = validate_final_manifest(load_json(Path(args.manifest)))
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    title_mp4 = work_dir / "title_card.mp4"
    black_mp4 = work_dir / "black_spacer.mp4"
    concat_txt = work_dir / "concat.txt"

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
            "anullsrc=r=44100:cl=stereo",
            "-t",
            str(manifest.title_seconds),
            "-vf",
            f"scale={manifest.render.width}:{manifest.render.height}:force_original_aspect_ratio=decrease,"
            f"pad={manifest.render.width}:{manifest.render.height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps={manifest.render.fps},format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            str(manifest.render.crf),
            "-c:a",
            "aac",
            "-shortest",
            str(title_mp4),
        ]
    )

    concat_lines = [f"file '{title_mp4.resolve()}'"]

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
                "anullsrc=r=44100:cl=stereo",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-shortest",
                str(black_mp4),
            ]
        )

    ordered_segments = sorted(manifest.segments, key=lambda s: s.order)
    for segment in ordered_segments:
        path = Path(segment.path)
        if not path.exists():
            raise FileNotFoundError(f"Missing segment file: {path}")
        if args.black_seconds > 0:
            concat_lines.append(f"file '{black_mp4.resolve()}'")
        concat_lines.append(f"file '{path.resolve()}'")

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
            "-r",
            str(manifest.render.fps),
            "-c:v",
            "libx264",
            "-crf",
            str(manifest.render.crf),
            "-c:a",
            "aac",
            "-af",
            "aresample=async=1",
            str(args.output),
        ]
    )

    print("\nStage 4 complete.")
    print(f"Output video: {args.output}")
    print(f"Used manifest: {args.manifest}")


if __name__ == "__main__":
    main()
