import os
import logging
import traceback
import subprocess

# Use the logger configured in the caller
logger = logging.getLogger(__name__)


def get_codecs_by_extension(extension):
    """Determine codecs based on file extension."""
    codecs = {
        ".webm": {"video_codec": "libvpx", "audio_codec": "libvorbis"},
        ".mp4": {"video_codec": "libx264", "audio_codec": "aac"},
        ".ogv": {"video_codec": "libtheora", "audio_codec": "libvorbis"},
        ".mkv": {"video_codec": "libx264", "audio_codec": "aac"},
    }
    return codecs.get(extension, {"video_codec": "libx264", "audio_codec": "aac"})


def looks_like_filename(value):
    if not value:
        return False
    text = str(value)
    return (
        "/" in text
        or "\\" in text
        or text.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi"))
    )


def _ffmpeg_escape(text):
    return str(text).replace('\\', r'\\').replace(':', r'\:').replace("'", r"\'")


def _position_to_expr(position):
    x_raw = str((position or ["left", "top"])[0]).lower()
    y_raw = str((position or ["left", "top"])[1]).lower()

    x_expr = {
        "left": "20",
        "center": "(w-text_w)/2",
        "right": "w-text_w-20",
    }.get(x_raw, x_raw)

    y_expr = {
        "top": "20",
        "center": "(h-text_h)/2",
        "bottom": "h-text_h-20",
    }.get(y_raw, y_raw)

    return x_expr, y_expr


def _drawtext_filter(text, color, font, font_size, position, box=True):
    x_expr, y_expr = _position_to_expr(position)
    escaped_text = _ffmpeg_escape(text)
    base = (
        f"drawtext=fontfile='{_ffmpeg_escape(font)}':"
        f"text='{escaped_text}':"
        f"fontcolor={color}:fontsize={font_size}:"
        f"x={x_expr}:y={y_expr}"
    )
    if box:
        base += ":box=1:boxcolor=black@0.35:boxborderw=8"
    return base


def _timestamp_filter(color, font, font_size, position, box=True):
    x_expr, y_expr = _position_to_expr(position)

    elapsed_hms = (
        "%{eif\\:trunc(t/3600)\\:d\\:2}"
        "\\:%{eif\\:trunc(mod(t\\,3600)/60)\\:d\\:2}"
        "\\:%{eif\\:trunc(mod(t\\,60))\\:d\\:2}"
    )

    base = (
        f"drawtext=fontfile='{_ffmpeg_escape(font)}':"
        f"text='{elapsed_hms}':"
        f"fontcolor={color}:fontsize={font_size}:"
        f"x={x_expr}:y={y_expr}"
    )

    if box:
        base += ":box=1:boxcolor=black@0.35:boxborderw=8"

    return base

def _truncate_for_label(text: str, max_chars: int = 120) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def build_source_label(uploader: str, upload_date: str, title: str, max_chars: int = 160) -> str:
    pieces = [piece.strip() for piece in [uploader, upload_date, title] if str(piece or "").strip()]
    return _truncate_for_label(" | ".join(pieces), max_chars=max_chars)


def add_watermark(params):
    """Add watermarks using ffmpeg drawtext for low-memory processing."""
    logger.debug("Received parameters for watermarking.")
    for key, value in params.items():
        logger.debug(f"{key}: {value}")

    input_video_path = params.get("input_video_path")
    if not input_video_path:
        raise ValueError("Missing required parameter: 'input_video_path'")

    try:
        logger.info(f"Processing video: {input_video_path}")

        filename, ext = os.path.splitext(os.path.basename(input_video_path))
        explicit_output_path = params.get("output_video_path")
        if explicit_output_path:
            watermarked_video_path = str(explicit_output_path)
        else:
            watermarked_video_path = os.path.join(
                params["download_path"], f"{filename}_watermarked{ext}"
            )

        font = params.get("font", "")
        if not font or not os.path.exists(font):
            raise FileNotFoundError(f"Watermark font not found: {font}")

        font_size = int(params.get("font_size", 32) or 32)
        preset = params.get("ffmpeg_preset", "veryfast")
        crf = int(params.get("ffmpeg_crf", 23) or 23)
        threads = int(params.get("ffmpeg_threads", 0) or 0)

        filters = []

        username_text = params.get("source_label") or params.get("username", "")
        if username_text and not looks_like_filename(username_text):
            filters.append(
                _drawtext_filter(
                    username_text,
                    params.get("username_color", "yellow"),
                    font,
                    font_size,
                    params.get("username_position", ["left", "top"]),
                )
            )

        if not params.get("source_label"):
            filters.append(
                _drawtext_filter(
                    params.get("video_date", ""),
                    params.get("date_color", "cyan"),
                    font,
                    font_size,
                    params.get("date_position", ["left", "bottom"]),
                )
            )

        filters.append(
            _timestamp_filter(
                params.get("timestamp_color", "red"),
                font,
                font_size,
                params.get("timestamp_position", ["right", "bottom"]),
            )
        )

        vf = ",".join(filters)
        codecs = get_codecs_by_extension(ext)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_video_path,
            "-vf",
            vf,
            "-c:v",
            codecs["video_codec"],
            "-preset",
            str(preset),
            "-crf",
            str(crf),
            "-c:a",
            "copy",
        ]
        if threads > 0:
            cmd.extend(["-threads", str(threads)])
        cmd.append(watermarked_video_path)

        logger.info("Exporting watermarked video with ffmpeg (memory-optimized path)...")
        logger.debug("ffmpeg command: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            stderr_tail = "\n".join(result.stderr.splitlines()[-30:])
            raise RuntimeError(f"ffmpeg watermark failed (exit {result.returncode}):\n{stderr_tail}")

        logger.info(f"Watermarked video saved to: {watermarked_video_path}")
        return {"to_process": watermarked_video_path}

    except Exception as e:
        logger.error(f"Error in add_watermark: {e}")
        logger.debug(traceback.format_exc())
        return None
