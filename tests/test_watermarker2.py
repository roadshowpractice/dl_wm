import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from dl_wm.watermarker2 import _timestamp_filter

HERE = os.path.dirname(os.path.abspath(__file__))


class WatermarkerTests(unittest.TestCase):

    def test_timestamp_uses_fixed_width_elapsed_hms_expression(self):
        filt = _timestamp_filter(
            color="red",
            font="fonts/Inter-Bold.otf",
            font_size=32,
            position=["right", "bottom"],
        )

        self.assertIn("%{eif\\:trunc(t/3600)\\:d\\:2}", filt)
        self.assertIn("%{eif\\:trunc(mod(t\\,3600)/60)\\:d\\:2}", filt)
        self.assertIn("%{eif\\:trunc(mod(t\\,60))\\:d\\:2}", filt)
        self.assertNotIn("gmtime", filt)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not available")
    def test_timestamp_filter_runs_in_ffmpeg(self):
        filt = _timestamp_filter(
            color="red",
            font=os.path.join(os.path.dirname(HERE), "fonts", "Inter-Bold.otf"),
            font_size=16,
            position=["right", "bottom"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "in.mp4")
            out_path = os.path.join(tmpdir, "out.mp4")

            make_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=160x120:rate=24:duration=2.2",
                "-pix_fmt",
                "yuv420p",
                in_path,
            ]
            make_res = subprocess.run(make_cmd, capture_output=True, text=True)
            self.assertEqual(
                0,
                make_res.returncode,
                msg=f"ffmpeg synthetic clip generation failed:\n{make_res.stderr}",
            )

            run_cmd = [
                "ffmpeg",
                "-y",
                "-i",
                in_path,
                "-vf",
                filt,
                "-an",
                out_path,
            ]
            run_res = subprocess.run(run_cmd, capture_output=True, text=True)

            self.assertEqual(
                0,
                run_res.returncode,
                msg=f"ffmpeg watermark run failed:\n{run_res.stderr}",
            )
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)


if __name__ == "__main__":
    unittest.main()
