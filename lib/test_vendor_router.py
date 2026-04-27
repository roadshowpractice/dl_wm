import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from vendor_router import canonicalize_vendor_url, detect_vendor, extract_vendor_id, format_shortcode, infer_kind


class VendorRouterTests(unittest.TestCase):
    def test_detect_instagram_vendor(self):
        self.assertEqual(detect_vendor("https://www.instagram.com/reel/ABC123/"), "instagram")
        self.assertEqual(detect_vendor("https://www.instagram.com/reels/C_YIrCJJGJj/"), "instagram")
        self.assertEqual(detect_vendor("https://www.instagram.com/p/XYZ99/?utm_source=ig_web_copy_link"), "instagram")

    def test_extract_instagram_shortcode(self):
        self.assertEqual(
            extract_vendor_id("instagram", "https://www.instagram.com/reel/C8abcDEF12_/"),
            "C8abcDEF12_",
        )
        self.assertEqual(
            extract_vendor_id("instagram", "https://www.instagram.com/reels/C_YIrCJJGJj/"),
            "C_YIrCJJGJj",
        )
        self.assertEqual(
            extract_vendor_id("instagram", "https://www.instagram.com/p/POSTCODE1/?img_index=1"),
            "POSTCODE1",
        )

    def test_infer_kind_instagram_reels_alias(self):
        self.assertEqual(infer_kind("instagram", "https://www.instagram.com/reels/C_YIrCJJGJj/"), "reel")


    def test_format_shortcode_prefixes_vendor(self):
        self.assertEqual(format_shortcode("instagram", "DU8aARCADM0"), "instagram__DU8aARCADM0")

    def test_format_shortcode_idempotent(self):
        self.assertEqual(
            format_shortcode("instagram", "instagram__DU8aARCADM0"),
            "instagram__DU8aARCADM0",
        )

    def test_detect_youtube_vendor(self):
        self.assertEqual(detect_vendor("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "youtube")
        self.assertEqual(detect_vendor("https://youtu.be/dQw4w9WgXcQ"), "youtube")
        self.assertEqual(detect_vendor("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "youtube")
        self.assertEqual(detect_vendor("https://www.youtube.com/live/feFGLbMvuc4"), "youtube")
        self.assertEqual(detect_vendor("https://youtube.com/live/feFGLbMvuc4"), "youtube")
        self.assertEqual(detect_vendor("https://m.youtube.com/live/feFGLbMvuc4"), "youtube")
        self.assertEqual(detect_vendor("https://www.youtube.com/live/feFGLbMvuc4?si=abc123"), "youtube")
        self.assertEqual(detect_vendor("https://www.youtube.com/live/feFGLbMvuc4?t=120"), "youtube")

    def test_detect_facebook_vendor(self):
        self.assertEqual(detect_vendor("https://www.facebook.com/reel/123456789012345/"), "facebook")
        self.assertEqual(detect_vendor("https://www.facebook.com/share/r/1AvwZSWP68/"), "facebook")
        self.assertEqual(detect_vendor("https://www.facebook.com/share/v/19G7Jx2x2n/"), "facebook")
        self.assertEqual(detect_vendor("https://fb.watch/xyzAbcD/"), "facebook")

    def test_extract_facebook_id(self):
        self.assertEqual(
            extract_vendor_id("facebook", "https://www.facebook.com/reel/123456789012345/"),
            "123456789012345",
        )
        self.assertEqual(
            extract_vendor_id("facebook", "https://www.facebook.com/watch/?v=998877665544332"),
            "998877665544332",
        )
        self.assertEqual(
            extract_vendor_id("facebook", "https://www.facebook.com/share/r/1AvwZSWP68/"),
            "1AvwZSWP68",
        )
        self.assertEqual(
            extract_vendor_id("facebook", "https://www.facebook.com/share/v/19G7Jx2x2n/"),
            "19G7Jx2x2n",
        )

    def test_infer_kind_facebook(self):
        self.assertEqual(infer_kind("facebook", "https://www.facebook.com/reel/123456789012345/"), "reel")
        self.assertEqual(infer_kind("facebook", "https://www.facebook.com/share/r/1AvwZSWP68/"), "reel")
        self.assertEqual(infer_kind("facebook", "https://www.facebook.com/watch/?v=998877665544332"), "video")


    def test_canonicalize_youtube_shorts_url(self):
        self.assertEqual(
            canonicalize_vendor_url("youtube", "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share"),
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

    def test_canonicalize_youtube_live_url(self):
        self.assertEqual(
            canonicalize_vendor_url("youtube", "https://www.youtube.com/live/feFGLbMvuc4"),
            "https://www.youtube.com/watch?v=feFGLbMvuc4",
        )
        self.assertEqual(
            canonicalize_vendor_url("youtube", "https://youtube.com/live/feFGLbMvuc4"),
            "https://www.youtube.com/watch?v=feFGLbMvuc4",
        )
        self.assertEqual(
            canonicalize_vendor_url("youtube", "https://m.youtube.com/live/feFGLbMvuc4"),
            "https://www.youtube.com/watch?v=feFGLbMvuc4",
        )
        self.assertEqual(
            canonicalize_vendor_url("youtube", "https://www.youtube.com/live/feFGLbMvuc4?si=abc123"),
            "https://www.youtube.com/watch?v=feFGLbMvuc4",
        )
        self.assertEqual(
            canonicalize_vendor_url("youtube", "https://www.youtube.com/live/feFGLbMvuc4?t=120"),
            "https://www.youtube.com/watch?v=feFGLbMvuc4",
        )

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
        self.assertEqual(
            extract_vendor_id("youtube", "https://www.youtube.com/live/feFGLbMvuc4?t=120"),
            "feFGLbMvuc4",
        )


if __name__ == "__main__":
    unittest.main()
