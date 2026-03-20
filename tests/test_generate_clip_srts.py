import importlib.util
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("generate_clip_srts", Path("bin/generate_clip_srts.py"))
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GenerateClipSrtsTests(unittest.TestCase):
    def test_build_timing_entries_from_json_prefers_word_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript_path = Path(tmp) / "input.whisper.json"
            transcript_path.write_text(
                json.dumps(
                    {
                        "segments": [
                            {
                                "start": 1.0,
                                "end": 2.0,
                                "text": " Hello world",
                                "words": [
                                    {"word": " Hello", "start": 1.0, "end": 1.4},
                                    {"word": " world", "start": 1.45, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            source, entries = MODULE.build_timing_entries_from_json(transcript_path)

            self.assertEqual(source, "word_timestamps")
            self.assertEqual(
                entries,
                [
                    {"start": 1.0, "end": 1.4, "text": " Hello"},
                    {"start": 1.45, "end": 2.0, "text": " world"},
                ],
            )

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

    def test_word_rows_for_clip_keep_native_word_timing(self):
        words = [
            {"start": 10.0, "end": 10.3, "text": " Hello"},
            {"start": 10.35, "end": 10.8, "text": " there"},
            {"start": 11.7, "end": 12.0, "text": " friend"},
        ]

        rows = MODULE.word_rows_for_clip(words, 10.0, 12.0)

        self.assertEqual(
            rows,
            [
                {"start": 0.0, "end": 0.8, "text": "Hello there"},
                {"start": 1.7, "end": 2.0, "text": "friend"},
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

    def test_parse_args_accepts_single_clip_interface(self):
        with patch("sys.argv", ["generate_clip_srts.py", "--clip-path", "clip.mp4", "--output", "clip.srt"]):
            args = MODULE.parse_args()

        self.assertEqual(args.clip_path, "clip.mp4")
        self.assertEqual(args.output, "clip.srt")

    def test_generate_single_clip_srt_supports_clip_path_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip_path = Path(tmp) / "clip01.mp4"
            clip_path.write_bytes(b"video")
            output_path = Path(tmp) / "nested" / "custom-name.srt"

            def fake_run_transcription(input_path: str, requested_output_path: str, output_format: str) -> bool:
                self.assertEqual(input_path, str(clip_path))
                self.assertEqual(output_format, "srt")
                generated = Path(requested_output_path).parent / f"{clip_path.stem}.srt"
                generated.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
                return True

            with patch.object(MODULE, "run_transcription_for_clip", side_effect=lambda clip, output: fake_run_transcription(str(clip), str(output), "srt")):
                written_path = MODULE.generate_single_clip_srt(clip_path, output_path)

            self.assertEqual(written_path, output_path)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
            )


if __name__ == "__main__":
    unittest.main()
