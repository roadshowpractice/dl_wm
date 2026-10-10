"""Watermark every photo in a downloaded post (the video watermark step skips photos).

Usage:
    python bin/call_watermark_images.py metadata/<vendor>__<id>.json

Reads the post's items (`items`, or `manifest.items` for Instagram), writes
`<stem>_watermarked.<ext>` next to each photo, and records the first one as
`apply_watermark` in the metadata. Videos in a mixed carousel are left to the
video watermark step.
"""
import json
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
lib_path = os.path.join(root_dir, "lib")
if lib_path not in sys.path:
    sys.path.append(lib_path)

from image_watermarker import watermark_image
from tasks_lib import update_task_output_path
from teton_utils import initialize_logging_from_config, load_app_config, load_config

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def image_files(data):
    """Photo files of the post, in slide order."""
    first = data.get("default_tasks", {}).get("perform_download") or data.get("downloaded_file")
    if not isinstance(first, str):
        return []
    folder = os.path.dirname(first)
    items = data.get("items") or (data.get("manifest") or {}).get("items") or []
    names = [i["filename"] for i in sorted(items, key=lambda i: i.get("index", 0)) if i.get("filename")]
    paths = [os.path.join(folder, n) for n in names] or [first]
    return [p for p in paths if os.path.splitext(p)[1].lower() in IMAGE_EXTENSIONS and os.path.isfile(p)]


def display_date(value):
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def main(argv):
    app_config = load_app_config()
    logger = initialize_logging_from_config({**load_config().get("logging", {}), **app_config.get("logging", {})})
    if len(argv) != 1 or not os.path.isfile(argv[0]):
        logger.error("Usage: call_watermark_images.py METADATA_JSON")
        return 1
    meta_path = argv[0]
    with open(meta_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    config = dict(app_config.get("watermark_config", {}))
    if config.get("font") and not os.path.isabs(config["font"]):
        config["font"] = os.path.join(root_dir, config["font"])

    photos = image_files(data)
    if not photos:
        logger.error("No photo files found for %s", meta_path)
        return 1

    username = data.get("uploader") or ""
    date = display_date(data.get("video_date"))
    outputs = []
    for n, path in enumerate(photos, start=1):
        stem, ext = os.path.splitext(path)
        out = f"{stem}_watermarked{ext}"
        label = f"{n}/{len(photos)}" if len(photos) > 1 else ""
        outputs.append(watermark_image(path, out, username=username, date=date, slide_label=label, config=config))

    update_task_output_path(meta_path, "apply_watermark", outputs[0])
    for out in outputs:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
