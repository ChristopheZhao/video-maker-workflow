from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from video_workflow_service.media.ffmpeg_pipeline import (
    DEFAULT_SUBTITLE_FONT_NAME,
    ClipProbe,
    burn_subtitles_into_video,
    compose_clips,
)


class FfmpegPipelineTestCase(unittest.TestCase):
    def test_burn_subtitles_into_video_uses_bundled_cjk_font(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            video_path = root / "final.mp4"
            subtitle_path = root / "final.srt"
            output_path = root / "final_burned.mp4"
            font_path = root / "fonts" / "NotoSansSC-Regular.otf"
            font_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"video")
            subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n他终于看见了真正的草原。\n", encoding="utf-8")
            font_path.write_bytes(b"font")
            captured_commands: list[list[str]] = []

            with patch(
                "video_workflow_service.media.ffmpeg_pipeline.run_ffmpeg",
                side_effect=lambda cmd: captured_commands.append(cmd),
            ):
                burn_subtitles_into_video(
                    ffmpeg_bin="ffmpeg",
                    video_path=video_path,
                    subtitle_path=subtitle_path,
                    output_path=output_path,
                    font_path=font_path,
                )

            self.assertEqual(len(captured_commands), 1)
            command = captured_commands[0]
            self.assertIn("-vf", command)
            filter_expr = command[command.index("-vf") + 1]
            self.assertIn("fontsdir=", filter_expr)
            self.assertIn(f"Fontname={DEFAULT_SUBTITLE_FONT_NAME}", filter_expr)
            self.assertIn("MarginV=28", filter_expr)

    def test_compose_clips_uses_smoothed_filtergraph_when_supported(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            clip_paths = [root / "scene-01.mp4", root / "scene-02.mp4"]
            for clip_path in clip_paths:
                clip_path.write_bytes(b"clip")
            captured_commands: list[list[str]] = []

            with patch(
                "video_workflow_service.media.ffmpeg_pipeline.probe_clip",
                side_effect=[
                    ClipProbe(duration_seconds=9.0, has_video=True, has_audio=True),
                    ClipProbe(duration_seconds=8.0, has_video=True, has_audio=True),
                ],
            ), patch(
                "video_workflow_service.media.ffmpeg_pipeline.run_ffmpeg",
                side_effect=lambda cmd: captured_commands.append(cmd),
            ):
                metadata = compose_clips(
                    ffmpeg_bin="ffmpeg",
                    ffprobe_bin="ffprobe",
                    clip_paths=clip_paths,
                    concat_list_path=root / "concat.txt",
                    output_path=root / "final.mp4",
                )

            self.assertEqual(metadata["mode"], "smoothed")
            self.assertTrue(metadata["audio_crossfade_applied"])
            self.assertEqual(len(captured_commands), 1)
            command = captured_commands[0]
            self.assertIn("-filter_complex", command)
            filter_complex = command[command.index("-filter_complex") + 1]
            self.assertIn("xfade=transition=fade", filter_complex)
            self.assertIn("acrossfade=", filter_complex)
            self.assertEqual(command[0], "ffmpeg")

    def test_compose_clips_falls_back_to_concat_when_boundary_is_too_short(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            clip_paths = [root / "scene-01.mp4", root / "scene-02.mp4"]
            for clip_path in clip_paths:
                clip_path.write_bytes(b"clip")
            captured_commands: list[list[str]] = []

            with patch(
                "video_workflow_service.media.ffmpeg_pipeline.probe_clip",
                side_effect=[
                    ClipProbe(duration_seconds=0.25, has_video=True, has_audio=True),
                    ClipProbe(duration_seconds=0.25, has_video=True, has_audio=True),
                ],
            ), patch(
                "video_workflow_service.media.ffmpeg_pipeline.run_ffmpeg",
                side_effect=lambda cmd: captured_commands.append(cmd),
            ):
                metadata = compose_clips(
                    ffmpeg_bin="ffmpeg",
                    ffprobe_bin="ffprobe",
                    clip_paths=clip_paths,
                    concat_list_path=root / "concat.txt",
                    output_path=root / "final.mp4",
                )

            self.assertEqual(metadata["mode"], "concat")
            self.assertTrue(str(metadata["fallback_reason"]).startswith("clip_too_short"))
            self.assertEqual(captured_commands[0][0:5], ["ffmpeg", "-y", "-f", "concat", "-safe"])
            concat_text = (root / "concat.txt").read_text(encoding="utf-8")
            self.assertIn("scene-01.mp4", concat_text)
            self.assertIn("scene-02.mp4", concat_text)

    def test_compose_clips_falls_back_to_concat_when_smoothing_command_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            clip_paths = [root / "scene-01.mp4", root / "scene-02.mp4"]
            for clip_path in clip_paths:
                clip_path.write_bytes(b"clip")
            captured_commands: list[list[str]] = []

            def capture_or_fail(cmd: list[str]) -> None:
                captured_commands.append(cmd)
                if "-filter_complex" in cmd:
                    raise RuntimeError("xfade failed")

            with patch(
                "video_workflow_service.media.ffmpeg_pipeline.probe_clip",
                side_effect=[
                    ClipProbe(duration_seconds=9.0, has_video=True, has_audio=False),
                    ClipProbe(duration_seconds=8.0, has_video=True, has_audio=False),
                ],
            ), patch(
                "video_workflow_service.media.ffmpeg_pipeline.run_ffmpeg",
                side_effect=capture_or_fail,
            ):
                metadata = compose_clips(
                    ffmpeg_bin="ffmpeg",
                    ffprobe_bin="ffprobe",
                    clip_paths=clip_paths,
                    concat_list_path=root / "concat.txt",
                    output_path=root / "final.mp4",
                )

            self.assertEqual(metadata["mode"], "concat")
            self.assertEqual(metadata["fallback_reason"], "smoothing_failed")
            self.assertIn("xfade failed", str(metadata["smoothing_error"]))
            self.assertGreaterEqual(len(captured_commands), 2)
            self.assertIn("-filter_complex", captured_commands[0])
            self.assertEqual(captured_commands[1][0:5], ["ffmpeg", "-y", "-f", "concat", "-safe"])


if __name__ == "__main__":
    unittest.main()
