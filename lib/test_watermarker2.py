import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from watermarker2 import _timestamp_filter


class WatermarkerTests(unittest.TestCase):

    def test_timestamp_uses_fixed_width_seconds_format(self):
        filt = _timestamp_filter(
            color="red",
            font="fonts/Inter-Bold.otf",
            font_size=32,
            position=["right", "bottom"],
        )

        self.assertIn("%H\\\\:%M\\\\:%S", filt)
        self.assertNotIn("%{pts\\:hms}", filt)


if __name__ == "__main__":
    unittest.main()
