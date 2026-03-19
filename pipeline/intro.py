from __future__ import annotations

import argparse
from pathlib import Path

from .utils import ClipEntry, ClipsManifest, dataclass_to_dict, dump_json, ensure_ffmpeg, load_json, run_cmd, validate_clips_manifest


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(",", "\\,")
        .replace("%", "\\%")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 2: prepend white forensic cards to clips")
    parser.add_argument("--manifest", required=True, help="Input clips_manifest.json")
    parser.add_argument("--output-dir", default="clips_with_intro")
    parser.add_argument("--manifest-out", default="clips_with_intro_manifest.json")
    parser.add_argument("--font", required=True, help="Font file used for drawtext")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--intro-seconds", type=float, default=2.0)
    parser.add_argument("--black-seconds", type=float, default=0.0, help="Optional black spacer duration; 0 disables")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ensure_ffmpeg()

    font = Path(args.font)
    if not font.exists():
        raise FileNotFoundError(f"Font not found: {font}")

    manifest = validate_clips_manifest(load_json(Path(args.manifest)))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    updated: list[ClipEntry] = []
    for clip in manifest.clips:
        clip_src = Path(clip.path)
        if not clip_src.exists():
            raise FileNotFoundError(f"Missing clip referenced by manifest: {clip_src}")

        intro_file = out_dir / f"{clip.clip_id}__intro.mp4"
        black_file = out_dir / f"{clip.clip_id}__black.mp4"
        final_file = out_dir / f"{clip.clip_id}.mp4"
        concat_file = out_dir / f"{clip.clip_id}__concat.txt"

        drawtext = (
            f"drawtext=fontfile={font}:text='{escape_drawtext(clip.comment or clip.clip_id)}':"
            f"fontcolor=black:fontsize=56:x=(w-text_w)/2:y=(h-text_h)/2:"
            "box=1:boxcolor=white@0.8:boxborderw=24"
        )

        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=white:s={args.width}x{args.height}:r={args.fps}:d={args.intro_seconds}",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=stereo",
                "-vf",
                drawtext,
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-shortest",
                str(intro_file),
            ]
        )

        concat_lines = [f"file '{intro_file.name}'"]

        if args.black_seconds > 0:
            run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=black:s={args.width}x{args.height}:r={args.fps}:d={args.black_seconds}",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=44100:cl=stereo",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(black_file),
                ]
            )
            concat_lines.append(f"file '{black_file.name}'")

        concat_lines.append(f"file '{clip_src.resolve()}'")
        concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-af",
                "aresample=async=1",
                str(final_file),
            ]
        )

        updated.append(
            ClipEntry(
                clip_id=clip.clip_id,
                start=clip.start,
                end=clip.end,
                path=str(final_file),
                comment=clip.comment,
                srt_path=clip.srt_path,
            )
        )

    out_manifest = ClipsManifest(
        source_video=manifest.source_video,
        clips=updated,
        title_image=manifest.title_image,
        title_seconds=manifest.title_seconds,
        render=manifest.render,
    )
    dump_json(Path(args.manifest_out), dataclass_to_dict(out_manifest))

    print("\nStage 2 complete (optional stage).")
    print(f"Rendered intro clips: {len(updated)}")
    print(f"Output directory:     {out_dir}")
    print(f"Updated manifest:     {args.manifest_out}")
    print("Next: run Stage 3 when ready.")


if __name__ == "__main__":
    main()
