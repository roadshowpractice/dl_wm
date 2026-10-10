import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FONT = str(ROOT / "fonts" / "Inter-Bold.otf")

# Other test files leave stub lib modules in sys.modules; load the real ones by path.
_STUBBED = ("tasks_lib", "teton_utils", "vendor_router")
_saved = {name: sys.modules.pop(name) for name in _STUBBED if name in sys.modules}
sys.path.insert(0, str(ROOT / "lib"))
_spec = importlib.util.spec_from_file_location("call_watermark_images_under_test", ROOT / "bin" / "call_watermark_images.py")
cwi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cwi)
from image_watermarker import watermark_image
sys.modules.update(_saved)


def test_watermark_marks_corners_and_keeps_size(tmp_path):
    src = tmp_path / "p.jpg"
    Image.new("RGB", (3720, 4096), (128, 128, 128)).save(src, quality=95)
    out = tmp_path / "p_watermarked.jpg"
    watermark_image(str(src), str(out), username="Tim Ballard", date="2026-10-08", slide_label="2/5", config={"font": FONT})
    im = Image.open(out)
    assert im.size == (3720, 4096)
    w, h = im.size
    gray = (128, 128, 128)

    def changed(box):
        return any(abs(a - b) > 30 for px in im.crop(box).getdata() for a, b in zip(px, gray))

    assert changed((0, 0, w // 4, h // 20))  # uploader, top left
    assert changed((0, h - h // 20, w // 4, h))  # date, bottom left
    assert changed((w - w // 8, h - h // 20, w, h))  # slide number, bottom right
    assert not changed((w // 3, h // 3, 2 * w // 3, 2 * h // 3))  # middle untouched


def test_image_files_in_slide_order_skips_videos(tmp_path):
    for name in ("x__01.jpg", "x__02.mp4", "x__03.png"):
        (tmp_path / name).write_bytes(b"0")
    data = {
        "default_tasks": {"perform_download": str(tmp_path / "x__01.jpg")},
        "manifest": {"items": [{"index": 3, "filename": "x__03.png"}, {"index": 1, "filename": "x__01.jpg"},
                               {"index": 2, "filename": "x__02.mp4"}]},
    }
    assert cwi.image_files(data) == [str(tmp_path / "x__01.jpg"), str(tmp_path / "x__03.png")]
    assert cwi.display_date("20261008") == "2026-10-08"
