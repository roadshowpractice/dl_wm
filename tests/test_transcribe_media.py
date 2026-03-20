import importlib.util
import tempfile
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("transcribe_media", Path("bin/transcribe_media.py"))
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TranscribeMediaTests(unittest.TestCase):
    def test_srt_rows_from_segments_prefers_word_timestamps(self):
        segments = [
            {
                "start": 0.0,
                "end": 2.0,
                "text": " Hello there friend",
                "words": [
                    {"word": " Hello", "start": 0.0, "end": 0.3},
                    {"word": " there", "start": 0.35, "end": 0.8},
                    {"word": " friend", "start": 1.4, "end": 1.9},
                ],
            }
        ]

        rows = MODULE.srt_rows_from_segments(segments)

        self.assertEqual(
            rows,
            [
                {"start": 0.0, "end": 0.8, "text": "Hello there"},
                {"start": 1.4, "end": 1.9, "text": "friend"},
            ],
        )

    def test_write_srt_uses_fine_grained_word_timings(self):
        segments = [
            {
                "start": 0.0,
                "end": 2.0,
                "text": " Hello there friend",
                "words": [
                    {"word": " Hello", "start": 0.0, "end": 0.3},
                    {"word": " there", "start": 0.35, "end": 0.8},
                    {"word": " friend", "start": 1.4, "end": 1.9},
                ],
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            srt_path = Path(tmp) / "clip.srt"
            MODULE.write_srt(segments, srt_path)

            self.assertEqual(
                srt_path.read_text(encoding="utf-8"),
                "1\n00:00:00,000 --> 00:00:00,800\nHello there\n\n2\n00:00:01,400 --> 00:00:01,900\nfriend\n\n",
            )


if __name__ == "__main__":
    unittest.main()
