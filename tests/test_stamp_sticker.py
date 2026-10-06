import subprocess, sys
from pathlib import Path
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "stamp_sticker.py"


def test_stamps_corner_and_keeps_input(tmp_path):
    src = tmp_path / "card.png"
    Image.new("RGB", (1000, 800), (10, 20, 30)).save(src)
    subprocess.run([sys.executable, str(SCRIPT), str(src), "--rotate", "0", "--corner", "br"], check=True, capture_output=True)
    out = tmp_path / "card_stamped.png"
    im = Image.open(out).convert("RGB")
    assert im.size == (1000, 800)
    assert Image.open(src).convert("RGB").getpixel((900, 700)) == (10, 20, 30)   # input untouched
    assert im.getpixel((10, 10)) == (10, 20, 30)                                  # far corner untouched
    assert im.getpixel((800 - 24 + 176 // 2 + 0, 800 - 24 - 176 // 2)) != (10, 20, 30)  # sticker centre (br)


def test_refuses_to_overwrite(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (100, 100)).save(src)
    r = subprocess.run([sys.executable, str(SCRIPT), str(src), "-o", str(src)], capture_output=True, text=True)
    assert r.returncode != 0 and "overwrite" in r.stderr


def test_auto_picks_the_empty_corner(tmp_path):
    src = tmp_path / "busy.png"
    im = Image.new("RGB", (1000, 800), (0, 0, 0))
    import random
    rnd = random.Random(1)
    for x in range(1000):            # noise everywhere except the top-left quarter
        for y in range(800):
            if not (x < 500 and y < 400):
                im.putpixel((x, y), (rnd.randrange(256),) * 3)
    im.save(src)
    r = subprocess.run([sys.executable, str(SCRIPT), str(src)], check=True, capture_output=True, text=True)
    assert "(corner tl)" in r.stdout
