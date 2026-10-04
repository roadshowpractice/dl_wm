import importlib.util
import json
import pathlib

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cn = _load("collabnet")
graph = _load("ig_collab_graph")


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_read_queue_skips_comments_blanks_and_duplicates(tmp_path):
    q = tmp_path / "q.txt"
    q.write_text("# header\nHiddenWarMovie   # seed\n\ntimballard89 # 24\nhiddenwarmovie\n", encoding="utf-8")
    assert cn.read_queue(q) == ["hiddenwarmovie", "timballard89"]


def test_existing_capture_ignores_flat_and_empty_files(tmp_path):
    _write(tmp_path / "acct.jsonl", [{"shortcode": "x"}])                 # old flat partial
    (tmp_path / "acct_2026-10-01").mkdir()
    (tmp_path / "acct_2026-10-01" / "acct_timeline.jsonl").write_text("")  # empty scrape
    assert cn.existing_capture("acct", root=tmp_path) is None
    full = _write(tmp_path / "acct_2026-10-04" / "acct_timeline.jsonl", [{"shortcode": "y"}])
    assert cn.existing_capture("acct", root=tmp_path) == full


def test_collaborators_of_and_snowball_append(tmp_path):
    tl = _write(tmp_path / "t.jsonl", [
        {"shortcode": "a", "collaborators": ["acct", "Partner"]},
        {"shortcode": "b", "collaborators": ["partner", "other"]},
    ])
    found = cn.collaborators_of(tl, "acct")
    assert found == {"partner": 2, "other": 1}
    q = tmp_path / "q.txt"
    q.write_text("acct\n", encoding="utf-8")
    cn.append_to_queue(q, found, "acct")
    assert cn.read_queue(q) == ["acct", "partner", "other"]
    assert "# from acct, 2 posts" in q.read_text()


def test_graph_counts_a_shared_post_once(tmp_path):
    # the same co-authored post shows up in both accounts' scrapes
    _write(tmp_path / "a_2026-10-04" / "a_timeline.jsonl",
           [{"shortcode": "P1", "taken_at": 1, "collaborators": ["a", "b"]}])
    _write(tmp_path / "b_2026-10-04" / "b_timeline.jsonl",
           [{"shortcode": "P1", "taken_at": 1, "collaborators": ["a", "b"]},
            {"shortcode": "P2", "taken_at": 2, "collaborators": ["b", "c"]}])
    files = graph.account_files(root=tmp_path)
    posts, counts = graph.load_posts(files)
    edges = graph.build_edges(posts)
    assert edges[("a", "b")]["n"] == 1
    assert edges[("b", "c")]["n"] == 1
    assert counts == {"a": 1, "b": 2}
