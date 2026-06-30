import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import types

if "yt_dlp" not in sys.modules:
    sys.modules["yt_dlp"] = types.ModuleType("yt_dlp")

import dl_wm.transcription_caller as transcription_caller


class TranscriptionCallerTests(unittest.TestCase):
    def test_build_transcribe_media_command_for_srt_uses_canonical_args(self):
        cmd, generated = transcription_caller._build_transcribe_media_command(
            python_bin="python3",
            script_path="bin/transcribe_media.py",
            input_path="/tmp/input/video.mp4",
            output_path="/tmp/output/requested.srt",
            output_format="srt",
            app_config={},
        )

        self.assertEqual(
            cmd,
            [
                "python3",
                "bin/transcribe_media.py",
                "/tmp/input/video.mp4",
                "--outdir",
                "/tmp/output",
                "--srt",
                "--no-txt",
            ],
        )
        self.assertNotIn("--input", cmd)
        self.assertNotIn("--output", cmd)
        self.assertEqual(generated, "/tmp/output/video.srt")

    def test_auto_transcribe_validates_generated_srt_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, "clip.mp4")
            outdir = os.path.join(tmp, "out")
            os.makedirs(outdir, exist_ok=True)
            output_path = os.path.join(outdir, "requested-name.srt")
            expected_srt = os.path.join(outdir, "clip.srt")
            open(input_path, "w", encoding="utf-8").close()

            captured = {}

            def fake_run_and_validate(cmd, output_file):
                captured["cmd"] = cmd
                captured["output_file"] = output_file
                open(output_file, "w", encoding="utf-8").close()
                return True

            with patch("dl_wm.transcription_caller.os.path.isfile", return_value=True), patch(
                "dl_wm.transcription_caller._python_executable", return_value="python3"
            ), patch("dl_wm.transcription_caller._run_and_validate", side_effect=fake_run_and_validate):
                ok = transcription_caller._auto_transcribe_with_local_script(
                    input_path=input_path,
                    output_path=output_path,
                    output_format="srt",
                    app_config={},
                )

            self.assertTrue(ok)
            self.assertEqual(captured["output_file"], expected_srt)
            self.assertIn(input_path, captured["cmd"])
            self.assertIn("--outdir", captured["cmd"])
            self.assertNotIn("--input", captured["cmd"])
            self.assertNotIn("--output", captured["cmd"])
            self.assertTrue(os.path.exists(expected_srt))


if __name__ == "__main__":
    unittest.main()
