import importlib.util
from pathlib import Path
import sys
import types
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CALL_WATERMARK_PATH = REPO_ROOT / "bin" / "call_watermark.py"

spec = importlib.util.spec_from_file_location("call_watermark", CALL_WATERMARK_PATH)
call_watermark = importlib.util.module_from_spec(spec)
sys.modules.setdefault("yt_dlp", types.SimpleNamespace())
spec.loader.exec_module(call_watermark)


class CallWatermarkManualTests(unittest.TestCase):
    def test_parse_args_supports_legacy_and_flag_input(self):
        legacy = call_watermark._parse_args(["/tmp/in.mp4"])
        self.assertEqual(legacy.input_video, "/tmp/in.mp4")

        flagged = call_watermark._parse_args(["--input", "/tmp/a b.mp4", "--title", "name"])
        self.assertEqual(flagged.input_video, "/tmp/a b.mp4")
        self.assertEqual(flagged.title, "name")


if __name__ == "__main__":
    unittest.main()
