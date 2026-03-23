from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from video_workflow_service import WorkflowService, load_settings
from video_workflow_service.domain.models import Scene, SceneVideoJob, SubtitleJob
from video_workflow_service.subtitles.service import SubtitleAlignmentResult, SubtitleCue


class WorkflowServiceTestCase(unittest.TestCase):
    def test_create_project_rejects_unsupported_provider_duration_split(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)

            with self.assertRaisesRegex(ValueError, "cannot split 35s across 2 scenes"):
                service.create_project(
                    title="Unsupported Duration Split",
                    prompt="A trailer about a wandering cat.",
                    target_duration_seconds=35,
                    provider="doubao",
                    scene_count=2,
                    workflow_mode="hitl",
                )

    def test_create_project_persists_subtitle_mode(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)

            project = service.create_project(
                title="Subtitle Mode",
                prompt="A narrated trailer about a wandering cat.",
                target_duration_seconds=12,
                provider="mock",
                scene_count=3,
                workflow_mode="hitl",
                subtitle_mode="enabled",
            )

            self.assertEqual(project.subtitle_mode, "enabled")

    def test_create_project_persists_scene1_first_frame_choice(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)

            project = service.create_project(
                title="Scene 1 Source",
                prompt="A portrait opening shot.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
                scene1_first_frame_source="upload",
                scene1_first_frame_image="data:image/png;base64,c2NlbmUx",
            )

            self.assertEqual(project.scene1_first_frame_source, "upload")
            self.assertEqual(project.scene1_first_frame_image, "data:image/png;base64,c2NlbmUx")
            self.assertEqual(project.scene1_first_frame_prompt, "")

    def test_plan_scenes_respects_scene1_initial_first_frame_setup(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Scene 1 Planning",
                prompt="A two-scene reveal.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
                scene1_first_frame_source="upload",
                scene1_first_frame_image="data:image/png;base64,c2NlbmUx",
            )

            planned = service.plan_scenes(project.project_id)

            first_scene = next(scene for scene in planned.scenes if scene.scene_id == "scene-01")
            second_scene = next(scene for scene in planned.scenes if scene.scene_id == "scene-02")
            self.assertEqual(first_scene.first_frame_source, "upload")
            self.assertEqual(first_scene.first_frame_image, "data:image/png;base64,c2NlbmUx")
            self.assertEqual(first_scene.first_frame_origin, "user_upload")
            self.assertEqual(first_scene.first_frame_status, "ready")
            self.assertTrue(first_scene.first_frame_analysis)
            self.assertEqual(
                first_scene.provider_metadata["scene_prompt_refresh"]["mode"],
                "llm_scene_prompt_render",
            )
            self.assertEqual(second_scene.first_frame_source, "continuity")
            self.assertEqual(second_scene.first_frame_origin, "previous_scene_tail")

    def test_optimize_prompt_prepares_project_scene1_first_frame_context(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Scene 1 Context",
                prompt="A woman stands indoors holding dried flowers.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
                scene1_first_frame_source="upload",
                scene1_first_frame_image="data:image/png;base64,c2NlbmUx",
            )

            optimized = service.optimize_prompt(project.project_id)

            self.assertEqual(optimized.scene1_first_frame_source, "upload")
            self.assertEqual(optimized.scene1_first_frame_origin, "user_upload")
            self.assertEqual(optimized.scene1_first_frame_status, "ready")
            self.assertTrue(optimized.scene1_first_frame_analysis)
            self.assertEqual(
                optimized.scene1_first_frame_analysis["subject_presence"],
                "The protagonist is already fully visible on screen.",
            )

    def test_optimize_prompt_detects_language_and_persists_audio_alignment(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Language Detection",
                prompt='一个古装女人站在药房里，慢慢说道：“他们都以为我只是个医娘子。”',
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )

            optimized = service.optimize_prompt(project.project_id)

            self.assertEqual(optimized.detected_input_language, "zh")
            self.assertEqual(optimized.dialogue_language, "zh")
            self.assertEqual(optimized.audio_language, "zh")
            language_events = [event for event in optimized.events if event.step == "language_detect"]
            self.assertEqual(len(language_events), 1)
            self.assertEqual(language_events[0].details["audio_language"], "zh")

    def test_optimize_prompt_continues_when_scene1_first_frame_analysis_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Analysis Failure Tolerance",
                prompt="生成一个葫芦娃七兄弟的预告片，加一点新的创意元素进去",
                target_duration_seconds=20,
                provider="mock",
                workflow_mode="hitl",
                scene1_first_frame_source="auto_generate",
            )

            with patch(
                "video_workflow_service.application.workflow_service.analyze_first_frame_step",
                side_effect=RuntimeError("Structured LLM output was not valid JSON: missing value"),
            ):
                optimized = service.optimize_prompt(project.project_id)

            self.assertEqual(optimized.status, "prompt_optimized")
            self.assertTrue(optimized.optimized_prompt)
            self.assertEqual(optimized.scene1_first_frame_status, "analysis_failed")
            analyze_events = [event for event in optimized.events if event.step == "first_frame_analyze"]
            self.assertTrue(analyze_events)
            self.assertEqual(analyze_events[-1].status, "failed")

    def test_plan_scenes_prepares_initial_auto_generated_first_frame(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Auto First Frame",
                prompt="A portrait opening shot.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
                scene1_first_frame_source="auto_generate",
                scene1_first_frame_prompt="A vertical portrait still of the heroine holding flowers indoors.",
            )

            planned = service.plan_scenes(project.project_id)
            first_scene = next(scene for scene in planned.scenes if scene.scene_id == "scene-01")

            self.assertEqual(first_scene.first_frame_source, "auto_generate")
            self.assertTrue(first_scene.first_frame_image)
            self.assertTrue(Path(first_scene.first_frame_image).exists())
            self.assertEqual(first_scene.first_frame_origin, "generated")
            self.assertEqual(first_scene.first_frame_status, "ready")
            self.assertTrue(first_scene.first_frame_analysis)
            self.assertIn("Opening still brief:", first_scene.first_frame_prompt)
            self.assertIn(
                "A vertical portrait still of the heroine holding flowers indoors",
                first_scene.first_frame_prompt,
            )
            self.assertIn("earliest stable state", first_scene.first_frame_prompt)

    def test_optimize_prompt_wraps_scene1_auto_generated_first_frame_as_opening_state(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Opening Still Guardrails",
                prompt="生成一个狮子被关在动物园，虽然每天被投喂食物，但是它过得并不开心，它期望的是草原，鹏鹏和丁满帮助它逃出动物园，回到草原。",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                scene1_first_frame_source="auto_generate",
            )

            optimized = service.optimize_prompt(project.project_id)

            self.assertIn("开场起点图说明：", optimized.scene1_first_frame_prompt)
            self.assertIn("只生成第1场在 t=0 时刻的单张起点图", optimized.scene1_first_frame_prompt)
            self.assertIn("不要把后续时间线", optimized.scene1_first_frame_prompt)

    def test_plan_scenes_rebuilds_scene1_auto_generated_first_frame_after_project_level_context(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Scene 1 Still Rebuild",
                prompt="Han Li studies a hand-drawn map in silence while Granny Liu waits outside with a lantern.",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                scene_count=2,
                scene1_first_frame_source="auto_generate",
            )

            optimized = service.optimize_prompt(project.project_id)
            initial_prompt = optimized.scene1_first_frame_prompt

            planned = service.plan_scenes(project.project_id)
            first_scene = next(scene for scene in planned.scenes if scene.scene_id == "scene-01")

            self.assertNotEqual(first_scene.first_frame_prompt, initial_prompt)
            self.assertIn("Opening still brief:", first_scene.first_frame_prompt)
            self.assertIn("Han Li", first_scene.first_frame_prompt)

    def test_start_scene_generation_rejects_legacy_unsupported_scene_duration(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Legacy Unsupported Duration",
                prompt="A portrait opening shot.",
                target_duration_seconds=10,
                provider="doubao",
                scene_count=1,
                workflow_mode="hitl",
                scene1_first_frame_source="upload",
                scene1_first_frame_image="data:image/png;base64,c2NlbmUx",
            )

            project = service.plan_scenes(project.project_id)
            first_scene = next(scene for scene in project.scenes if scene.scene_id == "scene-01")
            first_scene.duration_seconds = 18
            project.scenes = [first_scene]
            service.repo.save(project)

            with self.assertRaisesRegex(ValueError, "does not support 18s scene duration"):
                service.start_scene_generation(project.project_id, "scene-01")

    def test_scene1_auto_generated_still_uses_scene_filtered_character_anchor(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Scene 1 Character Still",
                prompt="Han Li studies a hand-drawn map in silence; Granny Liu waits at the doorway with a lantern.",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                scene_count=2,
                scene1_first_frame_source="auto_generate",
            )

            service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)

            first_scene = next(scene for scene in planned.scenes if scene.scene_id == "scene-01")
            self.assertIn("Han Li", first_scene.first_frame_prompt)
            self.assertNotIn("Granny Liu", first_scene.first_frame_prompt)
            self.assertEqual(planned.scene1_first_frame_prompt, first_scene.first_frame_prompt)
            self.assertTrue(Path(str(first_scene.first_frame_image)).exists())

    def test_revise_scene_prompt_updates_scene_prompt_from_feedback(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Prompt Feedback Revision",
                prompt="A woman studies an old map by candlelight.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )

            service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)
            previous_prompt = planned.scenes[0].prompt

            revised = service.revise_scene_prompt(
                planned.project_id,
                "scene-01",
                {"feedback": "镜头再近一点，情绪更压抑", "scope": "prompt_only"},
            )

            first_scene = next(scene for scene in revised.scenes if scene.scene_id == "scene-01")
            self.assertNotEqual(first_scene.prompt, previous_prompt)
            self.assertIn("镜头再近一点", first_scene.prompt)
            self.assertEqual(first_scene.approved_prompt, "")

    def test_revise_scene_prompt_can_regenerate_scene1_opening_still(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Opening Still Feedback Revision",
                prompt="生成一个狮子被关在动物园，虽然每天被投喂食物，但是它过得并不开心，它期望的是草原，鹏鹏和丁满帮助它逃出动物园，回到草原。",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                scene1_first_frame_source="auto_generate",
            )

            service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)
            first_scene_before = next(scene for scene in planned.scenes if scene.scene_id == "scene-01")
            previous_first_frame_prompt = first_scene_before.first_frame_prompt

            revised = service.revise_scene_prompt(
                planned.project_id,
                "scene-01",
                {"feedback": "门不应该开着", "scope": "opening_still_and_prompt"},
            )

            first_scene_after = next(scene for scene in revised.scenes if scene.scene_id == "scene-01")
            self.assertNotEqual(first_scene_after.first_frame_prompt, previous_first_frame_prompt)
            self.assertIn("门不应该开着", first_scene_after.first_frame_prompt)
            self.assertIn("门不应该开着", first_scene_after.prompt)
            self.assertTrue(Path(str(first_scene_after.first_frame_image)).exists())

    def test_revise_scene_prompt_rejects_continuity_start_state_change(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Continuity Prompt Feedback",
                prompt="A lion waits behind zoo bars, then later crosses into open grassland.",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                scene_count=2,
            )

            service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)

            with self.assertRaisesRegex(ValueError, "起始状态|start state"):
                service.revise_scene_prompt(
                    planned.project_id,
                    "scene-02",
                    {"feedback": "门不应该开着", "scope": "prompt_only"},
                )

    def test_prepare_character_anchors_generates_project_level_text_cards(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Character Anchors",
                prompt="Han Li walks with Granny Liu through a misty mountain garden.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
                scene1_first_frame_source="upload",
                scene1_first_frame_image="data:image/png;base64,c2NlbmUx",
            )

            prepared = service.prepare_character_anchors(project.project_id)

            self.assertGreaterEqual(len(prepared.character_cards), 2)
            first_card = prepared.character_cards[0]
            self.assertEqual(first_card.source, "text_only")
            self.assertIsNone(first_card.reference_image)
            self.assertTrue(first_card.reference_prompt)
            second_card = prepared.character_cards[1]
            self.assertEqual(second_card.source, "text_only")
            self.assertIsNone(second_card.reference_image)
            self.assertTrue(second_card.reference_prompt)

    def test_approved_character_lookdev_reference_prompt_shapes_scene_still_hint(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Approved Lookdev Still Hint",
                prompt="Han Li studies a hand-drawn map in silence; Granny Liu waits at the doorway with a lantern.",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                scene_count=2,
                scene1_first_frame_source="auto_generate",
            )

            service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)
            han_li_card = next(card for card in planned.character_cards if card.display_name == "Han Li")
            han_li_card.reference_prompt = "silver-threaded scholar robe, jade hair clasp, map scroll in hand"
            han_li_card.approval_status = "approved"

            first_scene = next(scene for scene in planned.scenes if scene.scene_id == "scene-01")
            regenerated_prompt = service._compose_scene_auto_generated_first_frame_prompt(planned, first_scene)

            self.assertIn("silver-threaded scholar robe", regenerated_prompt)
            self.assertNotIn("Granny Liu", regenerated_prompt)

    def test_serialize_project_exposes_character_reference_image_url(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Character Lookdev URLs",
                prompt="Han Li walks through a mountain garden.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )

            project = service.prepare_character_anchors(project.project_id)
            card = project.character_cards[0]
            project = service.regenerate_character_anchor(project.project_id, card.character_id)
            serialized = service.serialize_project(project, base_url="http://127.0.0.1:8787")

            first_card = serialized["character_cards"][0]
            self.assertTrue(first_card["reference_image"])
            self.assertTrue(first_card["reference_image_url"].startswith("http://127.0.0.1:8787/artifacts/"))

    def test_serialize_project_reports_subtitle_state_from_local_eligibility(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Subtitle Eligibility",
                prompt="A short narrated trailer about a lion returning home.",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                subtitle_mode="enabled",
            )
            project.scenes = [
                Scene(
                    scene_id="scene-01",
                    index=1,
                    title="Opening",
                    duration_seconds=6,
                    narrative="Silent setup",
                    spoken_text="",
                    speech_mode="none",
                ),
                Scene(
                    scene_id="scene-02",
                    index=2,
                    title="Reveal",
                    duration_seconds=6,
                    narrative="Spoken reveal",
                    spoken_text="他终于看见了真正的草原。",
                    speech_mode="once",
                ),
            ]

            serialized = service.serialize_project(project, base_url="http://127.0.0.1:8787")

            self.assertEqual(serialized["subtitle_mode"], "enabled")
            self.assertTrue(serialized["subtitle"]["enabled"])
            self.assertTrue(serialized["subtitle"]["eligible"])
            self.assertEqual(serialized["subtitle"]["status"], "planned")
            self.assertEqual(serialized["subtitle"]["reason"], "eligible")

    def test_compose_video_generates_subtitle_sidecars_without_blocking_delivery(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Subtitle Compose",
                prompt="A narrated trailer about a lion returning home.",
                target_duration_seconds=8,
                provider="mock",
                subtitle_mode="enabled",
            )
            clip_rel_path = f"{project.project_id}/scenes/scene-01.mp4"
            clip_path = settings.artifact_dir / clip_rel_path
            clip_path.parent.mkdir(parents=True, exist_ok=True)
            clip_path.write_bytes(b"scene-clip")
            project.scenes = [
                Scene(
                    scene_id="scene-01",
                    index=1,
                    title="Return",
                    duration_seconds=8,
                    narrative="A voiced return home.",
                    spoken_text="他终于看见了真正的草原。",
                    speech_mode="once",
                    status="generated",
                    video_rel_path=clip_rel_path,
                )
            ]
            service.repo.save(project)

            class FakeSubtitleClient:
                name = "fake_subtitles"

                def align_known_text(self, *, audio_path: Path, subtitle_text: str, language: str | None = None):
                    self.last_audio_path = audio_path
                    self.last_text = subtitle_text
                    self.last_language = language
                    return SubtitleAlignmentResult(
                        provider=self.name,
                        alignment_strategy="text_alignment",
                        cues=[
                            SubtitleCue(start_time_ms=0, end_time_ms=1200, text="他终于看见了真正的草原。"),
                        ],
                        metadata={"task_id": "task_sub_001"},
                    )

            subtitle_client = FakeSubtitleClient()

            def fake_compose_clips(**kwargs):
                output_path = kwargs["output_path"]
                output_path.write_bytes(b"final-video")
                return {"mode": "concat", "clip_count": 1}

            def fake_extract_audio_track(**kwargs):
                kwargs["output_path"].write_bytes(b"wav")

            with patch(
                "video_workflow_service.application.workflow_service.compose_clips",
                side_effect=fake_compose_clips,
            ), patch.object(
                service,
                "_subtitle_service_is_configured",
                return_value=True,
            ), patch.object(
                service,
                "_build_subtitle_client",
                return_value=subtitle_client,
            ), patch(
                "video_workflow_service.application.workflow_service.extract_audio_track",
                side_effect=fake_extract_audio_track,
            ):
                composed = service.compose_video(project.project_id)
                self.assertEqual(composed.status, "delivered")
                completed = service.wait_for_subtitle_job(project.project_id, timeout_seconds=5.0)

            self.assertIsNotNone(completed.subtitle_job)
            self.assertEqual(completed.subtitle_job.status, "completed")
            self.assertTrue(completed.subtitle_srt_rel_path)
            self.assertTrue(completed.subtitle_vtt_rel_path)
            self.assertTrue((settings.artifact_dir / str(completed.subtitle_srt_rel_path)).exists())
            self.assertTrue((settings.artifact_dir / str(completed.subtitle_vtt_rel_path)).exists())
            self.assertEqual(subtitle_client.last_text, "他终于看见了真正的草原。")
            serialized = service.serialize_project(completed, base_url="http://127.0.0.1:8787")
            self.assertEqual(serialized["subtitle"]["status"], "completed")
            self.assertEqual(serialized["subtitle"]["provider"], "fake_subtitles")
            self.assertTrue(serialized["subtitle"]["package_url"].endswith(f"/projects/{project.project_id}/delivery-package"))

            package_path = service.build_delivery_package(project.project_id)
            self.assertTrue(package_path.exists())
            with zipfile.ZipFile(package_path, "r") as archive:
                self.assertEqual(sorted(archive.namelist()), ["final.mp4", "final.srt", "final.vtt"])

    def test_apply_subtitle_alignment_result_creates_delivery_directory_when_missing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Subtitle Publish Directory",
                prompt="A narrated trailer about a lion returning home.",
                target_duration_seconds=8,
                provider="mock",
                subtitle_mode="enabled",
            )
            project.final_video_rel_path = f"{project.project_id}/delivery/final.mp4"
            project.subtitle_job = SubtitleJob(
                job_id="stj_test",
                status="running",
                provider="fake_subtitles",
                mode="enabled",
            )
            service.repo.save(project)

            completed = service._apply_subtitle_alignment_result(
                project.project_id,
                "stj_test",
                SubtitleAlignmentResult(
                    provider="fake_subtitles",
                    alignment_strategy="text_alignment",
                    cues=[SubtitleCue(start_time_ms=0, end_time_ms=800, text="回家了。")],
                    metadata={"task_id": "task_sub_001"},
                ),
            )

            self.assertTrue((settings.artifact_dir / str(completed.subtitle_srt_rel_path)).exists())
            self.assertTrue((settings.artifact_dir / str(completed.subtitle_vtt_rel_path)).exists())

    def test_compose_video_keeps_delivery_successful_when_subtitle_sidecar_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Subtitle Failure Isolation",
                prompt="A narrated trailer about a lion returning home.",
                target_duration_seconds=8,
                provider="mock",
                subtitle_mode="enabled",
            )
            clip_rel_path = f"{project.project_id}/scenes/scene-01.mp4"
            clip_path = settings.artifact_dir / clip_rel_path
            clip_path.parent.mkdir(parents=True, exist_ok=True)
            clip_path.write_bytes(b"scene-clip")
            project.scenes = [
                Scene(
                    scene_id="scene-01",
                    index=1,
                    title="Return",
                    duration_seconds=8,
                    narrative="A voiced return home.",
                    spoken_text="他终于看见了真正的草原。",
                    speech_mode="once",
                    status="generated",
                    video_rel_path=clip_rel_path,
                )
            ]
            service.repo.save(project)

            class FailingSubtitleClient:
                name = "fake_subtitles"

                def align_known_text(self, *, audio_path: Path, subtitle_text: str, language: str | None = None):
                    raise RuntimeError("subtitle alignment unavailable")

            def fake_compose_clips(**kwargs):
                kwargs["output_path"].write_bytes(b"final-video")
                return {"mode": "concat", "clip_count": 1}

            def fake_extract_audio_track(**kwargs):
                kwargs["output_path"].write_bytes(b"wav")

            with patch(
                "video_workflow_service.application.workflow_service.compose_clips",
                side_effect=fake_compose_clips,
            ), patch.object(
                service,
                "_subtitle_service_is_configured",
                return_value=True,
            ), patch.object(
                service,
                "_build_subtitle_client",
                return_value=FailingSubtitleClient(),
            ), patch.object(
                service,
                "_subtitle_asr_fallback_is_configured",
                return_value=False,
            ), patch(
                "video_workflow_service.application.workflow_service.extract_audio_track",
                side_effect=fake_extract_audio_track,
            ):
                composed = service.compose_video(project.project_id)
                self.assertEqual(composed.status, "delivered")
                completed = service.wait_for_subtitle_job(project.project_id, timeout_seconds=5.0)

            self.assertEqual(completed.status, "delivered")
            self.assertIsNotNone(completed.subtitle_job)
            self.assertEqual(completed.subtitle_job.status, "failed")
            self.assertIn("subtitle alignment unavailable", str(completed.subtitle_job.error_message))

    def test_compose_video_falls_back_to_asr_when_text_alignment_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Subtitle ASR Fallback",
                prompt="A narrated trailer about a lion returning home.",
                target_duration_seconds=8,
                provider="mock",
                subtitle_mode="enabled",
            )
            clip_rel_path = f"{project.project_id}/scenes/scene-01.mp4"
            clip_path = settings.artifact_dir / clip_rel_path
            clip_path.parent.mkdir(parents=True, exist_ok=True)
            clip_path.write_bytes(b"scene-clip")
            project.scenes = [
                Scene(
                    scene_id="scene-01",
                    index=1,
                    title="Return",
                    duration_seconds=8,
                    narrative="A voiced return home.",
                    spoken_text="他终于看见了真正的草原。",
                    speech_mode="once",
                    status="generated",
                    video_rel_path=clip_rel_path,
                )
            ]
            service.repo.save(project)

            class FailingSubtitleClient:
                name = "fake_ata"

                def align_known_text(self, *, audio_path: Path, subtitle_text: str, language: str | None = None):
                    raise RuntimeError("ata alignment unavailable")

            class FakeAsrClient:
                name = "fake_asr"

                def recognize_audio(self, *, audio_path: Path, language: str | None = None):
                    self.last_audio_path = audio_path
                    self.last_language = language
                    return SubtitleAlignmentResult(
                        provider=self.name,
                        alignment_strategy="asr_recognition",
                        cues=[
                            SubtitleCue(start_time_ms=0, end_time_ms=1200, text="他终于看见了真正的草原。"),
                        ],
                        metadata={"task_id": "task_asr_001"},
                    )

            asr_client = FakeAsrClient()

            def fake_compose_clips(**kwargs):
                kwargs["output_path"].write_bytes(b"final-video")
                return {"mode": "concat", "clip_count": 1}

            def fake_extract_audio_track(**kwargs):
                kwargs["output_path"].write_bytes(b"wav")

            with patch(
                "video_workflow_service.application.workflow_service.compose_clips",
                side_effect=fake_compose_clips,
            ), patch.object(
                service,
                "_subtitle_service_is_configured",
                return_value=True,
            ), patch.object(
                service,
                "_build_subtitle_client",
                return_value=FailingSubtitleClient(),
            ), patch.object(
                service,
                "_build_subtitle_asr_client",
                return_value=asr_client,
            ), patch(
                "video_workflow_service.application.workflow_service.extract_audio_track",
                side_effect=fake_extract_audio_track,
            ):
                composed = service.compose_video(project.project_id)
                self.assertEqual(composed.status, "delivered")
                completed = service.wait_for_subtitle_job(project.project_id, timeout_seconds=5.0)

            self.assertIsNotNone(completed.subtitle_job)
            self.assertEqual(completed.subtitle_job.status, "completed")
            self.assertEqual(completed.subtitle_job.provider, "fake_asr")
            self.assertEqual(completed.subtitle_job.metadata["alignment_strategy"], "asr_recognition")
            self.assertEqual(completed.subtitle_job.metadata["fallback_from"], "text_alignment")
            self.assertEqual(asr_client.last_audio_path.name, "final.subtitle-input.wav")
            self.assertEqual(asr_client.last_language, "")

    def test_compose_video_skips_subtitle_sidecar_when_service_is_not_configured(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Subtitle Skip",
                prompt="A narrated trailer about a lion returning home.",
                target_duration_seconds=8,
                provider="mock",
                subtitle_mode="enabled",
            )
            clip_rel_path = f"{project.project_id}/scenes/scene-01.mp4"
            clip_path = settings.artifact_dir / clip_rel_path
            clip_path.parent.mkdir(parents=True, exist_ok=True)
            clip_path.write_bytes(b"scene-clip")
            project.scenes = [
                Scene(
                    scene_id="scene-01",
                    index=1,
                    title="Return",
                    duration_seconds=8,
                    narrative="A voiced return home.",
                    spoken_text="他终于看见了真正的草原。",
                    speech_mode="once",
                    status="generated",
                    video_rel_path=clip_rel_path,
                )
            ]
            service.repo.save(project)

            def fake_compose_clips(**kwargs):
                kwargs["output_path"].write_bytes(b"final-video")
                return {"mode": "concat", "clip_count": 1}

            with patch(
                "video_workflow_service.application.workflow_service.compose_clips",
                side_effect=fake_compose_clips,
            ):
                composed = service.compose_video(project.project_id)

            self.assertEqual(composed.status, "delivered")
            self.assertIsNotNone(composed.subtitle_job)
            self.assertEqual(composed.subtitle_job.status, "skipped")
            serialized = service.serialize_project(composed, base_url="http://127.0.0.1:8787")
            self.assertEqual(serialized["subtitle"]["status"], "skipped")

    def test_export_subtitled_video_publishes_separate_burned_artifact(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Subtitle Burn Export",
                prompt="A narrated trailer about a lion returning home.",
                target_duration_seconds=8,
                provider="mock",
                subtitle_mode="enabled",
            )
            clip_rel_path = f"{project.project_id}/scenes/scene-01.mp4"
            clip_path = settings.artifact_dir / clip_rel_path
            clip_path.parent.mkdir(parents=True, exist_ok=True)
            clip_path.write_bytes(b"scene-clip")
            project.scenes = [
                Scene(
                    scene_id="scene-01",
                    index=1,
                    title="Return",
                    duration_seconds=8,
                    narrative="A voiced return home.",
                    spoken_text="他终于看见了真正的草原。",
                    speech_mode="once",
                    status="generated",
                    video_rel_path=clip_rel_path,
                )
            ]
            service.repo.save(project)

            class FakeSubtitleClient:
                name = "fake_subtitles"

                def align_known_text(self, *, audio_path: Path, subtitle_text: str, language: str | None = None):
                    return SubtitleAlignmentResult(
                        provider=self.name,
                        alignment_strategy="text_alignment",
                        cues=[SubtitleCue(start_time_ms=0, end_time_ms=1200, text="他终于看见了真正的草原。")],
                        metadata={"task_id": "task_sub_001"},
                    )

            def fake_compose_clips(**kwargs):
                kwargs["output_path"].write_bytes(b"final-video")
                return {"mode": "concat", "clip_count": 1}

            def fake_extract_audio_track(**kwargs):
                kwargs["output_path"].write_bytes(b"wav")

            def fake_burn_subtitles_into_video(**kwargs):
                kwargs["output_path"].write_bytes(b"burned-video")

            with patch(
                "video_workflow_service.application.workflow_service.compose_clips",
                side_effect=fake_compose_clips,
            ), patch.object(
                service,
                "_subtitle_service_is_configured",
                return_value=True,
            ), patch.object(
                service,
                "_build_subtitle_client",
                return_value=FakeSubtitleClient(),
            ), patch(
                "video_workflow_service.application.workflow_service.extract_audio_track",
                side_effect=fake_extract_audio_track,
            ), patch(
                "video_workflow_service.application.workflow_service.burn_subtitles_into_video",
                side_effect=fake_burn_subtitles_into_video,
            ):
                service.compose_video(project.project_id)
                service.wait_for_subtitle_job(project.project_id, timeout_seconds=5.0)
                queued = service.export_subtitled_video(project.project_id)
                self.assertIsNotNone(queued.subtitle_burn_job)
                self.assertEqual(queued.subtitle_burn_job.status, "queued")
                completed = service.wait_for_subtitle_burn_job(project.project_id, timeout_seconds=5.0)

            self.assertIsNotNone(completed.subtitle_burn_job)
            self.assertEqual(completed.subtitle_burn_job.status, "completed")
            self.assertTrue(completed.subtitle_burned_video_rel_path)
            self.assertTrue((settings.artifact_dir / str(completed.subtitle_burned_video_rel_path)).exists())
            serialized = service.serialize_project(completed, base_url="http://127.0.0.1:8787")
            self.assertEqual(serialized["subtitle"]["burn_status"], "completed")
            self.assertTrue(str(serialized["subtitle"]["burned_video_url"]).endswith("/final_burned.mp4"))

    def test_plan_scenes_records_story_roles_and_story_plan_event(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Story Plan",
                prompt="A quiet herbalist reveals a hidden identity over two connected scenes.",
                target_duration_seconds=15,
                provider="mock",
                workflow_mode="hitl",
                scene_count=2,
            )

            optimized = service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)

            self.assertTrue(optimized.optimized_prompt)
            self.assertEqual(len(planned.scenes), 2)
            self.assertTrue(all(scene.story_role for scene in planned.scenes))
            self.assertTrue(all(scene.story_purpose for scene in planned.scenes))
            self.assertTrue(all(scene.story_advance_goal for scene in planned.scenes))
            self.assertTrue(all(scene.pacing_intent for scene in planned.scenes))
            self.assertTrue(all(scene.information_load for scene in planned.scenes))
            self.assertTrue(all(scene.speech_expectation for scene in planned.scenes))

            story_plan_events = [event for event in planned.events if event.step == "story_plan"]
            self.assertEqual(len(story_plan_events), 1)
            self.assertEqual(story_plan_events[0].status, "completed")
            self.assertIn("overall_story_arc", story_plan_events[0].details)
            self.assertEqual(len(story_plan_events[0].details["scene_roles"]), 2)

    def test_plan_scenes_assigns_scene_level_character_participation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Scene Character Cast",
                prompt="Han Li studies a hand-drawn map in silence; Granny Liu waits at the doorway with a lantern.",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                scene_count=2,
            )

            service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)

            character_ids = {card.display_name: card.character_id for card in planned.character_cards}
            self.assertEqual(len(character_ids), 2)
            scene_01 = next(scene for scene in planned.scenes if scene.scene_id == "scene-01")
            scene_02 = next(scene for scene in planned.scenes if scene.scene_id == "scene-02")
            self.assertEqual(scene_01.participating_character_ids, [character_ids["Han Li"]])
            self.assertEqual(scene_01.primary_character_id, character_ids["Han Li"])
            self.assertIn("Han Li", scene_01.character_presence_notes)
            self.assertEqual(scene_02.participating_character_ids, [character_ids["Granny Liu"]])
            self.assertEqual(scene_02.primary_character_id, character_ids["Granny Liu"])
            self.assertIn("Granny Liu", scene_02.character_presence_notes)

            cast_events = [event for event in planned.events if event.step == "scene_character_cast"]
            self.assertEqual(len(cast_events), 1)
            self.assertEqual(cast_events[0].status, "completed")

    def test_create_project_rejects_scene1_upload_without_image(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)

            with self.assertRaisesRegex(ValueError, "scene1_first_frame_source=upload requires scene1_first_frame_image"):
                service.create_project(
                    title="Invalid Scene 1 Source",
                    prompt="A portrait opening shot.",
                    target_duration_seconds=10,
                    provider="mock",
                    scene1_first_frame_source="upload",
                )

    def test_full_workflow_generates_final_video(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Test Project",
                prompt="A young traveler explores a rainy neon city and finds a hidden rooftop garden.",
                target_duration_seconds=12,
                provider="mock",
            )

            project = service.run_workflow(project.project_id)
            reloaded = service.get_project(project.project_id)

            self.assertEqual(reloaded.status, "delivered")
            self.assertTrue(reloaded.final_video_rel_path)
            final_path = settings.artifact_dir / reloaded.final_video_rel_path
            self.assertTrue(final_path.exists(), final_path)
            self.assertGreater(final_path.stat().st_size, 0)

            self.assertIsNotNone(reloaded.final_video_job)
            self.assertEqual(reloaded.final_video_job.status, "completed")
            self.assertGreaterEqual(reloaded.final_video_job.attempt_count, 1)
            self.assertEqual(reloaded.final_video_job.final_video_rel_path, reloaded.final_video_rel_path)

            self.assertGreaterEqual(len(reloaded.scenes), 2)
            for scene in reloaded.scenes:
                self.assertEqual(scene.status, "generated")
                self.assertTrue(scene.video_rel_path)
                self.assertTrue((settings.artifact_dir / scene.video_rel_path).exists())
                self.assertIsNotNone(scene.video_job)
                self.assertEqual(scene.video_job.status, "completed")
                self.assertGreaterEqual(scene.video_job.attempt_count, 1)
                self.assertEqual(scene.video_job.scene_id, scene.scene_id)
                self.assertEqual(scene.video_job.video_rel_path, scene.video_rel_path)
                self.assertEqual(scene.video_job.final_frame_rel_path, scene.final_frame_rel_path)

    def test_storyboard_upload_validation_requires_locator_and_payload(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Storyboard Validation",
                prompt="A three-scene storyboard validation flow.",
                target_duration_seconds=12,
                provider="mock",
            )
            service.plan_scenes(project.project_id)

            with self.assertRaises(ValueError):
                service.upload_storyboards(
                    project.project_id,
                    [{"storyboard_notes": "Missing locator"}],
                )

            with self.assertRaises(ValueError):
                service.upload_storyboards(
                    project.project_id,
                    [{"scene_index": 1}],
                )

    def test_storyboard_upload_persists_first_frame_source_and_image(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="First Frame Binding",
                prompt="A short two-scene review flow.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            service.plan_scenes(project.project_id)

            updated = service.upload_storyboards(
                project.project_id,
                [
                    {
                        "scene_id": "scene-01",
                        "first_frame_source": "upload",
                        "first_frame_image": "data:image/png;base64,Zmlyc3QtZnJhbWU=",
                        "storyboard_notes": "hero opening"
                    }
                ],
            )

            scene = next(scene for scene in updated.scenes if scene.scene_id == "scene-01")
            self.assertEqual(scene.first_frame_source, "upload")
            self.assertEqual(scene.first_frame_image, "data:image/png;base64,Zmlyc3QtZnJhbWU=")
            self.assertEqual(scene.storyboard_notes, "hero opening")
            self.assertNotIn("provided first frame", scene.prompt.lower())
            self.assertEqual(
                scene.provider_metadata["scene_prompt_refresh"]["mode"],
                "llm_scene_prompt_render",
            )
            self.assertIn("camera", scene.prompt.lower())

    def test_uploaded_first_frame_adds_opening_frame_constraint_to_generation_prompt(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Upload First Frame Prompt",
                prompt="A close-up of a woman taking flowers from a wooden table.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)
            updated = service.upload_storyboards(
                planned.project_id,
                [
                    {
                        "scene_id": "scene-01",
                        "first_frame_source": "upload",
                        "first_frame_image": "data:image/png;base64,Zmlyc3QtZnJhbWU=",
                    }
                ],
            )

            scene = next(item for item in updated.scenes if item.scene_id == "scene-01")
            contract = service._build_scene_generation_input(
                updated,
                scene,
                {item.scene_id: item for item in updated.scenes},
            )
            self.assertNotIn("uploaded first frame", contract.prompt.lower())
            self.assertNotIn("provided first frame", contract.prompt.lower())
            self.assertIn("holding", contract.prompt.lower())
            self.assertIn("flower bundle", contract.prompt.lower())

    def test_plan_scenes_preserves_chinese_dialogue_language_in_rendered_prompt(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Chinese Dialogue",
                prompt='一个古装女人站在药房里，慢慢说道：“他们都以为我只是个医娘子。”',
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
                scene_count=2,
            )

            service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)

            self.assertEqual(planned.audio_language, "zh")
            spoken_scenes = [scene for scene in planned.scenes if scene.spoken_text]
            self.assertTrue(spoken_scenes)
            self.assertTrue(
                any("用自然中文" in scene.prompt for scene in spoken_scenes),
                "expected rendered prompt to stay in Chinese for Chinese input",
            )

    def test_async_workflow_run_supports_project_scene_count(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Async Workflow",
                prompt="A dynamic four-scene workflow execution.",
                target_duration_seconds=16,
                provider="mock",
                scene_count=4,
            )

            queued = service.start_workflow_run(project.project_id)
            self.assertIsNotNone(queued.workflow_run_job)
            self.assertIn(queued.workflow_run_job.status, {"queued", "running"})

            completed = service.wait_for_workflow_run(project.project_id, timeout_seconds=60.0)
            self.assertEqual(completed.status, "delivered")
            self.assertIsNotNone(completed.workflow_run_job)
            self.assertEqual(completed.workflow_run_job.status, "completed")
            self.assertEqual(completed.workflow_run_job.last_completed_step, "final_compose")
            self.assertEqual(completed.workflow_run_job.completed_steps, [
                "prompt_optimize",
                "scene_plan",
                "scene_video_generate",
                "final_compose",
            ])
            self.assertEqual(len(completed.scenes), 4)
            self.assertEqual(completed.scene_count, 4)

    def test_hitl_scene_flow_requires_approval_before_next_scene(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="HITL Flow",
                prompt="A two-scene cinematic reveal with a continuity handoff.",
                target_duration_seconds=10,
                provider="mock",
                scene_count=2,
                workflow_mode="hitl",
            )

            queued = service.start_scene_generation(project.project_id, "scene-01")
            self.assertEqual(queued.workflow_mode, "hitl")
            self.assertEqual(queued.scenes[0].status, "queued")

            reviewed = self._wait_for_scene_status(service, project.project_id, "scene-01", "pending_review")
            self.assertEqual(reviewed.status, "awaiting_scene_review")

            with self.assertRaises(ValueError):
                service.start_scene_generation(project.project_id, "scene-02")

            approved_first = service.approve_scene(project.project_id, "scene-01")
            self.assertEqual(approved_first.scenes[0].status, "approved")
            self.assertEqual(approved_first.status, "ready_for_next_scene")

            service.start_scene_generation(project.project_id, "scene-02")
            reviewed_second = self._wait_for_scene_status(service, project.project_id, "scene-02", "pending_review")
            self.assertEqual(reviewed_second.status, "awaiting_scene_review")

            approved_second = service.approve_scene(project.project_id, "scene-02")
            self.assertEqual(approved_second.status, "ready_for_compose")

            composed = service.compose_video(project.project_id)
            self.assertEqual(composed.status, "delivered")
            self.assertTrue(composed.final_video_rel_path)

    def test_hitl_next_scene_can_start_while_downstream_refresh_is_still_running(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="HITL Continuity Refresh Window",
                prompt="A three-scene cinematic reveal with continuity handoff.",
                target_duration_seconds=15,
                provider="mock",
                scene_count=3,
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)

            refresh_started = threading.Event()
            release_refresh = threading.Event()
            original_refresh = service._refresh_downstream_scene_prompts_for_continuity

            def blocking_refresh(project_id: str, source_scene_id: str):
                if source_scene_id == "scene-01":
                    refresh_started.set()
                    release_refresh.wait(timeout=5.0)
                return original_refresh(project_id, source_scene_id)

            with patch.object(
                service,
                "_refresh_downstream_scene_prompts_for_continuity",
                side_effect=blocking_refresh,
            ):
                service.start_scene_generation(planned.project_id, "scene-01")
                reviewed = self._wait_for_scene_status(service, planned.project_id, "scene-01", "pending_review")
                self.assertTrue(refresh_started.wait(timeout=5.0))

                approved = service.approve_scene(planned.project_id, "scene-01")
                self.assertEqual(approved.scenes[0].status, "approved")

                queued_second = service.start_scene_generation(planned.project_id, "scene-02")
                second_scene = next(scene for scene in queued_second.scenes if scene.scene_id == "scene-02")
                self.assertEqual(second_scene.status, "queued")

                release_refresh.set()
                reviewed_second = self._wait_for_scene_status(service, planned.project_id, "scene-02", "pending_review")
                self.assertEqual(reviewed_second.status, "awaiting_scene_review")

    def test_hitl_upload_source_requires_image_before_generation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Missing First Frame",
                prompt="A scene that expects an uploaded first frame.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)
            planned.scenes[0].first_frame_source = "upload"
            planned.scenes[0].first_frame_image = None
            service.repo.save(planned)

            with self.assertRaisesRegex(ValueError, "Upload a first-frame image"):
                service.start_scene_generation(project.project_id, "scene-01")

    def test_update_scene_prompt_persists_for_hitl_scene(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Prompt Editing",
                prompt="A two-scene prompt editing workflow.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)

            updated = service.update_scene_prompt(
                planned.project_id,
                "scene-01",
                {"prompt": "A revised opening shot with stronger motion cues."},
            )

            scene = next(scene for scene in updated.scenes if scene.scene_id == "scene-01")
            self.assertEqual(scene.prompt, "A revised opening shot with stronger motion cues.")
            self.assertNotEqual(scene.rendered_prompt, "")

    def test_hitl_regenerate_from_pending_review_uses_updated_prompt_snapshot(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Prompt Snapshot",
                prompt="A two-scene prompt revision workflow.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )

            service.start_scene_generation(project.project_id, "scene-01")
            reviewed = self._wait_for_scene_status(service, project.project_id, "scene-01", "pending_review")
            original_job = reviewed.scenes[0].video_job
            self.assertIsNotNone(original_job)

            updated = service.update_scene_prompt(
                project.project_id,
                "scene-01",
                {"prompt": "A tighter revised prompt after the first review."},
            )
            self.assertEqual(updated.scenes[0].status, "pending_review")

            service.start_scene_generation(project.project_id, "scene-01")
            regenerated = self._wait_for_scene_video_job_attempt(
                service,
                project.project_id,
                "scene-01",
                minimum_attempt_count=original_job.attempt_count + 1,
            )
            scene = regenerated.scenes[0]
            self.assertIsNotNone(scene.video_job)
            self.assertGreater(scene.video_job.attempt_count, original_job.attempt_count)
            self.assertIn(
                "A tighter revised prompt after the first review",
                scene.video_job.metadata["scene_prompt_snapshot"],
            )
            self.assertIn(
                "A tighter revised prompt after the first review",
                scene.video_job.metadata["scene_prompt_draft_snapshot"],
            )
            self.assertIn(
                "A tighter revised prompt after the first review",
                scene.video_job.metadata["scene_prompt"],
            )
            self.assertIn(
                "A tighter revised prompt after the first review",
                scene.video_job.metadata["scene_prompt_draft"],
            )
            self.assertEqual(
                scene.video_job.metadata["approved_prompt_snapshot"],
                "A tighter revised prompt after the first review.",
            )
            self.assertNotIn(
                "A tighter revised prompt after the first review",
                scene.video_job.metadata["scene_rendered_prompt_snapshot"],
            )
            self.assertEqual(
                scene.video_job.metadata["provider_prompt_snapshot"],
                scene.video_job.metadata["prompt_snapshot"],
            )
            self.assertIn("A tighter revised prompt after the first review", scene.video_job.metadata["prompt_snapshot"])
            self.assertIn("A tighter revised prompt after the first review", scene.prompt)

    def test_scene_completion_persists_even_if_downstream_continuity_refresh_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Continuity Refresh Failure",
                prompt="A three-scene continuity-driven reveal.",
                target_duration_seconds=15,
                provider="mock",
                scene_count=3,
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)

            first_reviewed = service._generate_scene_sync(
                planned.project_id,
                "scene-01",
                requires_review=True,
            )
            self.assertEqual(first_reviewed.scenes[0].status, "pending_review")
            approved = service.approve_scene(planned.project_id, "scene-01")
            self.assertEqual(approved.scenes[0].status, "approved")

            with patch.object(
                service,
                "_refresh_downstream_scene_prompts_for_continuity",
                side_effect=RuntimeError("continuity refresh boom"),
            ):
                generated = service._generate_scene_sync(
                    planned.project_id,
                    "scene-02",
                    requires_review=True,
                )

            self.assertEqual(generated.project_id, planned.project_id)
            reloaded = service.get_project(planned.project_id)
            scene = next(item for item in reloaded.scenes if item.scene_id == "scene-02")
            self.assertEqual(scene.status, "pending_review")
            self.assertEqual(scene.review_status, "pending_review")
            self.assertIsNotNone(scene.video_job)
            self.assertEqual(scene.video_job.status, "completed")
            self.assertTrue(scene.video_rel_path)

    def test_storyboard_refresh_keeps_user_prompt_draft_when_render_updates(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Prompt Draft Preservation",
                prompt="A woman stands in an apothecary holding dried herbs.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)
            initial_scene = next(scene for scene in planned.scenes if scene.scene_id == "scene-01")
            initial_rendered = initial_scene.rendered_prompt

            edited = service.update_scene_prompt(
                project.project_id,
                "scene-01",
                {"prompt": "Keep the calm pose, but add a sharper eye-line change."},
            )
            refreshed = service.upload_storyboards(
                edited.project_id,
                [
                    {
                        "scene_id": "scene-01",
                        "first_frame_source": "upload",
                        "first_frame_image": "data:image/png;base64,Zmlyc3QtZnJhbWU=",
                    }
                ],
            )

            scene = next(item for item in refreshed.scenes if item.scene_id == "scene-01")
            self.assertEqual(scene.prompt, "Keep the calm pose, but add a sharper eye-line change.")
            self.assertNotEqual(scene.rendered_prompt, "")
            self.assertNotEqual(scene.prompt, scene.rendered_prompt)

    def test_storyboard_refresh_marks_user_prompt_stale_instead_of_overwriting(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Prompt Staleness",
                prompt="A woman stands in an apothecary holding dried herbs.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)

            edited = service.update_scene_prompt(
                planned.project_id,
                "scene-01",
                {"prompt": "Hold the herb bundle steady and speak with a sharper reveal."},
            )
            refreshed = service.upload_storyboards(
                edited.project_id,
                [
                    {
                        "scene_id": "scene-01",
                        "first_frame_source": "upload",
                        "first_frame_image": "data:image/png;base64,c3RhbGU=",
                    }
                ],
            )

            scene = next(item for item in refreshed.scenes if item.scene_id == "scene-01")
            self.assertEqual(scene.prompt, "Hold the herb bundle steady and speak with a sharper reveal.")
            self.assertTrue(scene.prompt_stale)
            self.assertIn("first_frame_source_changed", scene.prompt_stale_reasons)
            self.assertIn("first_frame_image_changed", scene.prompt_stale_reasons)
            self.assertEqual(scene.approved_prompt, "")

    def test_generate_freezes_user_prompt_without_rerendering(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Prompt Freeze",
                prompt="A woman stands in an apothecary holding dried herbs.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)
            storyboarded = service.upload_storyboards(
                planned.project_id,
                [
                    {
                        "scene_id": "scene-01",
                        "first_frame_source": "upload",
                        "first_frame_image": "data:image/png;base64,Zmlyc3Q=",
                    }
                ],
            )
            custom_prompt = "Waist-up shot, woman already holding the herb bundle, speak the line once and hold eye contact."
            edited = service.update_scene_prompt(
                storyboarded.project_id,
                "scene-01",
                {"prompt": custom_prompt},
            )

            service.start_scene_generation(edited.project_id, "scene-01")
            generated = self._wait_for_scene_status(service, edited.project_id, "scene-01", "pending_review")
            scene = next(item for item in generated.scenes if item.scene_id == "scene-01")

            self.assertEqual(scene.approved_prompt, custom_prompt)
            self.assertFalse(scene.prompt_stale)
            self.assertEqual(scene.video_job.metadata["approved_prompt_snapshot"], custom_prompt)
            self.assertEqual(scene.video_job.metadata["provider_prompt_snapshot"], custom_prompt)
            self.assertEqual(scene.video_job.metadata["prompt_snapshot"], custom_prompt)

    def test_scene_completion_marks_downstream_user_prompt_stale_when_continuity_updates(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Continuity Prompt Staleness",
                prompt="A woman reveals a dangerous secret in two scenes.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)
            edited = service.update_scene_prompt(
                planned.project_id,
                "scene-02",
                {"prompt": "Push closer on the reveal, no dialogue, hold the mystery in silence."},
            )

            service.start_scene_generation(edited.project_id, "scene-01")
            self._wait_for_scene_status(service, edited.project_id, "scene-01", "pending_review")
            updated = self._wait_for_scene_prompt_stale(service, edited.project_id, "scene-02")
            scene = next(item for item in updated.scenes if item.scene_id == "scene-02")

            self.assertEqual(scene.prompt, "Push closer on the reveal, no dialogue, hold the mystery in silence.")
            self.assertTrue(scene.prompt_stale)
            self.assertIn("continuity_frame_updated", scene.prompt_stale_reasons)

    def test_downstream_continuity_refresh_preserves_source_scene_approval(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Continuity Approval Race",
                prompt="A three-scene reveal with a continuity-driven third scene.",
                target_duration_seconds=12,
                provider="mock",
                workflow_mode="hitl",
                scene_count=3,
            )
            planned = service.plan_scenes(project.project_id)

            scene_01 = next(item for item in planned.scenes if item.scene_id == "scene-01")
            scene_02 = next(item for item in planned.scenes if item.scene_id == "scene-02")
            scene_03 = next(item for item in planned.scenes if item.scene_id == "scene-03")
            scene_01.status = "approved"
            scene_01.review_status = "approved"
            scene_02.status = "pending_review"
            scene_02.review_status = "pending_review"
            scene_02.video_rel_path = f"{planned.project_id}/scenes/scene-02.mp4"
            scene_02.final_frame_rel_path = f"{planned.project_id}/scenes/scene-02_last.png"
            scene_03.status = "planned"
            scene_03.review_status = "pending_generation"
            service.repo.save(planned)

            def fake_refresh(project_obj, scene, scene_index_map, *, stale_reasons=None):
                latest = service.repo.load(project.project_id)
                source_scene = next(item for item in latest.scenes if item.scene_id == "scene-02")
                source_scene.status = "approved"
                source_scene.review_status = "approved"
                service.repo.save(latest)

                scene.rendered_prompt = "Downstream continuity prompt"
                scene.prompt = "Downstream continuity prompt"
                scene.approved_prompt = ""
                scene.prompt_stale = True
                scene.prompt_stale_reasons = ["continuity_frame_updated"]

            with patch.object(service, "_refresh_scene_prompt_after_upstream_change", side_effect=fake_refresh):
                service._refresh_downstream_scene_prompts_for_continuity(project.project_id, "scene-02")

            saved = service.repo.load(project.project_id)
            saved_scene_02 = next(item for item in saved.scenes if item.scene_id == "scene-02")
            saved_scene_03 = next(item for item in saved.scenes if item.scene_id == "scene-03")

            self.assertEqual(saved_scene_02.status, "approved")
            self.assertEqual(saved_scene_02.review_status, "approved")
            self.assertEqual(saved_scene_03.prompt, "Downstream continuity prompt")
            self.assertTrue(saved_scene_03.prompt_stale)
            self.assertIn("continuity_frame_updated", saved_scene_03.prompt_stale_reasons)

    def test_update_scene_prompt_rejects_in_flight_generation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            project = service.create_project(
                title="Prompt Update Guard",
                prompt="A guarded prompt update flow.",
                target_duration_seconds=10,
                provider="mock",
                workflow_mode="hitl",
            )
            planned = service.plan_scenes(project.project_id)
            planned.scenes[0].video_job = SceneVideoJob(
                job_id="svg_running",
                scene_id="scene-01",
                provider="mock",
                status="running",
            )
            service.repo.save(planned)

            with self.assertRaisesRegex(ValueError, "generation is in progress"):
                service.update_scene_prompt(
                    project.project_id,
                    "scene-01",
                    {"prompt": "This update should be rejected."},
                )

    def test_provider_capability_registry_lists_known_providers(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)

            providers = service.list_provider_capabilities()
            provider_names = {provider["name"] for provider in providers}

            self.assertIn("doubao", provider_names)
            self.assertIn("mock", provider_names)

    def test_load_settings_reads_only_local_env_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=env_key",
                        "VIDEO_WORKFLOW_PROVIDER=mock",
                    ]
                ),
                encoding="utf-8",
            )
            (root / ".env.local").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=local_key",
                        "VIDEO_WORKFLOW_PORT=9900",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(root)
                self.assertNotIn("DOUBAO_API_KEY", os.environ)
                self.assertNotIn("VIDEO_WORKFLOW_PORT", os.environ)

            self.assertEqual(settings.doubao_api_key, "local_key")
            self.assertEqual(settings.default_provider, "mock")
            self.assertEqual(settings.port, 9900)

    def test_load_settings_does_not_leak_env_between_roots(self) -> None:
        with TemporaryDirectory() as first_tmp_dir, TemporaryDirectory() as second_tmp_dir:
            first_root = Path(first_tmp_dir)
            second_root = Path(second_tmp_dir)
            (first_root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                first_settings = load_settings(first_root)
                second_settings = load_settings(second_root)

            self.assertEqual(first_settings.llm_provider, "doubao")
            self.assertEqual(second_settings.llm_provider, "mock")

    def _wait_for_scene_status(
        self,
        service: WorkflowService,
        project_id: str,
        scene_id: str,
        expected_status: str,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.1,
    ):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            project = service.get_project(project_id)
            for scene in project.scenes:
                if scene.scene_id == scene_id and scene.status == expected_status:
                    return project
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Scene {scene_id} did not reach {expected_status}")

    def _wait_for_scene_prompt_stale(
        self,
        service: WorkflowService,
        project_id: str,
        scene_id: str,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.1,
    ):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            project = service.get_project(project_id)
            for scene in project.scenes:
                if scene.scene_id == scene_id and scene.prompt_stale:
                    return project
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Scene {scene_id} did not become prompt-stale")

    def _wait_for_scene_video_job_attempt(
        self,
        service: WorkflowService,
        project_id: str,
        scene_id: str,
        *,
        minimum_attempt_count: int,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.1,
    ):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            project = service.get_project(project_id)
            for scene in project.scenes:
                video_job = scene.video_job
                if (
                    scene.scene_id == scene_id
                    and video_job is not None
                    and video_job.attempt_count >= minimum_attempt_count
                    and scene.status == "pending_review"
                ):
                    return project
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Scene {scene_id} did not reach attempt_count {minimum_attempt_count}")


if __name__ == "__main__":
    unittest.main()
