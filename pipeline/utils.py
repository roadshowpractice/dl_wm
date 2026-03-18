from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ClipEntry:
    clip_id: str
    start: float
    end: float
    path: str
    comment: str = ""


@dataclass
class ClipsManifest:
    source_video: str
    clips: list[ClipEntry]


@dataclass
class FinalSegment:
    order: int
    clip_id: str
    path: str
    comment: str = ""


@dataclass
class RenderSettings:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 18


@dataclass
class FinalManifest:
    title_image: str
    title_seconds: float
    segments: list[FinalSegment]
    render: RenderSettings


def run_cmd(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {lineno}: {exc}") from exc
    return rows


def ensure_ffmpeg() -> None:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        raise RuntimeError("ffmpeg is required but not available on PATH") from exc


def validate_clips_manifest(data: dict[str, Any]) -> ClipsManifest:
    if not isinstance(data, dict):
        raise ValueError("clips_manifest must be a JSON object")
    source_video = data.get("source_video")
    clips = data.get("clips")
    if not isinstance(source_video, str) or not source_video:
        raise ValueError("clips_manifest.source_video must be a non-empty string")
    if not isinstance(clips, list):
        raise ValueError("clips_manifest.clips must be a list")

    parsed: list[ClipEntry] = []
    for idx, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            raise ValueError(f"clips[{idx}] must be an object")
        try:
            clip_id = str(clip["clip_id"])
            start = float(clip["start"])
            end = float(clip["end"])
            path = str(clip["path"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"clips[{idx}] missing or invalid required fields") from exc
        if end <= start:
            raise ValueError(f"clips[{idx}] has end <= start")
        parsed.append(ClipEntry(clip_id=clip_id, start=start, end=end, path=path, comment=str(clip.get("comment", ""))))

    return ClipsManifest(source_video=source_video, clips=parsed)


def validate_final_manifest(data: dict[str, Any]) -> FinalManifest:
    if not isinstance(data, dict):
        raise ValueError("final_manifest must be a JSON object")
    title_image = data.get("title_image")
    title_seconds = data.get("title_seconds")
    segments = data.get("segments")
    render = data.get("render")
    if not isinstance(title_image, str) or not title_image:
        raise ValueError("final_manifest.title_image must be a non-empty string")
    if not isinstance(title_seconds, (int, float)) or title_seconds <= 0:
        raise ValueError("final_manifest.title_seconds must be positive")
    if not isinstance(segments, list):
        raise ValueError("final_manifest.segments must be a list")
    if not isinstance(render, dict):
        raise ValueError("final_manifest.render must be an object")

    parsed_segments: list[FinalSegment] = []
    for idx, seg in enumerate(segments, start=1):
        if not isinstance(seg, dict):
            raise ValueError(f"segments[{idx}] must be an object")
        try:
            parsed_segments.append(
                FinalSegment(
                    order=int(seg["order"]),
                    clip_id=str(seg["clip_id"]),
                    path=str(seg["path"]),
                    comment=str(seg.get("comment", "")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"segments[{idx}] missing or invalid fields") from exc

    try:
        render_settings = RenderSettings(
            width=int(render["width"]),
            height=int(render["height"]),
            fps=int(render["fps"]),
            video_codec=str(render["video_codec"]),
            audio_codec=str(render["audio_codec"]),
            crf=int(render["crf"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("render block has missing or invalid fields") from exc

    return FinalManifest(
        title_image=title_image,
        title_seconds=float(title_seconds),
        segments=parsed_segments,
        render=render_settings,
    )


def dataclass_to_dict(value: Any) -> dict[str, Any]:
    return asdict(value)
