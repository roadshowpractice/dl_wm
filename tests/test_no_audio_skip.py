import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from transcription_caller import has_audio_stream  # noqa: E402


def _make(path, with_audio):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=f=440:d=1", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


@pytest.mark.parametrize("with_audio", [True, False])
def test_has_audio_stream(tmp_path, with_audio):
    clip = tmp_path / "clip.mp4"
    _make(clip, with_audio)
    assert has_audio_stream(str(clip)) is with_audio


def test_has_audio_stream_unreadable_is_none(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video")
    assert has_audio_stream(str(bad)) is None
