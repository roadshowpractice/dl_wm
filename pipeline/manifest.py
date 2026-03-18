from __future__ import annotations

import argparse
from pathlib import Path

from .utils import FinalManifest, FinalSegment, RenderSettings, dataclass_to_dict, dump_json, load_json, validate_clips_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 3: build final_manifest.json from clips manifest")
    parser.add_argument("--clips-manifest", required=True)
    parser.add_argument("--title-image", required=True)
    parser.add_argument("--title-seconds", type=float, default=2.0)
    parser.add_argument("--output", default="final_manifest.json")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--video-codec", default="libx264")
    parser.add_argument("--audio-codec", default="aac")
    parser.add_argument("--crf", type=int, default=18)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    clips = validate_clips_manifest(load_json(Path(args.clips_manifest)))

    segments: list[FinalSegment] = []
    for idx, clip in enumerate(clips.clips, start=1):
        segments.append(FinalSegment(order=idx, clip_id=clip.clip_id, path=clip.path, comment=clip.comment))

    final_manifest = FinalManifest(
        title_image=args.title_image,
        title_seconds=args.title_seconds,
        segments=segments,
        render=RenderSettings(
            width=args.width,
            height=args.height,
            fps=args.fps,
            video_codec=args.video_codec,
            audio_codec=args.audio_codec,
            crf=args.crf,
        ),
    )

    dump_json(Path(args.output), dataclass_to_dict(final_manifest))

    print("\nStage 3 complete (critical checkpoint).")
    print(f"Segments written: {len(segments)}")
    print(f"Final manifest:   {args.output}")
    print("Review/edit final_manifest.json before running Stage 4.")


if __name__ == "__main__":
    main()
