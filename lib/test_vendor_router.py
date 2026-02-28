import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from vendor_router import detect_vendor, extract_vendor_id


class VendorRouterTests(unittest.TestCase):
    def test_detect_instagram_vendor(self):
        self.assertEqual(detect_vendor("https://www.instagram.com/reel/ABC123/"), "instagram")
        self.assertEqual(detect_vendor("https://www.instagram.com/p/XYZ99/?utm_source=ig_web_copy_link"), "instagram")

    def test_extract_instagram_shortcode(self):
        self.assertEqual(
            extract_vendor_id("instagram", "https://www.instagram.com/reel/C8abcDEF12_/"),
            "C8abcDEF12_",
        )
        self.assertEqual(
            extract_vendor_id("instagram", "https://www.instagram.com/p/POSTCODE1/?img_index=1"),
            "POSTCODE1",
        )

    def test_detect_youtube_vendor(self):
        self.assertEqual(detect_vendor("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "youtube")
        self.assertEqual(detect_vendor("https://youtu.be/dQw4w9WgXcQ"), "youtube")
        self.assertEqual(detect_vendor("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "youtube")

    def test_extract_youtube_id(self):
        self.assertEqual(
            extract_vendor_id("youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=43s"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_vendor_id("youtube", "https://youtu.be/dQw4w9WgXcQ?si=abc"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_vendor_id("youtube", "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share"),
            "dQw4w9WgXcQ",
        )


if __name__ == "__main__":
    unittest.main()
