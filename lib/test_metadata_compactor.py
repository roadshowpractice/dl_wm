import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from metadata_compactor import build_compact_metadata


class MetadataCompactorTests(unittest.TestCase):

    def test_build_compact_metadata_sets_vendor_fields_and_tasks(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            downloaded_path = tmp.name

        try:
            info = {
                "id": "XqZsoesa55w",
                "title": "Baby Shark",
                "upload_date": "20240220",
                "uploader": "Pinkfong",
                "duration": 136,
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "ext": "mp4",
                "filesize": 123456,
                "view_count": 100,
                "like_count": 10,
                "comment_count": 1,
            }

            compact = build_compact_metadata(
                info,
                url="https://www.youtube.com/watch?v=XqZsoesa55w",
                vendor="youtube",
                vendor_id="XqZsoesa55w",
                downloaded_path=downloaded_path,
            )

            self.assertEqual(compact["vendor"], "youtube")
            self.assertEqual(compact["vendor_id"], "XqZsoesa55w")
            self.assertEqual(compact["id"], "XqZsoesa55w")
            self.assertIsNone(compact["shortcode"])
            self.assertEqual(compact["video_title"], "Baby Shark")
            self.assertEqual(compact["video_date"], "20240220")
            self.assertEqual(compact["default_tasks"]["perform_download"], downloaded_path)
        finally:
            os.unlink(downloaded_path)

    def test_instagram_shortcode_is_set(self):
        compact = build_compact_metadata(
            {},
            url="https://www.instagram.com/reel/ABC123/",
            vendor="instagram",
            vendor_id="ABC123",
            downloaded_path="/tmp/does-not-exist.mp4",
        )
        self.assertEqual(compact["shortcode"], "ABC123")


if __name__ == "__main__":
    unittest.main()
