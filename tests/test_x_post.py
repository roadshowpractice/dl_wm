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


def _tweet(tid, name, text, reply_to=None, note=None, new_schema=True):
    user = {"core": {"screen_name": name}} if new_schema else {"legacy": {"screen_name": name}}
    t = {"rest_id": tid, "core": {"user_results": {"result": user}},
         "legacy": {"full_text": text, "created_at": "Thu Oct 08 15:45:12 +0000 2026", "in_reply_to_status_id_str": reply_to}}
    if note:
        t["note_tweet"] = {"note_tweet_results": {"result": {"text": note}}}
    return t


def test_tweets_in_walks_nested_response_and_prefers_long_text():
    resp = {"data": {"threaded_conversation_with_injections_v2": {"instructions": [{"entries": [
        {"content": {"itemContent": {"tweet_results": {"result": _tweet("1", "MerrillAnt50522", "our post")}}}},
        {"content": {"items": [{"item": {"itemContent": {"tweet_results": {"result":
            _tweet("2", "grok", "short…", reply_to="1", note="the full long reply", new_schema=False)}}}}]}}]}]}}}
    got = xp.tweets_in(resp)
    assert set(got) == {"1", "2"}
    assert got["2"]["author"] == "grok" and got["2"]["text"] == "the full long reply" and got["2"]["in_reply_to"] == "1"
    assert got["1"]["author"] == "MerrillAnt50522"


def test_save_replies_skips_the_post_itself_and_repeats(tmp_path):
    class L:
        def __call__(self, *a, **k): pass
    tweets = {"1": {"id": "1", "author": "me", "created_at": "x", "in_reply_to": None, "text": "post"},
              "2": {"id": "2", "author": "grok", "created_at": "x", "in_reply_to": "1", "text": "reply"}}
    seen = set()
    assert xp.save_replies(tmp_path, "1", tweets, seen, L()) == 1
    assert xp.save_replies(tmp_path, "1", tweets, seen, L()) == 0
    lines = (tmp_path / "replies_1.jsonl").read_text().splitlines()
    assert len(lines) == 1 and '"sha256"' in lines[0]
    assert "@grok" in (tmp_path / "replies_1.txt").read_text()
