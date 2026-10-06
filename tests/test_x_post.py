import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import x_post as xp


def test_parse_dashes_and_numbered_headers():
    assert xp.parse_thread("a\n---\nb\n---\n") == ["a", "b"]
    assert xp.parse_thread("1/2\nfirst post\n\n2/2\nsecond") == ["first post", "second"]


def test_length_counts_links_as_23_and_emoji_as_2():
    assert xp.x_length("hi https://example.com/very/long/path") == len("hi ") + 23
    assert xp.x_length("🧵") == 2


def test_ats_validate_dedupe_and_place(tmp_path):
    f = tmp_path / "ats.txt"
    f.write_text("# comment\n@alice\nbob  # note\nalice\n")
    hs = xp.read_ats(f)
    assert hs == ["alice", "bob"]
    assert xp.apply_ats(["one", "two"], hs, "reply") == ["one", "two", "cc @alice @bob"]
    assert xp.apply_ats(["one", "two"], hs, "first")[0].endswith("@alice @bob")
    assert xp.apply_ats(["one", "two"], hs, "last")[1].endswith("@alice @bob")
    f.write_text("not a handle!\n")
    with pytest.raises(SystemExit):
        xp.read_ats(f)


def test_over_limit_stops():
    with pytest.raises(SystemExit):
        xp.check(["x" * 281])
