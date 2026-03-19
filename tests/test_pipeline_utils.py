import unittest

from pipeline.utils import ClipEntry, ClipsManifest, dataclass_to_dict, validate_clips_manifest


class ValidateClipsManifestTests(unittest.TestCase):
    def test_accepts_manifest_without_srt_path(self):
        manifest = validate_clips_manifest(
            {
                "source_video": "source.mp4",
                "clips": [
                    {
                        "clip_id": "clip01",
                        "start": 0,
                        "end": 5,
                        "path": "clips/clip01.mp4",
                    }
                ],
            }
        )

        self.assertIsNone(manifest.clips[0].srt_path)


    def test_dataclass_to_dict_omits_empty_srt_path(self):
        manifest_dict = dataclass_to_dict(
            ClipsManifest(
                source_video="source.mp4",
                clips=[
                    ClipEntry(
                        clip_id="clip01",
                        start=0,
                        end=5,
                        path="clips/clip01.mp4",
                    )
                ],
            )
        )

        self.assertNotIn("srt_path", manifest_dict["clips"][0])

    def test_accepts_manifest_with_srt_path(self):
        manifest = validate_clips_manifest(
            {
                "source_video": "source.mp4",
                "clips": [
                    {
                        "clip_id": "clip01",
                        "start": 0,
                        "end": 5,
                        "path": "clips/clip01.mp4",
                        "srt_path": "subtitles/clip01.srt",
                    }
                ],
            }
        )

        self.assertEqual(manifest.clips[0].srt_path, "subtitles/clip01.srt")


if __name__ == "__main__":
    unittest.main()
