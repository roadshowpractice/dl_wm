import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.intro import render_intro_manifest
from pipeline.render import prepare_make_final_film_inputs
from pipeline.utils import ClipEntry, ClipsManifest, RenderSettings, dataclass_to_dict


class IntroStageTests(unittest.TestCase):
    def test_render_intro_manifest_advances_path_and_preserves_srt_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            source_clip = tmpdir / "subbed" / "clip01.mp4"
            source_clip.parent.mkdir(parents=True, exist_ok=True)
            source_clip.write_bytes(b"clip")

            font_path = tmpdir / "font.ttf"
            font_path.write_bytes(b"font")

            manifest = ClipsManifest(
                source_video="source.mp4",
                clips=[
                    ClipEntry(
                        clip_id="clip01",
                        start=0.0,
                        end=5.0,
                        path=str(source_clip),
                        comment="Break card text",
                        srt_path="subtitles/clip01.srt",
                    )
                ],
            )

            def fake_run(cmd: list[str]) -> None:
                output_path = Path(cmd[-1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"video")

            with patch("pipeline.intro.run_cmd", side_effect=fake_run):
                updated = render_intro_manifest(
                    manifest,
                    output_dir=tmpdir / "intro",
                    font=font_path,
                    intro_seconds=2.0,
                )

            clip = updated.clips[0]
            self.assertEqual(clip.path, str(tmpdir / "intro" / "clip01.mp4"))
            self.assertEqual(clip.comment, "Break card text")
            self.assertEqual(clip.srt_path, "subtitles/clip01.srt")
            self.assertTrue((tmpdir / "intro" / "clip01.card.mp4").exists())
            self.assertTrue((tmpdir / "intro" / "clip01.mp4").exists())
            self.assertIn(
                f"file '{source_clip.resolve()}'",
                (tmpdir / "intro" / "clip01__concat.txt").read_text(encoding="utf-8"),
            )


class FinalRenderPrepTests(unittest.TestCase):
    def test_prepare_make_final_film_inputs_uses_manifest_paths_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            first_clip = tmpdir / "intro" / "clip-b-current.mp4"
            second_clip = tmpdir / "intro" / "clip-a-current.mp4"
            first_clip.parent.mkdir(parents=True, exist_ok=True)
            first_clip.write_bytes(b"b")
            second_clip.write_bytes(b"a")

            manifest_path = tmpdir / "clips_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "source_video": "source.mp4",
                        "title_image": "monarch.png",
                        "title_seconds": 2.0,
                        "render": dataclass_to_dict(RenderSettings()),
                        "clips": [
                            {
                                "clip_id": "clip-b",
                                "start": 0,
                                "end": 4,
                                "path": str(first_clip),
                                "comment": "first",
                            },
                            {
                                "clip_id": "clip-a",
                                "start": 5,
                                "end": 9,
                                "path": str(second_clip),
                                "comment": "second",
                            },
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            jsonl_path, clip_dir = prepare_make_final_film_inputs(
                manifest_path,
                tmpdir / "film" / "clips_for_film.jsonl",
                tmpdir / "film" / "clips",
            )

            self.assertEqual(
                jsonl_path.read_text(encoding="utf-8").splitlines(),
                ['{"clip_id": "clip-b"}', '{"clip_id": "clip-a"}'],
            )
            self.assertTrue((clip_dir / "clip-b.mp4").is_symlink())
            self.assertTrue((clip_dir / "clip-a.mp4").is_symlink())
            self.assertEqual((clip_dir / "clip-b.mp4").resolve(), first_clip.resolve())
            self.assertEqual((clip_dir / "clip-a.mp4").resolve(), second_clip.resolve())


if __name__ == "__main__":
    unittest.main()
