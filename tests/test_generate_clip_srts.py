import importlib.util
import tempfile
import textwrap
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("generate_clip_srts", Path("bin/generate_clip_srts.py"))
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GenerateClipSrtsTests(unittest.TestCase):
    def test_load_transcript_srt_parses_multiline_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = Path(tmp) / "input.srt"
            srt_path.write_text(
                textwrap.dedent(
                    """
                    1
                    00:00:01,000 --> 00:00:03,500
                    First line
                    Second line

                    2
                    00:00:05,000 --> 00:00:06,000
                    Another subtitle
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            segments = MODULE.load_transcript_srt(srt_path)

            self.assertEqual(
                segments,
                [
                    {"start": 1.0, "end": 3.5, "text": "First line\nSecond line"},
                    {"start": 5.0, "end": 6.0, "text": "Another subtitle"},
                ],
            )

    def test_srt_segments_are_trimmed_relative_to_each_clip(self):
        segments = [
            {"start": 9.0, "end": 11.5, "text": "Before and into clip one"},
            {"start": 12.0, "end": 13.0, "text": "Clip one only"},
            {"start": 16.0, "end": 17.5, "text": "Clip two only"},
        ]

        clip_one = MODULE.segments_for_clip(segments, 10.0, 14.0)
        clip_two = MODULE.segments_for_clip(segments, 15.0, 18.0)

        self.assertEqual(
            clip_one,
            [
                {"start": 0.0, "end": 1.5, "text": "Before and into clip one"},
                {"start": 2.0, "end": 3.0, "text": "Clip one only"},
            ],
        )
        self.assertEqual(
            clip_two,
            [
                {"start": 1.0, "end": 2.5, "text": "Clip two only"},
            ],
        )

    def test_write_srt_outputs_expected_relative_timestamps(self):
        rows = [
            {"start": 0.0, "end": 1.5, "text": "Before and into clip one"},
            {"start": 2.0, "end": 3.0, "text": "Clip one only"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            srt_path = Path(tmp) / "clip-1.srt"
            MODULE.write_srt(srt_path, rows)

            self.assertEqual(
                srt_path.read_text(encoding="utf-8"),
                textwrap.dedent(
                    """
                    1
                    00:00:00,000 --> 00:00:01,500
                    Before and into clip one

                    2
                    00:00:02,000 --> 00:00:03,000
                    Clip one only

                    """
                ).lstrip(),
            )


if __name__ == "__main__":
    unittest.main()
