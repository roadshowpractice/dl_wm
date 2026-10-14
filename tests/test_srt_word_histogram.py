import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "srt_word_histogram.py"

SRT = """1
00:00:01,000 --> 00:00:02,000
Zion zion and the <i>temple</i>

2
00:00:02,500 --> 00:00:04,000
the temple of Zion
"""


def test_counts_key_and_dated_copy(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text(SRT)
    out = tmp_path / "out" / "a"
    subprocess.run([sys.executable, str(SCRIPT), str(srt), "-o", str(out)], check=True)
    counts = (tmp_path / "out" / "a_word_counts.txt").read_text().splitlines()
    assert counts[1].split() == ["3", "zion"]          # filler "the/and/of" dropped, tags stripped
    assert counts[2].split() == ["2", "temple"]
    assert (tmp_path / "out" / "a_word_histogram.png").stat().st_size > 0
    assert len(list((tmp_path / "out" / "history").glob("a_word_histogram_*.png"))) == 1


def test_filler_label_names_each_filtered_language():
    sys.path.insert(0, str(SCRIPT.parent))
    import srt_word_histogram as h
    assert h.filler_label() == "filler words left out (the, and, you...)"
    assert "el, que, y" in h.filler_label(es=True) and "o, de, que" not in h.filler_label(es=True)
    assert "o, de, que" in h.filler_label(pt=True)
