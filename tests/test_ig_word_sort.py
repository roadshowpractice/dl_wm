import importlib.util
import json
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "ig_word_sort", pathlib.Path(__file__).resolve().parents[1] / "bin" / "ig_word_sort.py"
)
ws = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ws)


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_reads_profile_history_timeline(tmp_path):
    folder = tmp_path / "hiddenwarmovie_2026-10-04"
    folder.mkdir()
    _write(folder / "hiddenwarmovie_timeline.jsonl", [
        {"shortcode": "A1", "taken_at": 1760134687, "caption": "Hidden War in theaters #HiddenWar @timballard89",
         "carousel_count": 0, "collaborators": ["hiddenwarmovie", "timballard89"]},
    ])
    src = ws.find_input(folder)
    assert ws.account_name(src) == "hiddenwarmovie"
    posts = ws.load_posts(src)
    assert posts[0]["code"] == "A1"
    c, cut_at = ws.count(posts)
    assert cut_at is None
    assert c["hashtags"]["hiddenwar"] == 1
    assert c["mentions"]["timballard89"] == 1
    assert c["collaborators"]["timballard89"] == 1
    assert c["words"]["hidden"] == 1 and "in" not in c["words"]
    assert c["months"]["2025-10"] == 1


def test_reads_forensic_capture(tmp_path):
    folder = tmp_path / "someone_2026-10-03_forensic"
    folder.mkdir()
    _write(folder / "posts.jsonl", [
        {"code": "B1", "taken_at": 1635010907, "caption": "full caption text here",
         "collaborators": ["someone"], "location": "Las Vegas, Nevada"},
        {"code": "B2", "taken_at": 1635010999, "caption": "", "location": {"name": "Paris"}},
    ])
    src = ws.find_input(folder)
    assert src.name == "posts.jsonl"
    assert ws.account_name(src) == "someone"
    c, _ = ws.count(ws.load_posts(src))
    assert c["locations"] == {"Las Vegas, Nevada": 1, "Paris": 1}


def test_truncated_captions_lose_their_cut_last_word():
    base = "x" * 190 + " "
    posts = [
        {"code": str(i), "taken_at": 0, "caption": (base + "#thetruth")[:200], "collaborators": [], "location": None}
        for i in range(5)
    ]
    c, cut_at = ws.count(posts)
    assert cut_at == 200
    assert not c["hashtags"]


def test_untruncated_captions_are_left_alone():
    posts = [{"code": "1", "taken_at": 0, "caption": "short one #tag", "collaborators": [], "location": None}]
    c, cut_at = ws.count(posts)
    assert cut_at is None
    assert c["hashtags"]["tag"] == 1


def test_main_writes_report(tmp_path):
    src = _write(tmp_path / "acct_timeline.jsonl", [
        {"shortcode": "C1", "taken_at": 1760134687, "caption": "real truth real story", "collaborators": []},
    ])
    out = tmp_path / "report.txt"
    assert ws.main([str(src), "--out", str(out)]) == 0
    text = out.read_text()
    assert "WORD SORT — acct" in text
    assert "     2  real" in text
    assert "real truth" not in text  # pairs need 2+ sightings
