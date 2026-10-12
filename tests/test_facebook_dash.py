"""downloaders/facebook_dash.py: the page-read fallback for Facebook reels yt-dlp can't parse.

Synthetic pages only (shaped like the real 2026-10-12 capture of Mortensen's reel 1645607447070005);
no network, no real page data in the repo.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

from downloaders import facebook, facebook_dash as fd  # noqa: E402

VID = "1645607447070005"
OTHER = "1103154808856573"


def _reps(video_id, sizes, audio=True):
    reps = [{"representation_id": f"{h}v", "mime_type": "video/mp4", "width": w, "height": h, "bandwidth": w * h,
             "base_url": f"https://video.example/{video_id}_{h}.mp4"} for w, h in sizes]
    if audio:
        reps.append({"representation_id": "a", "mime_type": "audio/mp4", "width": 0, "height": 0, "bandwidth": 55382,
                     "base_url": f"https://video.example/{video_id}_audio.mp4"})
    return {"video_id": video_id, "representations": reps}


def _page():
    ext = {"all_video_dash_prefetch_representations": [
        _reps(VID, [(1080, 1920), (360, 640), (540, 960), (720, 1280)]),
        _reps(OTHER, [(1440, 2560), (1080, 1920)]),
    ]}
    target_post = {"creation_time": 1791738450, "actors": [{"__typename": "User", "id": "1390345364", "name": "Alan W. Mortensen"}],
                   "message": {"text": "Last night, Tim Ballard responded publicly..."},
                   "attachments": [{"media": {"__typename": "Video", "id": VID, "length_in_second": 275.833}}]}
    other_post = {"creation_time": 1790953976, "actors": [{"name": "Someone Else"}], "message": {"text": "zoomies"},
                  "attachments": [{"media": {"__typename": "Video", "id": OTHER, "length_in_second": 17.749}}]}
    wrapper = {"require": [{"feed": [other_post, {"story": target_post}]}], "extensions": ext}
    return ('<html><script type="application/json" data-sjs>' + json.dumps(wrapper, separators=(",", ":"))
            + "</script></html>")


def test_streams_only_for_our_video():
    videos, audios = fd.find_streams([_page()], VID)
    assert len(videos) == 4 and len(audios) == 1
    assert all(VID in v["base_url"] for v in videos)


def test_pick_caps_short_side_at_1080():
    videos, audios = fd.find_streams([_page()], VID)
    v, a = fd.pick_streams(videos, audios)
    assert (v["width"], v["height"]) == (1080, 1920)
    assert a["mime_type"] == "audio/mp4"
    big, _ = fd.find_streams([_page()], OTHER)
    v2, _ = fd.pick_streams(big, [])
    assert (v2["width"], v2["height"]) == (1080, 1920)  # 1440x2560 is over the cap


def test_post_info_is_the_post_that_carries_the_video():
    info = fd.find_post_info([_page()], VID)
    assert info["timestamp"] == 1791738450
    assert info["uploader"] == "Alan W. Mortensen"
    assert info["description"].startswith("Last night")
    assert info["duration"] == 275.833


def test_no_streams_raises():
    try:
        fd.download(f"https://www.facebook.com/reel/999/", "/tmp/_fbdash_test_out", "/tmp/_fbdash_test_meta", {}, None,
                    bodies=["<html>nothing here</html>"])
    except fd.NoStreamsFound:
        return
    raise AssertionError("expected NoStreamsFound")


def test_facebook_download_falls_back_only_on_cannot_parse(monkeypatch, tmp_path):
    import yt_dlp

    calls = []

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            raise yt_dlp.utils.DownloadError(FakeYDL.msg)

    monkeypatch.setattr(facebook.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(fd, "download", lambda *a, **k: calls.append(a) or {"to_process": "x"})
    FakeYDL.msg = "ERROR: [facebook] 1645607447070005: Cannot parse data; please report this issue"
    out = facebook.download(f"https://www.facebook.com/reel/{VID}/", str(tmp_path), str(tmp_path), {}, None)
    assert out == {"to_process": "x"} and len(calls) == 1

    FakeYDL.msg = "ERROR: [facebook] 1645607447070005: This video is only available for registered users"
    try:
        facebook.download(f"https://www.facebook.com/reel/{VID}/", str(tmp_path), str(tmp_path), {}, None)
    except yt_dlp.utils.DownloadError:
        assert len(calls) == 1
        return
    raise AssertionError("other yt-dlp errors must not trigger the fallback")
