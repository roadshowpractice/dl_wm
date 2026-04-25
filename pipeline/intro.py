from __future__ import annotations

import argparse
from pathlib import Path

from .utils import (
    ClipEntry,
    ClipsManifest,
    dataclass_to_dict,
    dump_json,
    ensure_ffmpeg,
    load_json,
    normalized_anullsrc,
    normalized_audio_codec_args,
    normalized_concat_audio_filter,
    normalized_video_codec_args,
    probe_video_dimensions,
    run_cmd,
    validate_clips_manifest,
)


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
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--intro-seconds", type=float, default=2.0)
    parser.add_argument("--black-seconds", type=float, default=0.0, help="Optional black spacer duration; 0 disables")
    return parser


def render_intro_manifest(
    manifest: ClipsManifest,
    *,
    output_dir: Path,
    font: Path,
    width: int | None = None,
    height: int | None = None,
    fps: int = 30,
    intro_seconds: float = 2.0,
    black_seconds: float = 0.0,
) -> ClipsManifest:
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_width, resolved_height = _resolve_output_dimensions(manifest, width=width, height=height)

    updated: list[ClipEntry] = []
    for clip in manifest.clips:
        clip_src = Path(clip.path)
        if not clip_src.exists():
            raise FileNotFoundError(f"Missing clip referenced by manifest: {clip_src}")

        normalized_clip_path = output_dir / f"{clip.clip_id}.normalized.mp4"

        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(clip_src),
                "-vf",
                f"scale={resolved_width}:{resolved_height}:force_original_aspect_ratio=decrease,"
                f"pad={resolved_width}:{resolved_height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"fps={fps},format=yuv420p",
                *normalized_video_codec_args(fps=fps),
                *normalized_audio_codec_args(),
                str(normalized_clip_path),
            ]
        )

        intro_card_path = output_dir / f"{clip.clip_id}.card.mp4"
        black_file = output_dir / f"{clip.clip_id}__black.mp4"
        final_file = output_dir / f"{clip.clip_id}.mp4"
        concat_file = output_dir / f"{clip.clip_id}__concat.txt"

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
                f"color=c=white:s={resolved_width}x{resolved_height}:r={fps}:d={intro_seconds}",
                "-f",
                "lavfi",
                "-i",
                normalized_anullsrc(),
                "-vf",
                drawtext,
                *normalized_video_codec_args(fps=fps),
                *normalized_audio_codec_args(),
                "-shortest",
                str(intro_card_path),
            ]
        )

        concat_lines = [f"file '{intro_card_path.name}'"]

        if black_seconds > 0:
            run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=black:s={resolved_width}x{resolved_height}:r={fps}:d={black_seconds}",
                    "-f",
                    "lavfi",
                    "-i",
                    normalized_anullsrc(),
                    *normalized_video_codec_args(fps=fps),
                    *normalized_audio_codec_args(),
                    "-shortest",
                    str(black_file),
                ]
            )
            concat_lines.append(f"file '{black_file.name}'")

        concat_lines.append(f"file '{normalized_clip_path.name}'")
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
                *normalized_video_codec_args(fps=fps),
                *normalized_audio_codec_args(),
                "-af",
                normalized_concat_audio_filter(),
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

    return ClipsManifest(
        source_video=manifest.source_video,
        clips=updated,
        title_image=manifest.title_image,
        title_seconds=manifest.title_seconds,
        render=manifest.render,
    )


def _resolve_output_dimensions(manifest: ClipsManifest, *, width: int | None, height: int | None) -> tuple[int, int]:
    manifest_width = manifest.render.width if manifest.render is not None else None
    manifest_height = manifest.render.height if manifest.render is not None else None
    clip_probe: tuple[int, int] | None = None

    if manifest.clips:
        first_clip = Path(manifest.clips[0].path)
        if first_clip.exists():
            try:
                clip_probe = probe_video_dimensions(first_clip)
            except RuntimeError:
                clip_probe = None

    resolved_width = width or manifest_width or (clip_probe[0] if clip_probe is not None else None) or 1920
    resolved_height = height or manifest_height or (clip_probe[1] if clip_probe is not None else None) or 1080
    return resolved_width, resolved_height


def main() -> None:
    args = build_parser().parse_args()
    ensure_ffmpeg()

    font = Path(args.font)
    if not font.exists():
        raise FileNotFoundError(f"Font not found: {font}")

    manifest = validate_clips_manifest(load_json(Path(args.manifest)))
    out_manifest = render_intro_manifest(
        manifest,
        output_dir=Path(args.output_dir),
        font=font,
        width=args.width,
        height=args.height,
        fps=args.fps,
        intro_seconds=args.intro_seconds,
        black_seconds=args.black_seconds,
    )
    dump_json(Path(args.manifest_out), dataclass_to_dict(out_manifest))

    print("\nStage 2 complete (optional stage).")
    print(f"Rendered intro clips: {len(out_manifest.clips)}")
    print(f"Output directory:     {args.output_dir}")
    print(f"Updated manifest:     {args.manifest_out}")
    print("Next: run Stage 3 when ready.")


if __name__ == "__main__":
    main()
