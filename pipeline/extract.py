from __future__ import annotations

import argparse
from pathlib import Path

from .utils import ClipEntry, ClipsManifest, dataclass_to_dict, dump_json, ensure_ffmpeg, load_jsonl, run_cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1: extract normalized clips from JSONL")
    parser.add_argument("--source-video", required=True, help="Watermarked source video path")
    parser.add_argument("--clips-jsonl", required=True, help="JSONL clip input with start/end/comment")
    parser.add_argument("--output-dir", default="clips", help="Output clip directory")
    parser.add_argument("--manifest-out", default="clips_manifest.json", help="Output clips manifest JSON")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--crf", type=int, default=18)
    return parser


def parse_timecode(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        raise ValueError("empty time value")

    try:
        return float(s)
    except ValueError:
        pass

    parts = s.split(":")
    if len(parts) == 2:
        mm, ss = parts
        return int(mm) * 60 + float(ss)
    if len(parts) == 3:
        hh, mm, ss = parts
        return int(hh) * 3600 + int(mm) * 60 + float(ss)

    raise ValueError(f"invalid time value: {value!r}")


def main() -> None:
    args = build_parser().parse_args()
    ensure_ffmpeg()

    source_video = Path(args.source_video)
    if not source_video.exists():
        raise FileNotFoundError(f"Source video not found: {source_video}")

    jobs = load_jsonl(Path(args.clips_jsonl))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    title_image: str | None = None
    title_seconds: float | None = None
    manifest_clips: list[ClipEntry] = []
    for idx, row in enumerate(jobs, start=1):
        clip_id = str(row.get("clip_id") or row.get("id") or "").strip()
        if not clip_id:
            raise ValueError(f"JSONL row {idx} missing clip_id/id")

        try:
            start = parse_timecode(row["start"])
        except KeyError:
            raise ValueError(f"JSONL row {idx} missing start") from None
        except ValueError as exc:
            raise ValueError(f"JSONL row {idx} has invalid start: {row.get('start')!r}") from exc

        try:
            end = parse_timecode(row["end"])
        except KeyError:
            raise ValueError(f"JSONL row {idx} missing end") from None
        except ValueError as exc:
            raise ValueError(f"JSONL row {idx} has invalid end: {row.get('end')!r}") from exc

        if end <= start:
            raise ValueError(f"JSONL row {idx} has end <= start")

        comment = str(row.get("comment") or row.get("caption") or "")
        row_title_image = row.get("title_image")
        if row_title_image not in (None, ""):
            row_title_image = str(row_title_image)
            if title_image is None:
                title_image = row_title_image
            elif row_title_image != title_image:
                raise ValueError("JSONL rows contain inconsistent title_image values")

        row_title_seconds = row.get("title_seconds")
        if row_title_seconds is not None:
            row_title_seconds = float(row_title_seconds)
            if row_title_seconds <= 0:
                raise ValueError(f"JSONL row {idx} has non-positive title_seconds")
            if title_seconds is None:
                title_seconds = row_title_seconds
            elif row_title_seconds != title_seconds:
                raise ValueError("JSONL rows contain inconsistent title_seconds values")

        clip_path = output_dir / f"{clip_id}.mp4"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                str(source_video),
                "-r",
                str(args.fps),
                "-c:v",
                "libx264",
                "-crf",
                str(args.crf),
                "-c:a",
                "aac",
                "-af",
                "aresample=async=1",
                "-movflags",
                "+faststart",
                str(clip_path),
            ]
        )

        manifest_clips.append(
            ClipEntry(
                clip_id=clip_id,
                start=start,
                end=end,
                path=str(clip_path),
                comment=comment,
            )
        )

    manifest = ClipsManifest(
        source_video=str(source_video),
        clips=manifest_clips,
        title_image=title_image,
        title_seconds=title_seconds,
    )
    dump_json(Path(args.manifest_out), dataclass_to_dict(manifest))

    print("\nStage 1 complete.")
    print(f"Extracted clips: {len(manifest_clips)}")
    print(f"Clip directory: {output_dir}")
    print(f"Manifest:       {args.manifest_out}")
    print("Next: inspect clip outputs manually before Stage 2 or Stage 3.")


if __name__ == "__main__":
    main()
