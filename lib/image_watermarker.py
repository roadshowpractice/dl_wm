"""Watermark still images the way watermarker2 does video.

Uploader top-left (yellow), date bottom-left (cyan), and, where a video has its
running timestamp, the slide number "N/M" bottom-right (red). Same font and
translucent black box. Sizes scale with image width, 1080 px = the config size,
so a 3720 px Facebook photo gets proportionally larger text.
"""
import logging
import os

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

REFERENCE_WIDTH = 1080
MARGIN = 20
BOX_BORDER = 8
BOX_RGBA = (0, 0, 0, int(255 * 0.35))
COLORS = {"yellow": (255, 255, 0), "cyan": (0, 255, 255), "red": (255, 0, 0), "white": (255, 255, 255)}


def _rgb(name):
    return COLORS.get(str(name).lower(), COLORS["white"])


def _place(position, text_w, text_h, img_w, img_h, margin):
    x_raw, y_raw = [str(p).lower() for p in (position or ["left", "top"])]
    x = {"left": margin, "center": (img_w - text_w) // 2, "right": img_w - text_w - margin}.get(x_raw, margin)
    y = {"top": margin, "center": (img_h - text_h) // 2, "bottom": img_h - text_h - margin}.get(y_raw, margin)
    return x, y


def watermark_image(input_path, output_path, *, username="", date="", slide_label="", config=None):
    """Write a watermarked copy of input_path to output_path. Returns output_path."""
    config = config or {}
    font_path = config.get("font", "")
    if not font_path or not os.path.exists(font_path):
        raise FileNotFoundError(f"Watermark font not found: {font_path}")

    im = Image.open(input_path)
    icc = im.info.get("icc_profile")
    im = im.convert("RGBA")
    w, h = im.size
    scale = max(w, 1) / REFERENCE_WIDTH
    font = ImageFont.truetype(font_path, max(12, round(int(config.get("font_size", 32) or 32) * scale)))
    margin, border = round(MARGIN * scale), max(2, round(BOX_BORDER * scale))

    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    labels = [
        (username, config.get("username_color", "yellow"), config.get("username_position", ["left", "top"])),
        (date, config.get("date_color", "cyan"), config.get("date_position", ["left", "bottom"])),
        (slide_label, config.get("timestamp_color", "red"), config.get("timestamp_position", ["right", "bottom"])),
    ]
    for text, color, position in labels:
        text = str(text or "").strip()
        if not text:
            continue
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        tw, th = right - left, bottom - top
        x, y = _place(position, tw, th, w, h, margin)
        draw.rectangle([x - border, y - border, x + tw + border, y + th + border], fill=BOX_RGBA)
        draw.text((x - left, y - top), text, font=font, fill=_rgb(color) + (255,))

    out = Image.alpha_composite(im, layer).convert("RGB")
    save_kwargs = {"quality": 95} if output_path.lower().endswith((".jpg", ".jpeg")) else {}
    if icc:
        save_kwargs["icc_profile"] = icc
    out.save(output_path, **save_kwargs)
    logger.info("Watermarked image saved to: %s", output_path)
    return output_path
