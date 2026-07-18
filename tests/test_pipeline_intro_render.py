import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import render as render_module
from pipeline.intro import _resolve_output_dimensions, render_intro_manifest
from pipeline.render import prepare_make_final_film_inputs
from pipeline.utils import (
    ClipEntry,
    ClipsManifest,
    RenderSettings,
    dataclass_to_dict,
    normalized_anullsrc,
    normalized_audio_codec_args,
    normalized_concat_audio_filter,
    normalized_video_codec_args,
)


REPO_FONT_PATH = Path(__file__).resolve().parents[1] / "fonts" / "Inter-Bold.otf"


def assert_has_subsequence(testcase: unittest.TestCase, cmd: list[str], expected: list[str]) -> None:
    for idx in range(0, len(cmd) - len(expected) + 1):
        if cmd[idx : idx + len(expected)] == expected:
            return
    testcase.fail(f"Expected subsequence {expected!r} in command {cmd!r}")


def read_png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG file: {path}")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class IntroStageTests(unittest.TestCase):
    def test_resolve_output_dimensions_prioritizes_cli_then_manifest_then_probe(self):
        manifest = ClipsManifest(source_video="source.mp4", clips=[])
        self.assertEqual(_resolve_output_dimensions(manifest, width=360, height=640), (360, 640))

        manifest_with_render = ClipsManifest(
            source_video="source.mp4",
            clips=[],
            render=RenderSettings(width=480, height=854),
        )
        self.assertEqual(_resolve_output_dimensions(manifest_with_render, width=None, height=None), (480, 854))

    def test_render_intro_manifest_advances_path_and_preserves_srt_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            source_clip = tmpdir / "subbed" / "clip01.mp4"
            source_clip.parent.mkdir(parents=True, exist_ok=True)
            source_clip.write_bytes(b"clip")

            font_path = REPO_FONT_PATH

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

            with patch("pipeline.intro.probe_video_dimensions", return_value=(1920, 1080)), patch(
                "pipeline.intro.run_cmd", side_effect=fake_run
            ):
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
            self.assertTrue((tmpdir / "intro" / "clip01.card.png").exists())
            self.assertTrue((tmpdir / "intro" / "clip01.mp4").exists())
            self.assertIn(
                "file 'clip01.normalized.mp4'",
                (tmpdir / "intro" / "clip01__concat.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(read_png_dimensions(tmpdir / "intro" / "clip01.card.png"), (1920, 1080))

    def test_render_intro_manifest_normalizes_audio_for_card_black_and_concat(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            source_clip = tmpdir / "subbed" / "clip01.mp4"
            source_clip.parent.mkdir(parents=True, exist_ok=True)
            source_clip.write_bytes(b"clip")

            font_path = REPO_FONT_PATH

            manifest = ClipsManifest(
                source_video="source.mp4",
                clips=[ClipEntry(clip_id="clip01", start=0.0, end=5.0, path=str(source_clip), comment="Break")],
            )

            commands: list[list[str]] = []

            def fake_run(cmd: list[str]) -> None:
                commands.append(cmd)
                Path(cmd[-1]).write_bytes(b"video")

            with patch("pipeline.intro.probe_video_dimensions", return_value=(1920, 1080)), patch(
                "pipeline.intro.run_cmd", side_effect=fake_run
            ):
                render_intro_manifest(
                    manifest,
                    output_dir=tmpdir / "intro",
                    font=font_path,
                    intro_seconds=2.0,
                    black_seconds=1.0,
                )

            self.assertEqual(len(commands), 4)
            normalize_cmd, card_cmd, black_cmd, concat_cmd = commands
            self.assertIn(
                "scale=1920:1080:force_original_aspect_ratio=decrease",
                " ".join(normalize_cmd),
            )
            assert_has_subsequence(self, card_cmd, ["-loop", "1"])
            self.assertNotIn("drawtext", " ".join(card_cmd))
            self.assertIn(normalized_anullsrc(), card_cmd)
            self.assertIn(normalized_anullsrc(), black_cmd)
            assert_has_subsequence(self, card_cmd, normalized_video_codec_args(fps=30))
            assert_has_subsequence(self, card_cmd, normalized_audio_codec_args())
            assert_has_subsequence(self, black_cmd, normalized_video_codec_args(fps=30))
            assert_has_subsequence(self, black_cmd, normalized_audio_codec_args())
            assert_has_subsequence(self, concat_cmd, normalized_video_codec_args(fps=30))
            assert_has_subsequence(self, concat_cmd, normalized_audio_codec_args())
            assert_has_subsequence(self, concat_cmd, ["-af", normalized_concat_audio_filter()])


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

    def test_render_main_normalizes_title_clip_and_final_concat_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            title_image = tmpdir / "monarch.png"
            title_image.write_bytes(b"image")
            segment = tmpdir / "intro" / "clip01.mp4"
            segment.parent.mkdir(parents=True, exist_ok=True)
            segment.write_bytes(b"clip")
            manifest_path = tmpdir / "final_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "title_image": str(title_image),
                        "title_seconds": 2.0,
                        "segments": [{"order": 1, "clip_id": "clip01", "path": str(segment), "comment": "first"}],
                        "render": dataclass_to_dict(RenderSettings()),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            commands: list[list[str]] = []

            def fake_run(cmd: list[str]) -> None:
                commands.append(cmd)
                Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
                Path(cmd[-1]).write_bytes(b"video")

            argv = [
                "pipeline.render",
                "--manifest",
                str(manifest_path),
                "--output",
                str(tmpdir / "final.mp4"),
                "--black-seconds",
                "1.0",
                "--work-dir",
                str(tmpdir / ".tmp"),
            ]

            with patch("pipeline.render.ensure_ffmpeg"), patch("pipeline.render.run_cmd", side_effect=fake_run), patch(
                "sys.argv", argv
            ):
                render_module.main()

            self.assertEqual(len(commands), 4)
            title_cmd, black_cmd, normalize_cmd, concat_cmd = commands
            self.assertIn(normalized_anullsrc(), title_cmd)
            self.assertIn(normalized_anullsrc(), black_cmd)
            assert_has_subsequence(self, title_cmd, normalized_video_codec_args(fps=30, crf=18))
            assert_has_subsequence(self, title_cmd, normalized_audio_codec_args())
            assert_has_subsequence(self, black_cmd, normalized_video_codec_args(fps=30))
            self.assertIn(
                "scale=1920:1080:force_original_aspect_ratio=decrease",
                " ".join(normalize_cmd),
            )
            assert_has_subsequence(self, black_cmd, normalized_audio_codec_args())
            assert_has_subsequence(self, concat_cmd, normalized_video_codec_args(fps=30, crf=18))
            assert_has_subsequence(self, concat_cmd, normalized_audio_codec_args())
            assert_has_subsequence(self, concat_cmd, ["-af", normalized_concat_audio_filter()])


class FfmpegNormalizationHelperTests(unittest.TestCase):
    def test_normalization_helpers_lock_required_audio_video_invariants(self):
        self.assertEqual(normalized_anullsrc(), "anullsrc=r=48000:cl=stereo")
        self.assertEqual(normalized_audio_codec_args(), ["-c:a", "aac", "-ar", "48000", "-ac", "2"])
        self.assertEqual(
            normalized_video_codec_args(fps=30, crf=18),
            ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30"],
        )
        self.assertEqual(normalized_concat_audio_filter(), "aresample=48000,aresample=async=1")


if __name__ == "__main__":
    unittest.main()
