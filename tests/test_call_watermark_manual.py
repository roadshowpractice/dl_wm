import importlib.util
from pathlib import Path
import sys
import types
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CALL_WATERMARK_PATH = REPO_ROOT / "bin" / "call_watermark.py"

spec = importlib.util.spec_from_file_location("call_watermark", CALL_WATERMARK_PATH)
call_watermark = importlib.util.module_from_spec(spec)

# Only stub yt_dlp (a heavy, unrelated import pulled in transitively via
# teton_utils) if it isn't already the real module — and restore whatever
# was there afterward, so this doesn't leak a fake yt_dlp into sys.modules
# for the rest of the pytest session.
_had_yt_dlp = "yt_dlp" in sys.modules
if not _had_yt_dlp:
    sys.modules["yt_dlp"] = types.SimpleNamespace()
try:
    spec.loader.exec_module(call_watermark)
finally:
    if not _had_yt_dlp:
        sys.modules.pop("yt_dlp", None)


class CallWatermarkManualTests(unittest.TestCase):
    def test_build_source_label_joins_three_manual_fields(self):
        label = call_watermark._build_source_label("@some_uploader", "2026-04-26", "This is title")
        self.assertEqual(label, "@some_uploader | 2026-04-26 | This is title")

    def test_build_source_label_truncates_long_title(self):
        long_title = "x" * 500
        label = call_watermark._build_source_label("uploader", "2026-04-26", long_title, max_chars=80)
        self.assertTrue(label.endswith("…"))
        self.assertLessEqual(len(label), 80)

    def test_parse_args_supports_legacy_and_flag_input(self):
        legacy = call_watermark._parse_args(["/tmp/in.mp4"])
        self.assertEqual(legacy.input_video, "/tmp/in.mp4")

        flagged = call_watermark._parse_args(["--input", "/tmp/a b.mp4", "--title", "name"])
        self.assertEqual(flagged.input_video, "/tmp/a b.mp4")
        self.assertEqual(flagged.title, "name")


if __name__ == "__main__":
    unittest.main()
