from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging
from pathlib import Path
from threading import Lock
import time
from typing import Any
from uuid import uuid4
import zipfile

from video_workflow_service.domain.models import (
    CharacterCard,
    FinalVideoJob,
    Project,
    Scene,
    SceneVideoJob,
    SubtitleBurnJob,
    SubtitleJob,
    WorkflowRunJob,
    utc_now,
)
from video_workflow_service.infrastructure.config import ServiceSettings, load_settings
from video_workflow_service.media.ffmpeg_pipeline import (
    burn_subtitles_into_video,
    compose_clips,
    extract_audio_track,
)
from video_workflow_service.providers.factory import get_video_provider, list_video_providers
from video_workflow_service.storage.project_repository import ProjectRepository
from video_workflow_service.subtitles.formats import render_srt, render_vtt
from video_workflow_service.subtitles.service import SubtitleAlignmentResult, SubtitleClient
from video_workflow_service.subtitles.volcengine_asr import VolcengineSpeechAsrClient
from video_workflow_service.subtitles.volcengine_speech import VolcengineSpeechSubtitleClient
from video_workflow_service.workflow.contracts import (
    CharacterAnchorInput,
    FinalCompositionInput,
    FinalCompositionOutput,
    FirstFrameAnalyzeInput,
    LanguageDetectInput,
    PromptOptimizationInput,
    ScenePromptRevisionInput,
    ScenePromptRevisionRequest,
    SceneCharacterCastInput,
    SceneCharacterCastSceneInput,
    SceneGenerationInput,
    SceneGenerationOutput,
    ScenePlanningInput,
    ScenePromptRenderInput,
    ScenePromptUpdateInput,
    StoryPlanInput,
    StoryboardUploadInput,
    StoryboardUploadOutput,
)
from video_workflow_service.workflow.character_anchor import character_anchor_step
from video_workflow_service.workflow.context_assembler import (
    build_project_guidance_context,
    build_scene_guidance_context,
)
from video_workflow_service.workflow.first_frame_analyze import analyze_first_frame_step
from video_workflow_service.workflow.first_frame_prepare import (
    FirstFramePrepareInput,
    prepare_first_frame_step,
)
from video_workflow_service.workflow.language_detect import detect_language_step
from video_workflow_service.workflow.prompt_optimization import optimize_prompt_step
from video_workflow_service.workflow.scene_character_cast import scene_character_cast_step
from video_workflow_service.workflow.scene_planning import plan_scenes_step
from video_workflow_service.workflow.scene_prompt_render import (
    render_scene_prompt_step,
)
from video_workflow_service.workflow.scene_prompt_revise import revise_scene_prompt_step
from video_workflow_service.workflow.story_plan import (
    distribute_duration,
    story_plan_step,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


class WorkflowService:
    def __init__(self, settings: ServiceSettings | None = None):
        self.settings = settings or load_settings()
        self.repo = ProjectRepository(self.settings)
        self._executor = ThreadPoolExecutor(max_workers=max(1, self.settings.workflow_max_workers))
        self._futures_lock = Lock()
        self._workflow_futures: dict[str, Future[Project]] = {}
        self._scene_futures: dict[str, Future[Project]] = {}
        self._subtitle_futures: dict[str, Future[Project]] = {}
        self._subtitle_burn_futures: dict[str, Future[Project]] = {}
        self.logger = logging.getLogger(__name__)
        self.trace_logger = WorkflowTraceLogger(self.settings)

    def create_project(
        self,
        *,
        title: str,
        prompt: str,
        target_duration_seconds: int = 15,
        aspect_ratio: str | None = None,
        provider: str | None = None,
        scene_count: int | None = None,
        workflow_mode: str | None = None,
        subtitle_mode: str | None = None,
        scene1_first_frame_source: str | None = None,
        scene1_first_frame_image: str | None = None,
        scene1_first_frame_prompt: str | None = None,
    ) -> Project:
        normalized_workflow_mode = str(workflow_mode or "auto").strip().lower()
        if normalized_workflow_mode not in {"auto", "hitl"}:
            raise ValueError("workflow_mode must be auto or hitl")
        normalized_subtitle_mode = self._normalize_subtitle_mode(subtitle_mode)
        normalized_scene1_source = self._normalize_scene1_first_frame_source(scene1_first_frame_source)
        normalized_scene1_image = self._normalize_optional_string(scene1_first_frame_image)
        normalized_scene1_prompt = self._normalize_scene1_first_frame_prompt(
            prompt=prompt,
            source=normalized_scene1_source,
            first_frame_prompt=scene1_first_frame_prompt,
        )
        normalized_provider = (provider or self.settings.default_provider).strip().lower()
        normalized_scene_count = max(1, int(scene_count)) if scene_count is not None else self.settings.default_scene_count
        normalized_target_duration_seconds = max(5, int(target_duration_seconds))
        if normalized_scene1_source == "upload" and not normalized_scene1_image:
            raise ValueError("scene1_first_frame_source=upload requires scene1_first_frame_image")
        self._validate_project_scene_duration_distribution(
            provider_name=normalized_provider,
            target_duration_seconds=normalized_target_duration_seconds,
            scene_count=normalized_scene_count,
        )
        project = Project(
            project_id=f"prj_{uuid4().hex[:10]}",
            title=title.strip() or "Untitled Video Workflow Project",
            raw_prompt=prompt.strip(),
            target_duration_seconds=normalized_target_duration_seconds,
            aspect_ratio=(aspect_ratio or self.settings.default_aspect_ratio).strip(),
            provider=normalized_provider,
            workflow_mode=normalized_workflow_mode,
            subtitle_mode=normalized_subtitle_mode,
            scene_count=max(1, int(scene_count)) if scene_count is not None else None,
            scene1_first_frame_source=normalized_scene1_source,
            scene1_first_frame_image=normalized_scene1_image,
            scene1_first_frame_prompt=normalized_scene1_prompt,
            scene1_first_frame_origin="user_upload" if normalized_scene1_source == "upload" and normalized_scene1_image else None,
            scene1_first_frame_status="pending",
        )
        project.add_event("project_created", "completed", "Project created")
        self._log(
            "project created",
            project_id=project.project_id,
            provider=project.provider,
            workflow_mode=project.workflow_mode,
            subtitle_mode=project.subtitle_mode,
            scene_count=project.scene_count or self.settings.default_scene_count,
            scene1_first_frame_source=project.scene1_first_frame_source,
        )
        return self.repo.save(project)

    def list_projects(self) -> list[Project]:
        return self.repo.list()

    def get_project(self, project_id: str) -> Project:
        return self.repo.load(project_id)

    def detect_language(self, project_id: str) -> Project:
        project = self.repo.load(project_id)
        if project.detected_input_language and project.dialogue_language and project.audio_language:
            return project

        result = detect_language_step(
            LanguageDetectInput(raw_prompt=project.raw_prompt),
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )
        project.detected_input_language = result.input_language
        project.dialogue_language = result.dialogue_language
        project.audio_language = result.audio_language
        project.language_detection_confidence = result.confidence
        project.language_detection_notes = result.notes
        project.add_event(
            "language_detect",
            "completed",
            "Input language detected for planning and audio alignment",
            details={
                "input_language": result.input_language,
                "dialogue_language": result.dialogue_language,
                "audio_language": result.audio_language,
                "confidence": result.confidence,
                "mixed_language": result.mixed_language,
                "notes": result.notes,
                "provider_metadata": result.provider_metadata,
            },
        )
        self._log(
            "language detected",
            project_id=project.project_id,
            input_language=result.input_language,
            dialogue_language=result.dialogue_language,
            audio_language=result.audio_language,
            confidence=result.confidence,
        )
        return self.repo.save(project)

    def prepare_character_anchors(self, project_id: str) -> Project:
        project = self.detect_language(project_id)
        if project.character_cards or any(event.step == "character_anchor" for event in project.events):
            return project

        project_guidance = build_project_guidance_context(
            step_name="character_anchor",
            target_duration_seconds=project.target_duration_seconds,
            scene_count=max(1, project.scene_count or self.settings.default_scene_count),
            input_language=project.detected_input_language,
            dialogue_language=project.dialogue_language,
            audio_language=project.audio_language,
            language_confidence=project.language_detection_confidence,
            scene1_first_frame_source=project.scene1_first_frame_source,
            scene1_first_frame_prompt=project.scene1_first_frame_prompt,
            scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
        )
        result = character_anchor_step(
            CharacterAnchorInput(
                raw_prompt=project.raw_prompt,
                optimized_prompt=project.optimized_prompt or "",
                input_language=project.detected_input_language,
                dialogue_language=project.dialogue_language,
                audio_language=project.audio_language,
                scene1_first_frame_source=project.scene1_first_frame_source,
                scene1_first_frame_image=project.scene1_first_frame_image,
                scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
                project_guidance_context=project_guidance,
            ),
            settings=self.settings,
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )
        project.character_cards = self._materialize_character_cards(project, result.characters)
        project.add_event(
            "character_anchor",
            "completed",
            "Character anchors prepared",
            details={
                "character_count": len(project.character_cards),
                "characters": [
                    {
                        "character_id": card.character_id,
                        "display_name": card.display_name,
                        "story_role": card.story_role,
                        "visual_description": card.visual_description,
                        "reference_image": card.reference_image,
                        "reference_prompt": card.reference_prompt,
                        "approval_status": card.approval_status,
                        "source": card.source,
                    }
                    for card in project.character_cards
                ],
                "provider_metadata": result.provider_metadata,
            },
        )
        self._log(
            "character anchors prepared",
            project_id=project.project_id,
            character_count=len(project.character_cards),
        )
        return self.repo.save(project)

    def list_provider_capabilities(self) -> list[dict[str, Any]]:
        return list_video_providers(self.settings)

    def optimize_prompt(self, project_id: str) -> Project:
        project = self.prepare_character_anchors(project_id)
        self._ensure_project_scene1_first_frame_context(project)
        project_guidance = build_project_guidance_context(
            step_name="prompt_optimize",
            target_duration_seconds=project.target_duration_seconds,
            scene_count=max(1, project.scene_count or self.settings.default_scene_count),
            input_language=project.detected_input_language,
            dialogue_language=project.dialogue_language,
            audio_language=project.audio_language,
            language_confidence=project.language_detection_confidence,
            scene1_first_frame_source=project.scene1_first_frame_source,
            scene1_first_frame_prompt=project.scene1_first_frame_prompt,
            scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
        )
        contract = PromptOptimizationInput(
            raw_prompt=project.raw_prompt,
            target_duration_seconds=project.target_duration_seconds,
            scene_count=max(1, project.scene_count or self.settings.default_scene_count),
            input_language=project.detected_input_language,
            dialogue_language=project.dialogue_language,
            audio_language=project.audio_language,
            scene1_first_frame_source=project.scene1_first_frame_source,
            scene1_first_frame_prompt=project.scene1_first_frame_prompt,
            scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
            project_guidance_context=project_guidance,
        )
        result = optimize_prompt_step(
            contract,
            settings=self.settings,
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )
        project.optimized_prompt = result.optimized_prompt
        project.status = "prompt_optimized"
        project.add_event(
            "prompt_optimize",
            "completed",
            "Prompt optimized for storyboard and scene generation",
            details={
                "optimized_prompt": result.optimized_prompt,
                "creative_intent": result.creative_intent,
                "style_guardrails": result.style_guardrails,
                "dialogue_lines": result.dialogue_lines,
                "planning_notes": result.planning_notes,
                "provider_metadata": result.provider_metadata,
            },
        )
        return self.repo.save(project)

    def plan_scenes(self, project_id: str) -> Project:
        project = self.prepare_character_anchors(project_id)
        self._ensure_project_scene1_first_frame_context(project)
        prompt_optimize_details = self._latest_event_details(project, "prompt_optimize")
        scene_count = max(1, project.scene_count or self.settings.default_scene_count)
        approximate_scene_durations = distribute_duration(project.target_duration_seconds, scene_count)
        story_plan_guidance = build_project_guidance_context(
            step_name="story_plan",
            target_duration_seconds=project.target_duration_seconds,
            scene_count=scene_count,
            input_language=project.detected_input_language,
            dialogue_language=project.dialogue_language,
            audio_language=project.audio_language,
            language_confidence=project.language_detection_confidence,
            creative_intent=str(prompt_optimize_details.get("creative_intent", "")),
            style_guardrails=list(prompt_optimize_details.get("style_guardrails", [])),
            planning_notes=str(prompt_optimize_details.get("planning_notes", "")),
            dialogue_lines=list(prompt_optimize_details.get("dialogue_lines", [])),
            scene1_first_frame_source=project.scene1_first_frame_source,
            scene1_first_frame_prompt=project.scene1_first_frame_prompt,
            scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
        )
        story_plan = story_plan_step(
            StoryPlanInput(
                raw_prompt=project.raw_prompt,
                optimized_prompt=project.optimized_prompt or project.raw_prompt,
                target_duration_seconds=project.target_duration_seconds,
                scene_count=scene_count,
                input_language=project.detected_input_language,
                dialogue_language=project.dialogue_language,
                audio_language=project.audio_language,
                project_guidance_context=story_plan_guidance,
                approximate_scene_durations=approximate_scene_durations,
                dialogue_lines=list(prompt_optimize_details.get("dialogue_lines", [])),
                creative_intent=str(prompt_optimize_details.get("creative_intent", "")),
                planning_notes=str(prompt_optimize_details.get("planning_notes", "")),
                scene1_first_frame_source=project.scene1_first_frame_source,
                scene1_first_frame_prompt=project.scene1_first_frame_prompt,
                scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
            ),
            settings=self.settings,
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )
        project.add_event(
            "story_plan",
            "completed",
            "Global story plan generated",
            details={
                "overall_story_arc": story_plan.overall_story_arc,
                "dialogue_strategy": story_plan.dialogue_strategy,
                "planning_notes": story_plan.planning_notes,
                "scene_roles": [
                    {
                        "scene_id": role.scene_id,
                        "scene_index": role.scene_index,
                        "duration_seconds": role.duration_seconds,
                        "role_label": role.role_label,
                        "narrative_purpose": role.narrative_purpose,
                        "story_advance_goal": role.story_advance_goal,
                        "pacing_intent": role.pacing_intent,
                        "information_load": role.information_load,
                        "speech_expectation": role.speech_expectation,
                    }
                    for role in story_plan.scene_roles
                ],
                "provider_metadata": story_plan.provider_metadata,
            },
        )
        project_guidance = build_project_guidance_context(
            step_name="scene_plan",
            target_duration_seconds=project.target_duration_seconds,
            scene_count=scene_count,
            input_language=project.detected_input_language,
            dialogue_language=project.dialogue_language,
            audio_language=project.audio_language,
            language_confidence=project.language_detection_confidence,
            creative_intent=str(prompt_optimize_details.get("creative_intent", "")),
            style_guardrails=list(prompt_optimize_details.get("style_guardrails", [])),
            planning_notes=str(prompt_optimize_details.get("planning_notes", "")),
            dialogue_lines=list(prompt_optimize_details.get("dialogue_lines", [])),
            scene1_first_frame_source=project.scene1_first_frame_source,
            scene1_first_frame_prompt=project.scene1_first_frame_prompt,
            scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
        )
        contract = ScenePlanningInput(
            optimized_prompt=project.optimized_prompt or project.raw_prompt,
            target_duration_seconds=project.target_duration_seconds,
            scene_count=scene_count,
            raw_prompt=project.raw_prompt,
            input_language=project.detected_input_language,
            dialogue_language=project.dialogue_language,
            audio_language=project.audio_language,
            dialogue_lines=list(prompt_optimize_details.get("dialogue_lines", [])),
            creative_intent=str(prompt_optimize_details.get("creative_intent", "")),
            planning_notes=str(prompt_optimize_details.get("planning_notes", "")),
            scene1_first_frame_source=project.scene1_first_frame_source,
            scene1_first_frame_prompt=project.scene1_first_frame_prompt,
            scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
            overall_story_arc=story_plan.overall_story_arc,
            dialogue_strategy=story_plan.dialogue_strategy,
            story_plan_scene_roles=story_plan.scene_roles,
            project_guidance_context=project_guidance,
        )
        result = plan_scenes_step(
            contract,
            settings=self.settings,
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )
        project.scenes = result.scenes
        cast_result = None
        if project.character_cards:
            cast_result = scene_character_cast_step(
                SceneCharacterCastInput(
                    raw_prompt=project.raw_prompt,
                    optimized_prompt=project.optimized_prompt or project.raw_prompt,
                    input_language=project.detected_input_language,
                    dialogue_language=project.dialogue_language,
                    audio_language=project.audio_language,
                    overall_story_arc=story_plan.overall_story_arc,
                    character_cards=[
                        {
                            "character_id": card.character_id,
                            "display_name": card.display_name,
                            "story_role": card.story_role,
                            "visual_description": card.visual_description,
                            "approval_status": card.approval_status,
                        }
                        for card in project.character_cards
                    ],
                    scenes=[
                        SceneCharacterCastSceneInput(
                            scene_id=scene.scene_id,
                            scene_index=scene.index,
                            title=scene.title,
                            narrative=scene.narrative,
                            visual_goal=scene.visual_goal,
                            continuity_notes=scene.continuity_notes,
                            duration_seconds=scene.duration_seconds,
                            story_role=scene.story_role,
                            story_purpose=scene.story_purpose,
                            story_advance_goal=scene.story_advance_goal,
                            pacing_intent=scene.pacing_intent,
                        )
                        for scene in project.scenes
                    ],
                    project_guidance_context=build_project_guidance_context(
                        step_name="scene_character_cast",
                        target_duration_seconds=project.target_duration_seconds,
                        scene_count=scene_count,
                        input_language=project.detected_input_language,
                        dialogue_language=project.dialogue_language,
                        audio_language=project.audio_language,
                        language_confidence=project.language_detection_confidence,
                        character_cards=project.character_cards,
                        scene1_first_frame_source=project.scene1_first_frame_source,
                        scene1_first_frame_prompt=project.scene1_first_frame_prompt,
                        scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
                    ),
                ),
                settings=self.settings,
                trace_logger=self.trace_logger,
                project_id=project.project_id,
            )
            cast_map = {item.scene_id: item for item in cast_result.scenes}
            for scene in project.scenes:
                participation = cast_map.get(scene.scene_id)
                if participation is None:
                    continue
                scene.participating_character_ids = list(participation.participating_character_ids)
                scene.primary_character_id = participation.primary_character_id
                scene.character_presence_notes = participation.character_presence_notes
        for scene in project.scenes:
            scene.status = "planned"
            scene.review_status = "pending_generation"
            if scene.index == 1:
                scene.first_frame_source = project.scene1_first_frame_source
                scene.first_frame_image = project.scene1_first_frame_image
                scene.first_frame_prompt = project.scene1_first_frame_prompt
                scene.first_frame_origin = project.scene1_first_frame_origin
                scene.first_frame_status = project.scene1_first_frame_status
                scene.first_frame_analysis = dict(project.scene1_first_frame_analysis)
                scene.first_frame_job = dict(project.scene1_first_frame_job)
            else:
                scene.first_frame_source = "continuity"
                scene.first_frame_image = None
                scene.first_frame_prompt = ""
                scene.first_frame_origin = "previous_scene_tail"
                scene.first_frame_status = "pending"
        self._prepare_initial_first_frames(project)
        scene_index_map = {scene.scene_id: scene for scene in project.scenes}
        self._refresh_scene_prompts_parallel(project, project.scenes, scene_index_map)
        project.status = "ready_for_scene_generation" if project.workflow_mode == "hitl" else "scenes_planned"
        project.add_event(
            "scene_plan",
            "completed",
            "Scene plan generated",
            details={
                "scene_count": len(project.scenes),
                "scene_ids": [scene.scene_id for scene in project.scenes],
                "scenes": [
                    {
                        "scene_id": scene.scene_id,
                        "title": scene.title,
                        "story_role": scene.story_role,
                        "story_purpose": scene.story_purpose,
                        "story_advance_goal": scene.story_advance_goal,
                        "pacing_intent": scene.pacing_intent,
                        "information_load": scene.information_load,
                        "speech_expectation": scene.speech_expectation,
                        "narrative": scene.narrative,
                        "visual_goal": scene.visual_goal,
                        "spoken_text": scene.spoken_text,
                        "speech_mode": scene.speech_mode,
                        "delivery_notes": scene.delivery_notes,
                        "duration_seconds": scene.duration_seconds,
                    }
                    for scene in project.scenes
                ],
                "planning_notes": result.planning_notes,
                "provider_metadata": result.provider_metadata,
                "scene1_first_frame_source": project.scene1_first_frame_source,
            },
        )
        if cast_result is not None:
            project.add_event(
                "scene_character_cast",
                "completed",
                "Scene-level character participation assigned",
                details={
                    "scenes": [
                        {
                            "scene_id": scene.scene_id,
                            "participating_character_ids": scene.participating_character_ids,
                            "primary_character_id": scene.primary_character_id,
                            "character_presence_notes": scene.character_presence_notes,
                        }
                        for scene in project.scenes
                    ],
                    "provider_metadata": cast_result.provider_metadata,
                },
            )
        return self.repo.save(project)

    def upload_storyboards(self, project_id: str, items: list[dict[str, Any]]) -> Project:
        project = self.repo.load(project_id)
        contract = StoryboardUploadInput.from_payloads(items)
        updated_scene_ids: list[str] = []
        for binding in contract.items:
            scene = self._find_scene(
                project.scenes,
                {"scene_id": binding.scene_id, "scene_index": binding.scene_index},
            )
            if scene is None:
                continue
            stale_reasons: list[str] = []
            if binding.first_frame_source is not None:
                if binding.first_frame_source != scene.first_frame_source:
                    stale_reasons.append("first_frame_source_changed")
                scene.first_frame_source = binding.first_frame_source
                if binding.first_frame_source != "upload":
                    scene.first_frame_image = None
                    scene.first_frame_analysis = {}
                    scene.first_frame_job = {}
                    if binding.first_frame_source == "continuity":
                        scene.first_frame_origin = "previous_scene_tail"
                    elif binding.first_frame_source == "auto_generate":
                        scene.first_frame_origin = None
                        scene.first_frame_status = "pending"
            if binding.first_frame_image:
                if binding.first_frame_image != scene.first_frame_image:
                    stale_reasons.append("first_frame_image_changed")
                scene.first_frame_image = binding.first_frame_image
                scene.first_frame_analysis = {}
                scene.first_frame_job = {}
                if binding.first_frame_source is None:
                    scene.first_frame_source = "upload"
                scene.first_frame_origin = "user_upload"
                scene.first_frame_status = "ready"
            if binding.reference_image:
                scene.reference_image = binding.reference_image
            scene.storyboard_notes = binding.storyboard_notes
            self._refresh_scene_prompt_after_upstream_change(
                project,
                scene,
                {item.scene_id: item for item in project.scenes},
                stale_reasons=stale_reasons,
            )
            updated_scene_ids.append(scene.scene_id)
        output = StoryboardUploadOutput(updated_scene_ids=updated_scene_ids)
        if output.updated_scene_ids:
            project.status = (
                "ready_for_scene_generation"
                if project.workflow_mode == "hitl"
                else "storyboards_uploaded"
            )
        project.add_event(
            "storyboard_upload",
            "completed",
            "Storyboard assets updated",
            details={
                "updated_scenes": len(output.updated_scene_ids),
                "scene_ids": output.updated_scene_ids,
            },
        )
        self.trace_logger.append(
            project.project_id,
            event_type="storyboard_upload",
            step="storyboard_upload",
            status="completed",
            actor="user",
            details={"scene_ids": output.updated_scene_ids, "items": items},
        )
        return self.repo.save(project)

    def generate_scenes(self, project_id: str) -> Project:
        project = self._ensure_project_ready_for_scene_flow(project_id)
        if not project.scenes:
            raise ValueError("No scenes found. Run scene planning first.")
        project.status = "scene_videos_generating"
        self.repo.save(project)

        for scene in list(project.scenes):
            self._generate_scene_sync(project_id, scene.scene_id, requires_review=False)

        project = self.repo.load(project_id)
        project.status = "scene_videos_generated"
        return self.repo.save(project)

    def start_scene_generation(self, project_id: str, scene_id: str) -> Project:
        project = self._ensure_project_ready_for_scene_flow(project_id)
        if project.workflow_run_job and project.workflow_run_job.status in {"queued", "running"}:
            raise ValueError("Workflow run is active. Wait for it to finish before manual scene generation.")
        if self._get_scene_future(project_id) is not None:
            raise ValueError("Another scene generation is already active for this project.")

        scene = self._require_scene(project, scene_id)
        self._validate_scene_generation_preconditions(project, scene)
        contract = self._build_scene_generation_input(
            project,
            scene,
            {item.scene_id: item for item in project.scenes},
        )
        job = self._queue_scene_video_job(project, scene, contract)
        project.add_event(
            "scene_video_generate",
            "queued",
            f"Scene {scene.index} queued for generation",
            details={"scene_id": scene.scene_id, "job_id": job.job_id},
        )
        self.trace_logger.append(
            project.project_id,
            event_type="scene_generation_requested",
            step="scene_video_generate",
            status="queued",
            actor="user",
            details={
                "scene_id": scene.scene_id,
                "job_id": job.job_id,
                "provider_prompt_snapshot": contract.prompt,
                "prompt_snapshot": contract.prompt,
                "first_frame_source": contract.first_frame_source,
                "has_first_frame_image": bool(contract.first_frame_image),
                "has_reference_image": bool(contract.reference_image),
                "has_continuity_image": bool(contract.continuity_image),
            },
        )
        self._log(
            "scene generation queued",
            project_id=project.project_id,
            scene_id=scene.scene_id,
            scene_index=scene.index,
            job_id=job.job_id,
        )
        self.repo.save(project)

        future = self._executor.submit(self._execute_scene_generation, project_id, scene.scene_id, job.job_id)
        with self._futures_lock:
            self._scene_futures[project_id] = future
        return self.repo.load(project_id)

    def approve_scene(self, project_id: str, scene_id: str) -> Project:
        project = self.repo.load(project_id)
        if project.workflow_mode != "hitl":
            raise ValueError("Scene approval is only available for hitl workflow mode.")
        scene = self._require_scene(project, scene_id)
        if scene.status != "pending_review" or not scene.video_rel_path:
            raise ValueError("Scene is not waiting for review approval.")

        scene.status = "approved"
        scene.review_status = "approved"
        self._sync_hitl_project_status(project)
        project.add_event(
            "scene_review",
            "completed",
            f"Scene {scene.index} approved",
            details={"scene_id": scene.scene_id, "video_rel_path": scene.video_rel_path},
        )
        self._log(
            "scene approved",
            project_id=project.project_id,
            scene_id=scene.scene_id,
            scene_index=scene.index,
        )
        self.trace_logger.append(
            project.project_id,
            event_type="scene_approved",
            step="scene_review",
            status="completed",
            actor="user",
            details={"scene_id": scene.scene_id, "scene_index": scene.index},
        )
        return self.repo.save(project)

    def update_scene_prompt(self, project_id: str, scene_id: str, payload: dict[str, Any]) -> Project:
        project = self.repo.load(project_id)
        scene = self._require_scene(project, scene_id)
        contract = ScenePromptUpdateInput.from_payload(payload)
        contract.validate()
        self._validate_scene_prompt_update(project, scene)

        previous_prompt = scene.prompt
        scene.prompt = contract.prompt
        scene.approved_prompt = ""
        self._clear_scene_prompt_stale(scene)
        project.add_event(
            "scene_prompt_update",
            "completed",
            f"Scene {scene.index} prompt updated",
            details={
                "scene_id": scene.scene_id,
                "previous_prompt": previous_prompt,
                "prompt_draft": scene.prompt,
                "prompt_stale": scene.prompt_stale,
            },
        )
        self._log(
            "scene prompt updated",
            project_id=project.project_id,
            scene_id=scene.scene_id,
            scene_index=scene.index,
        )
        self.trace_logger.append(
            project.project_id,
            event_type="scene_prompt_update",
            step="scene_prompt_update",
            status="completed",
            actor="user",
            details={
                "scene_id": scene.scene_id,
                "previous_prompt": previous_prompt,
                "prompt_draft": scene.prompt,
            },
        )
        return self.repo.save(project)

    def revise_scene_prompt(self, project_id: str, scene_id: str, payload: dict[str, Any]) -> Project:
        project = self.repo.load(project_id)
        scene = self._require_scene(project, scene_id)
        self._validate_scene_prompt_update(project, scene)
        contract = ScenePromptRevisionRequest.from_payload(payload)
        contract.validate()

        if contract.scope == "opening_still_and_prompt":
            if scene.index != 1:
                raise ValueError("opening_still_and_prompt is only available for scene-01")
            if scene.first_frame_source != "auto_generate":
                raise ValueError("opening_still_and_prompt requires scene-01 auto-generated first frame")

        revision = self._run_scene_prompt_revision(
            project,
            scene,
            feedback=contract.feedback,
            scope=contract.scope,
        )
        if revision.outcome == "requires_start_state_edit":
            raise ValueError(
                revision.rejection_reason
                or "This feedback changes the scene start state and cannot be applied through prompt revision."
            )

        previous_prompt = scene.prompt
        previous_first_frame_prompt = scene.first_frame_prompt

        if contract.scope == "opening_still_and_prompt":
            scene.first_frame_prompt = revision.revised_first_frame_prompt
            scene.first_frame_image = None
            scene.first_frame_analysis = {}
            scene.first_frame_status = "pending"
            scene.first_frame_origin = None
            scene.first_frame_job = {}
            if scene.index == 1:
                project.scene1_first_frame_prompt = scene.first_frame_prompt
                project.scene1_first_frame_image = None
                project.scene1_first_frame_analysis = {}
                project.scene1_first_frame_status = "pending"
                project.scene1_first_frame_origin = None
                project.scene1_first_frame_job = {}
            prepared = prepare_first_frame_step(
                FirstFramePrepareInput(
                    project_id=project.project_id,
                    provider=project.provider,
                    scene_id=scene.scene_id,
                    scene_index=scene.index,
                    prompt=scene.first_frame_prompt,
                    aspect_ratio=project.aspect_ratio,
                ),
                settings=self.settings,
                trace_logger=self.trace_logger,
                project_id=project.project_id,
            )
            scene.first_frame_image = prepared.first_frame_image
            scene.first_frame_prompt = prepared.first_frame_prompt
            scene.first_frame_origin = prepared.first_frame_origin
            scene.first_frame_status = prepared.first_frame_status
            scene.first_frame_job = {
                "status": "completed",
                "step": "first_frame_prepare",
            } | prepared.provider_metadata
            if scene.index == 1:
                project.scene1_first_frame_image = scene.first_frame_image
                project.scene1_first_frame_prompt = scene.first_frame_prompt
                project.scene1_first_frame_origin = scene.first_frame_origin
                project.scene1_first_frame_status = scene.first_frame_status
                project.scene1_first_frame_job = dict(scene.first_frame_job)
            self._ensure_first_frame_analysis(
                project,
                scene,
                first_frame_image=scene.first_frame_image,
            )
            scene_index_map = {item.scene_id: item for item in project.scenes}
            self._refresh_scene_prompt(project, scene, scene_index_map)
            revision = self._run_scene_prompt_revision(
                project,
                scene,
                feedback=contract.feedback,
                scope="prompt_only",
            )
            if revision.outcome == "requires_start_state_edit":
                raise ValueError(
                    revision.rejection_reason
                    or "This feedback still conflicts with the updated opening state."
                )

        scene.prompt = revision.revised_prompt
        scene.approved_prompt = ""
        self._clear_scene_prompt_stale(scene)
        project.add_event(
            "scene_prompt_revise",
            "completed",
            f"Scene {scene.index} prompt revised from feedback",
            details={
                "scene_id": scene.scene_id,
                "scope": contract.scope,
                "feedback": contract.feedback,
                "previous_prompt": previous_prompt,
                "revised_prompt": scene.prompt,
                "previous_first_frame_prompt": previous_first_frame_prompt,
                "revised_first_frame_prompt": scene.first_frame_prompt if contract.scope == "opening_still_and_prompt" else "",
                "change_summary": revision.change_summary,
                "provider_metadata": revision.provider_metadata,
            },
        )
        self.trace_logger.append(
            project.project_id,
            event_type="scene_prompt_revise",
            step="scene_prompt_revise",
            status="completed",
            actor="user",
            details={
                "scene_id": scene.scene_id,
                "scene_index": scene.index,
                "scope": contract.scope,
                "feedback": contract.feedback,
                "change_summary": revision.change_summary,
            },
        )
        self._log(
            "scene prompt revised",
            project_id=project.project_id,
            scene_id=scene.scene_id,
            scene_index=scene.index,
            scope=contract.scope,
        )
        return self.repo.save(project)

    def approve_character_anchor(self, project_id: str, character_id: str) -> Project:
        project = self.repo.load(project_id)
        card = self._require_character_card(project, character_id)
        card.approval_status = "approved"
        project.add_event(
            "character_anchor_review",
            "completed",
            f"Character anchor {card.display_name} approved",
            details={"character_id": card.character_id, "display_name": card.display_name},
        )
        self.trace_logger.append(
            project.project_id,
            event_type="character_anchor_approved",
            step="character_anchor_review",
            status="completed",
            actor="user",
            details={"character_id": card.character_id, "display_name": card.display_name},
        )
        return self.repo.save(project)

    def regenerate_character_anchor(self, project_id: str, character_id: str) -> Project:
        project = self.repo.load(project_id)
        card = self._require_character_card(project, character_id)
        prepared = prepare_first_frame_step(
            FirstFramePrepareInput(
                project_id=project.project_id,
                provider=project.provider,
                scene_id=f"character-regenerated-{card.character_id}",
                scene_index=1,
                prompt=card.reference_prompt or card.visual_description or card.display_name,
                aspect_ratio=project.aspect_ratio,
                model=self.settings.image_character_model,
            ),
            settings=self.settings,
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )
        card.reference_image = prepared.first_frame_image
        card.reference_prompt = prepared.first_frame_prompt
        card.source = "generated"
        card.approval_status = "pending"
        project.add_event(
            "character_anchor_regenerate",
            "completed",
            f"Character anchor {card.display_name} regenerated",
            details={"character_id": card.character_id, "display_name": card.display_name},
        )
        return self.repo.save(project)

    def replace_character_anchor(
        self,
        project_id: str,
        character_id: str,
        *,
        reference_image: str,
    ) -> Project:
        project = self.repo.load(project_id)
        card = self._require_character_card(project, character_id)
        card.reference_image = reference_image.strip()
        card.source = "uploaded"
        card.approval_status = "pending"
        project.add_event(
            "character_anchor_replace",
            "completed",
            f"Character anchor {card.display_name} replaced",
            details={"character_id": card.character_id, "display_name": card.display_name},
        )
        self.trace_logger.append(
            project.project_id,
            event_type="character_anchor_replaced",
            step="character_anchor_review",
            status="completed",
            actor="user",
            details={"character_id": card.character_id, "display_name": card.display_name},
        )
        return self.repo.save(project)

    def compose_video(self, project_id: str) -> Project:
        project = self.repo.load(project_id)
        if project.workflow_mode == "hitl" and any(scene.status != "approved" for scene in project.scenes):
            raise ValueError("Approve all scenes before composing in hitl workflow mode.")
        clips = []
        for scene in project.scenes:
            if not scene.video_rel_path:
                raise ValueError(f"Scene {scene.scene_id} has no generated video")
            clips.append(self.settings.artifact_dir / scene.video_rel_path)
        if not clips:
            raise ValueError("No scene videos to compose")

        output_dir = self.settings.artifact_dir / project.project_id / "delivery"
        output_dir.mkdir(parents=True, exist_ok=True)
        contract = FinalCompositionInput(
            project_id=project.project_id,
            scene_ids=[scene.scene_id for scene in project.scenes],
            clip_paths=clips,
            output_rel_path=f"{project.project_id}/delivery/final.mp4",
        )
        job = self._start_final_video_job(project, contract)
        self.repo.save(project)

        try:
            compose_metadata = compose_clips(
                ffmpeg_bin=self.settings.ffmpeg_bin,
                ffprobe_bin=self.settings.ffprobe_bin,
                clip_paths=contract.clip_paths,
                concat_list_path=output_dir / "concat.txt",
                output_path=self.settings.artifact_dir / contract.output_rel_path,
                boundary_trim_seconds=self.settings.composer_boundary_trim_seconds,
                video_crossfade_seconds=self.settings.composer_video_crossfade_seconds,
                audio_crossfade_seconds=self.settings.composer_audio_crossfade_seconds,
            )
        except Exception as exc:
            self._mark_final_video_failed(project, job, exc)
            self.repo.save(project)
            raise

        result = FinalCompositionOutput(
            final_video_rel_path=contract.output_rel_path,
            metadata={
                "clip_count": len(contract.clip_paths),
                "scene_ids": contract.scene_ids,
                "compose": compose_metadata,
            },
        )
        self._apply_final_composition_output(project, job, result)
        saved = self.repo.save(project)
        self._queue_subtitle_sidecar(saved.project_id)
        return self.repo.load(project_id)

    def run_workflow(self, project_id: str) -> Project:
        return self._execute_workflow_run(project_id)

    def start_workflow_run(self, project_id: str) -> Project:
        project = self.repo.load(project_id)
        current_job = project.workflow_run_job
        if current_job and current_job.status in {"queued", "running"}:
            raise ValueError(f"Workflow run already active: {current_job.job_id}")

        attempt_count = current_job.attempt_count if current_job else 0
        project.workflow_run_job = WorkflowRunJob(
            job_id=f"wfr_{uuid4().hex[:10]}",
            status="queued",
            attempt_count=attempt_count + 1,
            queued_at=utc_now(),
            metadata={
                "provider": project.provider,
                "scene_count": project.scene_count or self.settings.default_scene_count,
                "workflow_mode": project.workflow_mode,
            },
        )
        project.status = "workflow_queued"
        project.add_event(
            "workflow_run",
            "queued",
            "Workflow run queued for background execution",
            details={"job_id": project.workflow_run_job.job_id},
        )
        self._log(
            "workflow queued",
            project_id=project.project_id,
            job_id=project.workflow_run_job.job_id,
            provider=project.provider,
        )
        self.repo.save(project)

        future = self._executor.submit(
            self._execute_workflow_run,
            project_id,
            project.workflow_run_job.job_id,
        )
        with self._futures_lock:
            self._workflow_futures[project_id] = future
        return self.repo.load(project_id)

    def wait_for_workflow_run(
        self,
        project_id: str,
        *,
        timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 0.25,
    ) -> Project:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            project = self.repo.load(project_id)
            workflow_run_job = project.workflow_run_job
            if workflow_run_job and workflow_run_job.status == "completed":
                return project
            if workflow_run_job and workflow_run_job.status == "failed":
                raise RuntimeError(workflow_run_job.error_message or "Workflow run failed")

            future = self._get_workflow_future(project_id)
            if future and future.done():
                return future.result()
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for workflow run for project {project_id}")

    def wait_for_subtitle_job(
        self,
        project_id: str,
        *,
        timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 0.25,
    ) -> Project:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            project = self.repo.load(project_id)
            subtitle_job = project.subtitle_job
            if project.subtitle_mode == "disabled" or self._subtitle_eligibility_reason(project) != "eligible":
                return project
            if subtitle_job and subtitle_job.status in {"completed", "failed", "skipped"}:
                return project

            future = self._get_subtitle_future(project_id)
            if future and future.done():
                return future.result()
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for subtitle job for project {project_id}")

    def wait_for_subtitle_burn_job(
        self,
        project_id: str,
        *,
        timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 0.25,
    ) -> Project:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            project = self.repo.load(project_id)
            subtitle_burn_job = project.subtitle_burn_job
            if subtitle_burn_job and subtitle_burn_job.status in {"completed", "failed"}:
                return project

            future = self._get_subtitle_burn_future(project_id)
            if future and future.done():
                return future.result()
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for subtitle burn export for project {project_id}")

    def build_delivery_package(self, project_id: str) -> Path:
        project = self.repo.load(project_id)
        if not project.final_video_rel_path:
            raise ValueError("Final video is not ready.")
        if not project.subtitle_srt_rel_path and not project.subtitle_vtt_rel_path:
            raise ValueError("Subtitle files are not ready.")

        delivery_dir = self.settings.artifact_dir / project.project_id / "delivery"
        delivery_dir.mkdir(parents=True, exist_ok=True)
        package_path = delivery_dir / "final_delivery.zip"

        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            final_video_path = self.settings.artifact_dir / str(project.final_video_rel_path)
            archive.write(final_video_path, arcname="final.mp4")
            if project.subtitle_srt_rel_path:
                archive.write(
                    self.settings.artifact_dir / str(project.subtitle_srt_rel_path),
                    arcname="final.srt",
                )
            if project.subtitle_vtt_rel_path:
                archive.write(
                    self.settings.artifact_dir / str(project.subtitle_vtt_rel_path),
                    arcname="final.vtt",
                )

        return package_path

    def export_subtitled_video(self, project_id: str) -> Project:
        project = self.repo.load(project_id)
        if not project.final_video_rel_path:
            raise ValueError("Final video is not ready.")
        if not project.subtitle_srt_rel_path:
            raise ValueError("Subtitle files are not ready.")

        current_job = project.subtitle_burn_job
        if current_job and current_job.status in {"queued", "running"}:
            raise ValueError(f"Subtitled video export already active: {current_job.job_id}")

        if project.subtitle_burned_video_rel_path:
            (self.settings.artifact_dir / str(project.subtitle_burned_video_rel_path)).unlink(missing_ok=True)
            project.subtitle_burned_video_rel_path = None

        job = SubtitleBurnJob(
            job_id=f"sbj_{uuid4().hex[:10]}",
            status="queued",
            provider="ffmpeg",
            metadata={"source_video_rel_path": project.final_video_rel_path},
        )
        project.subtitle_burn_job = job
        project.add_event(
            "subtitle_burn",
            "queued",
            "Subtitled video export queued",
            details={"job_id": job.job_id, "provider": job.provider},
        )
        self.repo.save(project)
        future = self._executor.submit(self._execute_subtitle_burn_export, project_id, job.job_id)
        with self._futures_lock:
            self._subtitle_burn_futures[project_id] = future
        return self.repo.load(project_id)

    def serialize_project(self, project: Project, *, base_url: str | None = None) -> dict[str, Any]:
        payload = project.to_dict()
        payload["subtitle_mode"] = self._public_subtitle_mode(project.subtitle_mode)
        if base_url:
            payload["final_video_url"] = self._artifact_url(project.final_video_rel_path, base_url)
            payload["subtitle_srt_url"] = self._artifact_url(project.subtitle_srt_rel_path, base_url)
            payload["subtitle_vtt_url"] = self._artifact_url(project.subtitle_vtt_rel_path, base_url)
            payload["subtitle_burned_video_url"] = self._artifact_url(project.subtitle_burned_video_rel_path, base_url)
            for card in payload.get("character_cards", []):
                card["reference_image_url"] = self._first_frame_url(card.get("reference_image"), base_url)
            for scene in payload.get("scenes", []):
                scene["video_url"] = self._artifact_url(scene.get("video_rel_path"), base_url)
                scene["final_frame_url"] = self._artifact_url(scene.get("final_frame_rel_path"), base_url)
                scene["first_frame_url"] = self._first_frame_url(scene.get("first_frame_image"), base_url)
        payload["subtitle"] = self._serialize_subtitle_state(project, base_url=base_url)
        payload["hitl"] = self._serialize_hitl_state(project)
        scene_map = {scene.scene_id: scene for scene in project.scenes}
        for scene_payload in payload.get("scenes", []):
            scene = scene_map.get(str(scene_payload.get("scene_id", "")))
            if scene is None:
                continue
            scene_payload["available_actions"] = self._available_scene_actions(project, scene)
        return payload

    def _normalize_scene1_first_frame_source(self, source: str | None) -> str:
        normalized = str(source or "auto_generate").strip().lower()
        if normalized not in {"upload", "auto_generate"}:
            raise ValueError("scene1_first_frame_source must be upload or auto_generate")
        return normalized

    def _normalize_subtitle_mode(self, subtitle_mode: str | None) -> str:
        normalized = str(subtitle_mode or "disabled").strip().lower()
        if normalized == "sidecar":
            return "enabled"
        if normalized not in {"disabled", "enabled"}:
            raise ValueError("subtitle_mode must be disabled or enabled")
        return normalized

    def _public_subtitle_mode(self, subtitle_mode: str | None) -> str:
        normalized = str(subtitle_mode or "disabled").strip().lower()
        return "disabled" if normalized == "disabled" else "enabled"

    def _normalize_optional_string(self, value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _normalize_scene1_first_frame_prompt(
        self,
        *,
        prompt: str,
        source: str,
        first_frame_prompt: str | None,
    ) -> str:
        normalized = self._normalize_optional_string(first_frame_prompt)
        if source != "auto_generate":
            return ""
        return normalized or prompt.strip()

    def _artifact_url(self, rel_path: str | None, base_url: str) -> str | None:
        if not rel_path:
            return None
        return f"{base_url.rstrip('/')}/artifacts/{rel_path}"

    def _project_has_spoken_dialogue(self, project: Project) -> bool:
        return any(
            str(scene.speech_mode or "").strip().lower() != "none" and str(scene.spoken_text or "").strip()
            for scene in project.scenes
        )

    def _subtitle_eligibility_reason(self, project: Project) -> str:
        if project.subtitle_mode == "disabled":
            return "subtitle_mode_disabled"
        if not self._project_has_spoken_dialogue(project):
            return "no_spoken_dialogue"
        return "eligible"

    def _serialize_subtitle_state(self, project: Project, *, base_url: str | None = None) -> dict[str, Any]:
        reason = self._subtitle_eligibility_reason(project)
        eligible = reason == "eligible"
        srt_url = self._artifact_url(project.subtitle_srt_rel_path, base_url) if base_url else None
        vtt_url = self._artifact_url(project.subtitle_vtt_rel_path, base_url) if base_url else None
        burned_video_url = self._artifact_url(project.subtitle_burned_video_rel_path, base_url) if base_url else None
        subtitle_job = project.subtitle_job
        subtitle_burn_job = project.subtitle_burn_job
        subtitle_ready = bool(project.subtitle_srt_rel_path or project.subtitle_vtt_rel_path)
        public_mode = self._public_subtitle_mode(project.subtitle_mode)

        if project.subtitle_mode == "disabled":
            status = "disabled"
        elif subtitle_ready:
            status = "completed"
        elif subtitle_job and subtitle_job.status:
            status = subtitle_job.status
        elif not eligible:
            status = "not_applicable"
        elif project.final_video_rel_path:
            status = "pending"
        else:
            status = "planned"

        if project.subtitle_mode == "disabled":
            burn_status = "disabled"
        elif project.subtitle_burned_video_rel_path:
            burn_status = "completed"
        elif subtitle_burn_job and subtitle_burn_job.status:
            burn_status = subtitle_burn_job.status
        else:
            burn_status = "idle"

        return {
            "mode": public_mode,
            "enabled": project.subtitle_mode != "disabled",
            "eligible": eligible,
            "status": status,
            "reason": reason,
            "srt_rel_path": project.subtitle_srt_rel_path,
            "vtt_rel_path": project.subtitle_vtt_rel_path,
            "srt_url": srt_url,
            "vtt_url": vtt_url,
            "package_url": f"{base_url.rstrip('/')}/projects/{project.project_id}/delivery-package" if base_url and subtitle_ready else None,
            "language": project.audio_language or project.dialogue_language or project.detected_input_language or "",
            "job_id": subtitle_job.job_id if subtitle_job else None,
            "provider": subtitle_job.provider if subtitle_job else None,
            "error_message": subtitle_job.error_message if subtitle_job else None,
            "burned_video_rel_path": project.subtitle_burned_video_rel_path,
            "burned_video_url": burned_video_url,
            "burn_status": burn_status,
            "burn_job_id": subtitle_burn_job.job_id if subtitle_burn_job else None,
            "burn_error_message": subtitle_burn_job.error_message if subtitle_burn_job else None,
        }

    def _first_frame_url(self, image_ref: str | None, base_url: str) -> str | None:
        if not image_ref:
            return None
        if image_ref.startswith("data:"):
            return image_ref
        candidate = Path(image_ref).expanduser()
        artifact_root = self.settings.artifact_dir.resolve()
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if artifact_root in resolved.parents:
                return self._artifact_url(str(resolved.relative_to(artifact_root)).replace("\\", "/"), base_url)
        else:
            rel_candidate = image_ref.lstrip("/")
            if (artifact_root / rel_candidate).exists():
                return self._artifact_url(rel_candidate, base_url)
        return None

    def _prepare_initial_first_frames(self, project: Project) -> None:
        for scene in project.scenes:
            if scene.first_frame_source != "auto_generate":
                continue
            prepared_prompt = self._compose_scene_auto_generated_first_frame_prompt(project, scene)
            if not self._should_prepare_scene_auto_generated_first_frame(
                project,
                scene,
                prepared_prompt=prepared_prompt,
            ):
                continue
            prepared = prepare_first_frame_step(
                FirstFramePrepareInput(
                    project_id=project.project_id,
                    provider=project.provider,
                    scene_id=scene.scene_id,
                    scene_index=scene.index,
                    prompt=prepared_prompt,
                    aspect_ratio=project.aspect_ratio,
                ),
                settings=self.settings,
                trace_logger=self.trace_logger,
                project_id=project.project_id,
            )
            scene.first_frame_image = prepared.first_frame_image
            scene.first_frame_prompt = prepared.first_frame_prompt
            scene.first_frame_origin = prepared.first_frame_origin
            scene.first_frame_status = prepared.first_frame_status
            scene.first_frame_analysis = {}
            scene.first_frame_job = {
                "status": "completed",
                "step": "first_frame_prepare",
            } | prepared.provider_metadata
            if scene.index == 1:
                project.scene1_first_frame_image = prepared.first_frame_image
                project.scene1_first_frame_prompt = prepared.first_frame_prompt
                project.scene1_first_frame_origin = prepared.first_frame_origin
                project.scene1_first_frame_status = prepared.first_frame_status
                project.scene1_first_frame_analysis = {}
                project.scene1_first_frame_job = dict(scene.first_frame_job)

    def _ensure_project_scene1_first_frame_context(self, project: Project) -> None:
        if project.scene1_first_frame_source == "auto_generate" and not project.scene1_first_frame_image:
            prepared_prompt = self._compose_project_opening_first_frame_prompt(project)
            prepared = prepare_first_frame_step(
                FirstFramePrepareInput(
                    project_id=project.project_id,
                    provider=project.provider,
                    scene_id="scene-01",
                    scene_index=1,
                    prompt=prepared_prompt,
                    aspect_ratio=project.aspect_ratio,
                ),
                settings=self.settings,
                trace_logger=self.trace_logger,
                project_id=project.project_id,
            )
            project.scene1_first_frame_image = prepared.first_frame_image
            project.scene1_first_frame_prompt = prepared.first_frame_prompt
            project.scene1_first_frame_origin = prepared.first_frame_origin
            project.scene1_first_frame_status = prepared.first_frame_status
            project.scene1_first_frame_job = {
                "status": "completed",
                "step": "first_frame_prepare",
            } | prepared.provider_metadata
        if not project.scene1_first_frame_image:
            return
        if project.scene1_first_frame_analysis:
            if project.scene1_first_frame_status != "ready":
                project.scene1_first_frame_status = "ready"
            return
        try:
            analysis = analyze_first_frame_step(
                FirstFrameAnalyzeInput(
                    scene_id="scene-01",
                    scene_index=1,
                    first_frame_source=project.scene1_first_frame_source,
                    image_input=project.scene1_first_frame_image,
                    title="Opening scene",
                    narrative=project.raw_prompt,
                    visual_goal="",
                ),
                settings=self.settings,
                trace_logger=self.trace_logger,
                project_id=project.project_id,
            )
        except Exception as exc:
            project.scene1_first_frame_analysis = {}
            project.scene1_first_frame_status = "analysis_failed"
            project.scene1_first_frame_job = {
                "status": "failed",
                "step": "first_frame_analyze",
                "error": str(exc),
            }
            project.add_event(
                "first_frame_analyze",
                "failed",
                "Scene 1 first-frame analysis failed; continuing without image analysis",
                details={"error": str(exc)},
            )
            self._log(
                "scene1 first-frame analysis failed",
                project_id=project.project_id,
                error=str(exc),
            )
            return
        project.scene1_first_frame_analysis = analysis.to_dict()
        project.scene1_first_frame_status = "ready"
        project.scene1_first_frame_job = {
            "status": "completed",
            "provider": analysis.provider_metadata.get("provider"),
            "model": analysis.provider_metadata.get("model"),
            "step": "first_frame_analyze",
        }
        if project.scene1_first_frame_source == "upload" and not project.scene1_first_frame_origin:
            project.scene1_first_frame_origin = "user_upload"
        elif project.scene1_first_frame_source == "auto_generate" and not project.scene1_first_frame_origin:
            project.scene1_first_frame_origin = "generated"

    def _materialize_character_cards(self, project: Project, candidates: list[Any]) -> list[CharacterCard]:
        cards: list[CharacterCard] = []
        for index, candidate in enumerate(candidates[:3], start=1):
            character_id = str(getattr(candidate, "character_id", "") or f"char-{index:02d}")
            display_name = str(getattr(candidate, "display_name", "") or f"Character {index}")
            story_role = str(getattr(candidate, "story_role", ""))
            visual_description = str(getattr(candidate, "visual_description", ""))
            reference_prompt = str(
                getattr(candidate, "reference_prompt", "") or visual_description or display_name
            ).strip()
            source = "text_only"
            cards.append(
                CharacterCard(
                    character_id=character_id,
                    display_name=display_name,
                    story_role=story_role,
                    visual_description=visual_description,
                    reference_image=None,
                    reference_prompt=reference_prompt,
                    approval_status="pending",
                    source=source,
                )
            )
        return cards

    def _latest_event_details(self, project: Project, step_name: str) -> dict[str, Any]:
        for event in reversed(project.events):
            if event.step == step_name:
                return dict(event.details)
        return {}

    def _find_scene(self, scenes: list[Scene], item: dict[str, Any]) -> Scene | None:
        scene_id = item.get("scene_id")
        if isinstance(scene_id, str):
            for scene in scenes:
                if scene.scene_id == scene_id:
                    return scene
        scene_index = item.get("scene_index")
        if scene_index is not None:
            try:
                scene_index_int = int(scene_index)
            except (TypeError, ValueError):
                scene_index_int = None
            if scene_index_int is not None:
                for scene in scenes:
                    if scene.index == scene_index_int:
                        return scene
        return None

    def _require_scene(self, project: Project, scene_id: str) -> Scene:
        scene = self._find_scene(project.scenes, {"scene_id": scene_id})
        if scene is None:
            raise ValueError(f"Scene not found: {scene_id}")
        return scene

    def _require_character_card(self, project: Project, character_id: str) -> CharacterCard:
        for card in project.character_cards:
            if card.character_id == character_id:
                return card
        raise ValueError(f"Character not found: {character_id}")

    def _ensure_project_ready_for_scene_flow(self, project_id: str) -> Project:
        project = self.repo.load(project_id)
        if not project.optimized_prompt:
            project = self.optimize_prompt(project_id)
        if not project.scenes:
            project = self.plan_scenes(project_id)
        return self.repo.load(project_id)

    def _execute_workflow_run(
        self,
        project_id: str,
        workflow_run_job_id: str | None = None,
    ) -> Project:
        project = self.repo.load(project_id)
        workflow_run_job = self._begin_workflow_run(project, workflow_run_job_id)
        self.repo.save(project)

        try:
            steps = [
                ("prompt_optimize", lambda: self.optimize_prompt(project_id) if not self.repo.load(project_id).optimized_prompt else self.repo.load(project_id)),
                ("scene_plan", lambda: self.plan_scenes(project_id) if not self.repo.load(project_id).scenes else self.repo.load(project_id)),
                ("scene_video_generate", lambda: self.generate_scenes(project_id)),
                ("final_compose", lambda: self.compose_video(project_id)),
            ]

            for step_name, action in steps:
                self._mark_workflow_step_running(project_id, workflow_run_job.job_id, step_name)
                action()
                self._mark_workflow_step_completed(project_id, workflow_run_job.job_id, step_name)

            project = self.repo.load(project_id)
            workflow_run_job = project.workflow_run_job
            if workflow_run_job is None:
                raise RuntimeError("Workflow run job missing at completion")
            workflow_run_job.status = "completed"
            workflow_run_job.completed_at = utc_now()
            workflow_run_job.current_step = None
            workflow_run_job.metadata = workflow_run_job.metadata | {
                "final_video_rel_path": project.final_video_rel_path,
                "scene_ids": [scene.scene_id for scene in project.scenes],
            }
            project.add_event(
                "workflow_run",
                "completed",
                "Workflow run completed",
                details={
                    "job_id": workflow_run_job.job_id,
                    "final_video_rel_path": project.final_video_rel_path,
                },
            )
            self._log(
                "workflow completed",
                project_id=project.project_id,
                job_id=workflow_run_job.job_id,
                final_video_rel_path=project.final_video_rel_path,
            )
            self.repo.save(project)
            return project
        except Exception as exc:
            project = self.repo.load(project_id)
            workflow_run_job = project.workflow_run_job
            if workflow_run_job is not None:
                workflow_run_job.status = "failed"
                workflow_run_job.failed_at = utc_now()
                workflow_run_job.current_step = None
                workflow_run_job.error_message = str(exc)
            project.status = "failed"
            project.add_event(
                "workflow_run",
                "failed",
                "Workflow run failed",
                details={
                    "job_id": workflow_run_job.job_id if workflow_run_job else None,
                    "error": str(exc),
                },
            )
            self._log(
                "workflow failed",
                project_id=project.project_id,
                job_id=workflow_run_job.job_id if workflow_run_job else None,
                error=str(exc),
            )
            self.repo.save(project)
            raise
        finally:
            with self._futures_lock:
                current_project = self.repo.load(project_id)
                current_job = current_project.workflow_run_job
                if current_job is not None and current_job.job_id == workflow_run_job.job_id:
                    self._workflow_futures.pop(project_id, None)

    def _build_scene_generation_input(
        self,
        project: Project,
        scene: Scene,
        scene_index_map: dict[str, Scene],
    ) -> SceneGenerationInput:
        continuity_image = None
        continuity_source_scene_id = None
        if scene.depends_on_scene:
            prev_scene = scene_index_map.get(scene.depends_on_scene)
            if prev_scene and prev_scene.final_frame_rel_path:
                continuity_image = str(self.settings.artifact_dir / prev_scene.final_frame_rel_path)
                continuity_source_scene_id = prev_scene.scene_id
        first_frame_image = self._resolve_first_frame_image(scene, continuity_image)
        effective_prompt = self._compile_scene_generation_prompt(
            project,
            scene,
            first_frame_image=first_frame_image,
        )
        return SceneGenerationInput(
            project_id=project.project_id,
            provider=project.provider,
            scene_id=scene.scene_id,
            scene_index=scene.index,
            prompt=effective_prompt,
            duration_seconds=scene.duration_seconds,
            aspect_ratio=project.aspect_ratio,
            first_frame_source=scene.first_frame_source,
            first_frame_image=first_frame_image,
            reference_image=scene.reference_image,
            continuity_source_scene_id=continuity_source_scene_id,
            continuity_image=continuity_image,
            storyboard_notes=scene.storyboard_notes,
            audio_language=project.audio_language,
            generate_audio=True,
        )

    def _resolve_first_frame_image(
        self,
        scene: Scene,
        continuity_image: str | None,
    ) -> str | None:
        if scene.first_frame_source == "upload":
            return scene.first_frame_image
        if scene.first_frame_source == "continuity":
            return continuity_image
        if scene.first_frame_source == "auto_generate":
            return scene.first_frame_image
        return None

    def _compile_scene_generation_prompt(
        self,
        project: Project,
        scene: Scene,
        *,
        first_frame_image: str | None,
    ) -> str:
        base_prompt = self._freeze_scene_prompt_for_generation(
            project,
            scene,
            {item.scene_id: item for item in project.scenes},
            first_frame_image=first_frame_image,
        )
        return self._build_effective_scene_prompt(
            base_prompt,
            first_frame_source=scene.first_frame_source,
        )

    def _scene_prompt_has_user_override(self, scene: Scene) -> bool:
        draft = scene.prompt.strip()
        rendered = scene.rendered_prompt.strip()
        if not draft:
            return False
        return draft != rendered

    def _clear_scene_prompt_stale(self, scene: Scene) -> None:
        scene.prompt_stale = False
        scene.prompt_stale_reasons = []

    def _mark_scene_prompt_stale(self, scene: Scene, reasons: list[str]) -> None:
        merged = list(scene.prompt_stale_reasons)
        for reason in reasons:
            normalized = str(reason).strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
        scene.prompt_stale = bool(merged)
        scene.prompt_stale_reasons = merged

    def _freeze_scene_prompt_for_generation(
        self,
        project: Project,
        scene: Scene,
        scene_index_map: dict[str, Scene],
        *,
        first_frame_image: str | None,
    ) -> str:
        candidate_prompt = scene.prompt.strip() or scene.rendered_prompt.strip()
        if not candidate_prompt:
            self._refresh_scene_prompt(project, scene, scene_index_map)
            candidate_prompt = scene.prompt.strip() or scene.rendered_prompt.strip()
        if not candidate_prompt:
            raise ValueError("Scene prompt is empty. Refresh or edit the scene prompt before generation.")
        scene.approved_prompt = candidate_prompt
        self._clear_scene_prompt_stale(scene)
        return scene.approved_prompt

    def _ensure_first_frame_analysis(
        self,
        project: Project,
        scene: Scene,
        *,
        first_frame_image: str,
    ) -> dict[str, Any]:
        if scene.first_frame_source != "continuity" and scene.first_frame_analysis:
            return dict(scene.first_frame_analysis)
        analysis = analyze_first_frame_step(
            FirstFrameAnalyzeInput(
                scene_id=scene.scene_id,
                scene_index=scene.index,
                first_frame_source=scene.first_frame_source,
                image_input=first_frame_image,
                title=scene.title,
                narrative=scene.narrative,
                visual_goal=scene.visual_goal,
            ),
            settings=self.settings,
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )
        scene.first_frame_analysis = analysis.to_dict()
        scene.first_frame_status = "ready"
        scene.first_frame_job = {
            "status": "completed",
            "provider": analysis.provider_metadata.get("provider"),
            "model": analysis.provider_metadata.get("model"),
            "step": "first_frame_analyze",
        }
        if scene.first_frame_source == "upload" and not scene.first_frame_origin:
            scene.first_frame_origin = "user_upload"
        elif scene.first_frame_source == "continuity":
            scene.first_frame_origin = "previous_scene_tail"
        elif scene.first_frame_source == "auto_generate" and not scene.first_frame_origin:
            scene.first_frame_origin = "generated"
        if scene.index == 1:
            project.scene1_first_frame_image = scene.first_frame_image
            project.scene1_first_frame_prompt = scene.first_frame_prompt
            project.scene1_first_frame_origin = scene.first_frame_origin
            project.scene1_first_frame_status = scene.first_frame_status
            project.scene1_first_frame_analysis = dict(scene.first_frame_analysis)
            project.scene1_first_frame_job = dict(scene.first_frame_job)
        return dict(scene.first_frame_analysis)

    def _should_prepare_scene_auto_generated_first_frame(
        self,
        project: Project,
        scene: Scene,
        *,
        prepared_prompt: str,
    ) -> bool:
        if not scene.first_frame_image:
            return True
        if scene.first_frame_origin != "generated":
            return False
        if scene.index == 1:
            project_level_prompt = self._compose_project_opening_first_frame_prompt(project)
            if project.scene1_first_frame_prompt.strip() != project_level_prompt.strip():
                return False
        return scene.first_frame_prompt.strip() != prepared_prompt.strip()

    def _compose_project_opening_first_frame_prompt(self, project: Project) -> str:
        parts: list[str] = []
        default_project_prompt = project.raw_prompt.strip()
        base_prompt = project.scene1_first_frame_prompt.strip()
        if self._is_system_opening_state_first_frame_prompt(base_prompt, project.detected_input_language):
            base_prompt = ""
        if base_prompt and not self._prompt_text_matches(base_prompt, default_project_prompt):
            parts.append(base_prompt.rstrip("."))
        elif default_project_prompt:
            parts.append(default_project_prompt.rstrip("."))
        prompt_brief = ". ".join(self._dedupe_prompt_parts(parts)) if parts else default_project_prompt
        return self._wrap_opening_state_first_frame_prompt(
            prompt_brief,
            input_language=project.detected_input_language,
            scene_index=1,
        )

    def _wrap_opening_state_first_frame_prompt(
        self,
        prompt_brief: str,
        *,
        input_language: str | None,
        scene_index: int,
    ) -> str:
        normalized_brief = prompt_brief.strip()
        if not normalized_brief:
            return ""
        if str(input_language or "").strip().lower() == "zh":
            return (
                "开场起点图说明：\n"
                f"{normalized_brief}\n\n"
                f"只生成第{scene_index}场在 t=0 时刻的单张起点图。"
                "只表现这个场景最开始已经真实存在的稳定状态，不要把后续时间线、结果、目标达成、救援完成、逃脱成功、门已打开、到达目的地、团聚、分屏、前后对照或转场过渡压缩进同一张图。"
                "如果角色只是向往某个地点或结果，不要把那个目标地点直接画成开场已发生的现实场景，除非这一场一开始就发生在那里。"
                "不要提前泄露后续场景才会出现的人物、动作结果或环境变化。"
                "只保留开场时刻真实需要出现的人物、道具和环境。"
            )
        return (
            "Opening still brief:\n"
            f"{normalized_brief}\n\n"
            f"Generate a single opening-state still for scene {scene_index} at t=0. "
            "Show only the earliest stable state that is already true when the scene begins. "
            "Do not compress later timeline beats, outcomes, achieved goals, completed rescues, successful escapes, already-open escape routes, destination arrivals, reunions, split-screen contrasts, or before/after transitions into the same frame. "
            "If the story mentions a desired place or future outcome, do not show it as a literal achieved reality unless the scene truly starts there. "
            "Do not introduce characters, environmental changes, or result states that belong to later scenes. "
            "Keep only the characters, props, and setting elements that are genuinely present at the opening moment."
        )

    def _is_system_opening_state_first_frame_prompt(
        self,
        prompt_text: str,
        input_language: str | None,
    ) -> bool:
        normalized_prompt = prompt_text.strip()
        if not normalized_prompt:
            return False
        prefix = (
            "开场起点图说明：\n"
            if str(input_language or "").strip().lower() == "zh"
            else "Opening still brief:\n"
        )
        return normalized_prompt.startswith(prefix) and "\n\n" in normalized_prompt

    def _prompt_text_matches(self, left: str, right: str) -> bool:
        punctuation = " \t\r\n.。!！?？"
        normalized_left = " ".join(left.strip().rstrip(punctuation).split()).casefold()
        normalized_right = " ".join(right.strip().rstrip(punctuation).split()).casefold()
        return bool(normalized_left) and normalized_left == normalized_right

    def _compose_scene_auto_generated_first_frame_prompt(self, project: Project, scene: Scene) -> str:
        parts: list[str] = []
        narrative = scene.narrative.strip()
        visual_goal = scene.visual_goal.strip()
        base_prompt = scene.first_frame_prompt.strip()
        if self._is_system_opening_state_first_frame_prompt(base_prompt, project.detected_input_language):
            base_prompt = ""
        default_project_prompt = project.raw_prompt.strip()
        if base_prompt and not self._prompt_text_matches(base_prompt, default_project_prompt):
            parts.append(base_prompt.rstrip("."))
        if narrative:
            parts.append(narrative.rstrip("."))
        if visual_goal:
            parts.append(visual_goal.rstrip("."))
        character_prompt = self._scene_character_first_frame_hint(project, scene)
        if character_prompt:
            parts.append(character_prompt.rstrip("."))
        if not parts:
            prompt_brief = base_prompt or default_project_prompt
        else:
            prompt_brief = ". ".join(self._dedupe_prompt_parts(parts))
        return self._wrap_opening_state_first_frame_prompt(
            prompt_brief,
            input_language=project.detected_input_language,
            scene_index=scene.index,
        )

    def _scene_character_first_frame_hint(self, project: Project, scene: Scene) -> str:
        cards = self._scene_approved_lookdev_cards(project, scene) or self._scene_character_cards(project, scene)
        if not cards:
            return ""
        primary_id = scene.primary_character_id or ""
        ordered_cards = sorted(
            cards,
            key=lambda card: 0 if card.character_id == primary_id else 1,
        )
        summaries: list[str] = []
        for card in ordered_cards[:2]:
            display_name = card.display_name.strip() or card.character_id
            lookdev_description = (
                card.reference_prompt.strip()
                if card.approval_status == "approved" and card.reference_prompt.strip()
                else card.visual_description.strip()
            )
            if lookdev_description:
                summaries.append(f"{display_name}: {lookdev_description}")
            else:
                summaries.append(display_name)
        if not summaries:
            return ""
        if len(summaries) == 1:
            return f"Character anchor for this scene: {summaries[0]}"
        return "Scene character anchors: " + "; ".join(summaries)

    def _scene_approved_lookdev_cards(self, project: Project, scene: Scene) -> list[CharacterCard]:
        if not scene.participating_character_ids:
            return []
        allowed_ids = {item for item in scene.participating_character_ids if item}
        return [
            card
            for card in project.character_cards
            if card.character_id in allowed_ids and card.approval_status == "approved"
        ]

    def _dedupe_prompt_parts(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(value.split()).strip().casefold()
            if not normalized or normalized in seen:
                continue
            deduped.append(value)
            seen.add(normalized)
        return deduped

    def _run_scene_prompt_revision(
        self,
        project: Project,
        scene: Scene,
        *,
        feedback: str,
        scope: str,
    ):
        prompt_optimize_details = self._latest_event_details(project, "prompt_optimize")
        project_guidance = build_project_guidance_context(
            step_name="scene_prompt_revise",
            target_duration_seconds=project.target_duration_seconds,
            scene_count=max(1, project.scene_count or self.settings.default_scene_count),
            input_language=project.detected_input_language,
            dialogue_language=project.dialogue_language,
            audio_language=project.audio_language,
            language_confidence=project.language_detection_confidence,
            creative_intent=str(prompt_optimize_details.get("creative_intent", "")),
            style_guardrails=list(prompt_optimize_details.get("style_guardrails", [])),
            planning_notes=str(prompt_optimize_details.get("planning_notes", "")),
            dialogue_lines=list(prompt_optimize_details.get("dialogue_lines", [])),
            scene1_first_frame_source=project.scene1_first_frame_source,
            scene1_first_frame_prompt=project.scene1_first_frame_prompt,
            scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
        )
        scene_guidance = build_scene_guidance_context(
            step_name="scene_prompt_revise",
            working_prompt=scene.prompt,
            spoken_text=scene.spoken_text,
            speech_mode=scene.speech_mode,
            delivery_notes=scene.delivery_notes,
            dialogue_language=project.dialogue_language,
            audio_language=project.audio_language,
            character_cards=self._scene_character_cards(project, scene),
            participating_character_ids=scene.participating_character_ids,
            primary_character_id=scene.primary_character_id,
            character_presence_notes=scene.character_presence_notes,
            first_frame_source=scene.first_frame_source,
            first_frame_analysis=dict(scene.first_frame_analysis),
            continuity_notes=scene.continuity_notes,
            first_frame_prompt=scene.first_frame_prompt,
        )
        return revise_scene_prompt_step(
            ScenePromptRevisionInput(
                scene_id=scene.scene_id,
                scene_index=scene.index,
                scene_count=max(1, project.scene_count or self.settings.default_scene_count),
                raw_prompt=project.raw_prompt,
                current_prompt=scene.prompt or scene.rendered_prompt,
                current_rendered_prompt=scene.rendered_prompt,
                title=scene.title,
                narrative=scene.narrative,
                visual_goal=scene.visual_goal,
                spoken_text=scene.spoken_text,
                speech_mode=scene.speech_mode,
                delivery_notes=scene.delivery_notes,
                continuity_notes=scene.continuity_notes,
                first_frame_source=scene.first_frame_source,
                first_frame_prompt=scene.first_frame_prompt,
                first_frame_analysis=dict(scene.first_frame_analysis),
                input_language=project.detected_input_language,
                dialogue_language=project.dialogue_language,
                audio_language=project.audio_language,
                feedback=feedback,
                requested_scope=scope,
                project_guidance_context=project_guidance,
                scene_guidance_context=scene_guidance,
            ),
            settings=self.settings,
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )

    def _refresh_scene_prompt(
        self,
        project: Project,
        scene: Scene,
        scene_index_map: dict[str, Scene],
        *,
        working_prompt_override: str | None = None,
    ) -> None:
        continuity_image = None
        if scene.depends_on_scene:
            prev_scene = scene_index_map.get(scene.depends_on_scene)
            if prev_scene and prev_scene.final_frame_rel_path:
                continuity_image = str(self.settings.artifact_dir / prev_scene.final_frame_rel_path)
        first_frame_image = self._resolve_first_frame_image(scene, continuity_image)
        first_frame_analysis: dict[str, Any] = {}
        if first_frame_image:
            first_frame_analysis = self._ensure_first_frame_analysis(
                project,
                scene,
                first_frame_image=first_frame_image,
            )
        prompt_optimize_details = self._latest_event_details(project, "prompt_optimize")
        rendered = render_scene_prompt_step(
            ScenePromptRenderInput(
                scene_id=scene.scene_id,
                scene_index=scene.index,
                scene_count=max(1, project.scene_count or self.settings.default_scene_count),
                title=scene.title,
                working_prompt=(working_prompt_override or "").strip(),
                narrative=scene.narrative,
                visual_goal=scene.visual_goal,
                spoken_text=scene.spoken_text,
                speech_mode=scene.speech_mode,
                delivery_notes=scene.delivery_notes,
                input_language=project.detected_input_language,
                dialogue_language=project.dialogue_language,
                audio_language=project.audio_language,
                continuity_notes=scene.continuity_notes,
                duration_seconds=scene.duration_seconds,
                first_frame_source=scene.first_frame_source,
                first_frame_prompt=scene.first_frame_prompt,
                first_frame_analysis=first_frame_analysis,
                aspect_ratio=project.aspect_ratio,
                project_guidance_context=build_project_guidance_context(
                    step_name="scene_prompt_render",
                    target_duration_seconds=project.target_duration_seconds,
                    scene_count=max(1, project.scene_count or self.settings.default_scene_count),
                    input_language=project.detected_input_language,
                    dialogue_language=project.dialogue_language,
                    audio_language=project.audio_language,
                    language_confidence=project.language_detection_confidence,
                    creative_intent=str(prompt_optimize_details.get("creative_intent", "")),
                    style_guardrails=list(prompt_optimize_details.get("style_guardrails", [])),
                    planning_notes=str(prompt_optimize_details.get("planning_notes", "")),
                    dialogue_lines=list(prompt_optimize_details.get("dialogue_lines", [])),
                    scene1_first_frame_source=project.scene1_first_frame_source,
                    scene1_first_frame_prompt=project.scene1_first_frame_prompt,
                    scene1_first_frame_analysis=dict(project.scene1_first_frame_analysis),
                ),
                scene_guidance_context=build_scene_guidance_context(
                    step_name="scene_prompt_render",
                    working_prompt=(working_prompt_override or "").strip(),
                    spoken_text=scene.spoken_text,
                    speech_mode=scene.speech_mode,
                    delivery_notes=scene.delivery_notes,
                    dialogue_language=project.dialogue_language,
                    audio_language=project.audio_language,
                    character_cards=self._scene_character_cards(project, scene),
                    participating_character_ids=scene.participating_character_ids,
                    primary_character_id=scene.primary_character_id,
                    character_presence_notes=scene.character_presence_notes,
                    first_frame_source=scene.first_frame_source,
                    first_frame_analysis=first_frame_analysis,
                    continuity_notes=scene.continuity_notes,
                    first_frame_prompt=scene.first_frame_prompt,
                ),
            ),
            settings=self.settings,
            trace_logger=self.trace_logger,
            project_id=project.project_id,
        )
        draft_was_in_sync = not scene.prompt.strip() or scene.prompt.strip() == scene.rendered_prompt.strip()
        scene.rendered_prompt = rendered.rendered_prompt
        if draft_was_in_sync and not (working_prompt_override or "").strip():
            scene.prompt = rendered.rendered_prompt
        scene.provider_metadata = dict(scene.provider_metadata) | {
            "scene_prompt_refresh": {
                "mode": "llm_scene_prompt_render",
                "first_frame_source": scene.first_frame_source,
                "working_prompt_override": bool((working_prompt_override or "").strip()),
            },
            "scene_prompt_render": rendered.provider_metadata,
        }

    def _refresh_scene_prompts_parallel(
        self,
        project: Project,
        scenes: list[Scene],
        scene_index_map: dict[str, Scene],
    ) -> None:
        if len(scenes) <= 1:
            for scene in scenes:
                self._refresh_scene_prompt(project, scene, scene_index_map)
            return
        max_workers = max(1, min(len(scenes), self.settings.workflow_max_workers))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self._refresh_scene_prompt, project, scene, scene_index_map)
                for scene in scenes
            ]
            for future in futures:
                future.result()

    def _scene_character_cards(self, project: Project, scene: Scene) -> list[CharacterCard]:
        if not scene.participating_character_ids:
            return []
        allowed_ids = {item for item in scene.participating_character_ids if item}
        return [card for card in project.character_cards if card.character_id in allowed_ids]

    def _refresh_scene_prompt_after_upstream_change(
        self,
        project: Project,
        scene: Scene,
        scene_index_map: dict[str, Scene],
        *,
        stale_reasons: list[str] | None = None,
    ) -> None:
        reasons = [str(item).strip() for item in (stale_reasons or []) if str(item).strip()]
        had_user_override = self._scene_prompt_has_user_override(scene)
        previous_rendered = scene.rendered_prompt.strip()
        self._refresh_scene_prompt(project, scene, scene_index_map)
        if had_user_override and reasons:
            if scene.rendered_prompt.strip() != previous_rendered or reasons:
                self._mark_scene_prompt_stale(scene, reasons)
                scene.approved_prompt = ""
            return
        self._clear_scene_prompt_stale(scene)
        scene.approved_prompt = ""

    def _build_effective_scene_prompt(
        self,
        base_prompt: str,
        *,
        first_frame_source: str,
    ) -> str:
        normalized = str(base_prompt or "").strip()
        return normalized

    def _queue_scene_video_job(
        self,
        project: Project,
        scene: Scene,
        contract: SceneGenerationInput,
    ) -> SceneVideoJob:
        previous_attempts = scene.video_job.attempt_count if scene.video_job else 0
        job = SceneVideoJob(
            job_id=f"svg_{uuid4().hex[:10]}",
            scene_id=scene.scene_id,
            provider=contract.provider,
            status="queued",
            attempt_count=previous_attempts + 1,
            continuity_source_scene_id=contract.continuity_source_scene_id,
            metadata={
                "prompt": contract.prompt,
                "prompt_snapshot": contract.prompt,
                "provider_prompt_snapshot": contract.prompt,
                "approved_prompt": scene.approved_prompt or contract.prompt,
                "approved_prompt_snapshot": scene.approved_prompt or contract.prompt,
                "scene_prompt": scene.prompt,
                "scene_prompt_snapshot": scene.prompt,
                "scene_prompt_draft": scene.prompt,
                "scene_prompt_draft_snapshot": scene.prompt,
                "scene_rendered_prompt": scene.rendered_prompt or scene.prompt,
                "scene_rendered_prompt_snapshot": scene.rendered_prompt or scene.prompt,
                "prompt_stale": scene.prompt_stale,
                "prompt_stale_reasons": list(scene.prompt_stale_reasons),
                "duration_seconds": contract.duration_seconds,
                "aspect_ratio": contract.aspect_ratio,
                "first_frame_source": contract.first_frame_source,
                "first_frame_image": contract.first_frame_image,
                "reference_image": contract.reference_image,
                "continuity_image": contract.continuity_image,
                "storyboard_notes": contract.storyboard_notes,
                "storyboard_notes_snapshot": contract.storyboard_notes,
                "audio_language": contract.audio_language,
                "generate_audio": contract.generate_audio,
            },
        )
        scene.video_job = job
        scene.status = "queued"
        scene.review_status = "generating"
        project.status = "scene_generation_queued" if project.workflow_mode == "hitl" else "scene_videos_generating"
        return job

    def _begin_scene_video_job(
        self,
        project: Project,
        scene: Scene,
        job: SceneVideoJob,
        contract: SceneGenerationInput,
    ) -> None:
        job.status = "running"
        job.started_at = job.started_at or utc_now()
        job.failed_at = None
        job.completed_at = None
        job.error_message = None
        scene.status = "generating"
        scene.review_status = "generating"
        project.status = "scene_videos_generating"
        self._log(
            "scene generation started",
            project_id=project.project_id,
            scene_id=scene.scene_id,
            scene_index=scene.index,
            provider=contract.provider,
            continuity_source_scene_id=contract.continuity_source_scene_id,
        )

    def _mark_scene_video_failed(
        self,
        project: Project,
        scene: Scene,
        job: SceneVideoJob,
        error: Exception,
    ) -> None:
        job.status = "failed"
        job.failed_at = utc_now()
        job.error_message = str(error)
        scene.status = "failed"
        scene.review_status = "failed"
        project.status = "failed"
        project.add_event(
            "scene_video_generate",
            "failed",
            f"Scene {scene.index} generation failed",
            details={
                "scene_id": scene.scene_id,
                "job_id": job.job_id,
                "error": str(error),
            },
        )
        self._log(
            "scene generation failed",
            project_id=project.project_id,
            scene_id=scene.scene_id,
            scene_index=scene.index,
            job_id=job.job_id,
            error=str(error),
        )

    def _apply_scene_generation_output(
        self,
        project: Project,
        scene: Scene,
        job: SceneVideoJob,
        result: SceneGenerationOutput,
        *,
        requires_review: bool,
    ) -> None:
        scene.video_rel_path = result.video_rel_path
        scene.final_frame_rel_path = result.final_frame_rel_path
        scene.generation_mode = result.generation_mode
        scene.provider_metadata = result.provider_metadata | {
            "provider": result.provider,
            "model": result.model,
        }
        if requires_review:
            scene.status = "pending_review"
            scene.review_status = "pending_review"
        elif project.workflow_mode == "hitl":
            scene.status = "approved"
            scene.review_status = "approved"
        else:
            scene.status = "generated"
            scene.review_status = "not_required"

        job.status = "completed"
        job.completed_at = utc_now()
        job.generation_mode = result.generation_mode
        job.provider_task_id = result.provider_task_id
        job.video_rel_path = result.video_rel_path
        job.final_frame_rel_path = result.final_frame_rel_path
        job.metadata = job.metadata | result.provider_metadata | {
            "provider": result.provider,
            "model": result.model,
        }

        project.add_event(
            "scene_video_generate",
            "completed",
            (
                f"Scene {scene.index} generated and awaiting review"
                if requires_review
                else f"Scene {scene.index} generated"
            ),
            details={
                "scene_id": scene.scene_id,
                "job_id": job.job_id,
                "provider_task_id": result.provider_task_id,
                "generation_mode": scene.generation_mode,
                "video_rel_path": scene.video_rel_path,
            },
        )
        self._log(
            "scene generation completed",
            project_id=project.project_id,
            scene_id=scene.scene_id,
            scene_index=scene.index,
            job_id=job.job_id,
            provider_task_id=result.provider_task_id,
            video_rel_path=scene.video_rel_path,
        )
        self.trace_logger.append(
            project.project_id,
            event_type="scene_generation_completed",
            step="scene_video_generate",
            status="completed",
            details={
                "scene_id": scene.scene_id,
                "job_id": job.job_id,
                "provider_task_id": result.provider_task_id,
                "provider_prompt_snapshot": job.metadata.get("provider_prompt_snapshot")
                or job.metadata.get("prompt_snapshot"),
                "prompt_snapshot": job.metadata.get("prompt_snapshot"),
                "video_rel_path": scene.video_rel_path,
                "speech_mode": scene.speech_mode,
                "spoken_text": scene.spoken_text,
                "request_summary": result.provider_metadata.get("request_summary"),
            },
        )

    def _refresh_downstream_scene_prompts_for_continuity(
        self,
        project_id: str,
        source_scene_id: str,
    ) -> Project:
        working_project = self.repo.load(project_id)
        source_scene = self._require_scene(working_project, source_scene_id)
        scene_index_map = {item.scene_id: item for item in working_project.scenes}
        refreshed_scene_ids: list[str] = []

        for dependent_scene in working_project.scenes:
            if dependent_scene.depends_on_scene != source_scene.scene_id:
                continue
            if dependent_scene.first_frame_source != "continuity":
                continue
            if dependent_scene.status in {"queued", "generating", "approved"}:
                continue
            self._refresh_scene_prompt_after_upstream_change(
                working_project,
                dependent_scene,
                scene_index_map,
                stale_reasons=["continuity_frame_updated"],
            )
            refreshed_scene_ids.append(dependent_scene.scene_id)

        if not refreshed_scene_ids:
            return self.repo.load(project_id)

        latest_project = self.repo.load(project_id)
        latest_scene_map = {item.scene_id: item for item in latest_project.scenes}
        working_scene_map = {item.scene_id: item for item in working_project.scenes}
        for scene_id in refreshed_scene_ids:
            latest_scene = latest_scene_map.get(scene_id)
            working_scene = working_scene_map.get(scene_id)
            if latest_scene is None or working_scene is None:
                continue
            if latest_scene.status in {"queued", "generating", "pending_review", "approved"}:
                continue
            latest_scene.prompt = working_scene.prompt
            latest_scene.rendered_prompt = working_scene.rendered_prompt
            latest_scene.approved_prompt = working_scene.approved_prompt
            latest_scene.prompt_stale = working_scene.prompt_stale
            latest_scene.prompt_stale_reasons = list(working_scene.prompt_stale_reasons)
            latest_scene.provider_metadata = dict(working_scene.provider_metadata)
            latest_scene.first_frame_analysis = dict(working_scene.first_frame_analysis)
            latest_scene.first_frame_job = dict(working_scene.first_frame_job)
            latest_scene.first_frame_status = working_scene.first_frame_status
            latest_scene.first_frame_origin = working_scene.first_frame_origin
            latest_scene.first_frame_prompt = working_scene.first_frame_prompt
            latest_scene.first_frame_image = working_scene.first_frame_image

        return self.repo.save(latest_project)

    def _generate_scene_sync(
        self,
        project_id: str,
        scene_id: str,
        *,
        queued_job_id: str | None = None,
        requires_review: bool,
        refresh_downstream_continuity: bool = True,
    ) -> Project:
        project = self.repo.load(project_id)
        scene = self._require_scene(project, scene_id)
        provider = get_video_provider(self.settings, project.provider)
        job = scene.video_job
        if queued_job_id:
            if job is None or job.job_id != queued_job_id:
                raise RuntimeError("Scene video job mismatch")
            contract = self._build_scene_generation_input_from_job(project, scene, job)
        else:
            scene_index_map = {item.scene_id: item for item in project.scenes}
            contract = self._build_scene_generation_input(project, scene, scene_index_map)
            job = self._queue_scene_video_job(project, scene, contract)
        if job is None:
            raise RuntimeError("Scene video job missing")
        self._begin_scene_video_job(project, scene, job, contract)
        self.repo.save(project)

        try:
            provider_result = provider.generate_video(contract.to_provider_request())
        except Exception as exc:
            self._mark_scene_video_failed(project, scene, job, exc)
            self.repo.save(project)
            raise

        result = SceneGenerationOutput.from_provider_result(contract, provider_result)
        self._apply_scene_generation_output(project, scene, job, result, requires_review=requires_review)
        if project.workflow_mode == "hitl":
            self._sync_hitl_project_status(project)
        project = self.repo.save(project)

        if not refresh_downstream_continuity:
            return project

        try:
            project = self._refresh_downstream_scene_prompts_for_continuity(
                project.project_id,
                scene.scene_id,
            )
        except Exception as exc:
            self.logger.warning(
                "downstream continuity prompt refresh failed | project_id=%s scene_id=%s error=%s",
                project.project_id,
                scene.scene_id,
                str(exc),
            )
            self.trace_logger.append(
                project.project_id,
                event_type="downstream_continuity_refresh",
                step="scene_prompt_refresh",
                status="failed",
                details={
                    "source_scene_id": scene.scene_id,
                    "error": str(exc),
                },
            )
            return project

        return project

    def _build_scene_generation_input_from_job(
        self,
        project: Project,
        scene: Scene,
        job: SceneVideoJob,
    ) -> SceneGenerationInput:
        metadata = dict(job.metadata)
        return SceneGenerationInput(
            project_id=project.project_id,
            provider=project.provider,
            scene_id=scene.scene_id,
            scene_index=scene.index,
            prompt=str(
                metadata.get("provider_prompt_snapshot")
                or metadata.get("approved_prompt_snapshot")
                or metadata.get("prompt_snapshot")
                or metadata.get("prompt")
                or scene.approved_prompt
                or scene.rendered_prompt
                or scene.prompt
            ),
            duration_seconds=int(metadata.get("duration_seconds", scene.duration_seconds)),
            aspect_ratio=str(metadata.get("aspect_ratio", project.aspect_ratio)),
            first_frame_source=str(metadata.get("first_frame_source", scene.first_frame_source)),
            first_frame_image=self._normalize_optional_string(metadata.get("first_frame_image")),
            reference_image=self._normalize_optional_string(metadata.get("reference_image")),
            continuity_source_scene_id=self._normalize_optional_string(metadata.get("continuity_source_scene_id")),
            continuity_image=self._normalize_optional_string(metadata.get("continuity_image")),
            storyboard_notes=str(metadata.get("storyboard_notes", scene.storyboard_notes)),
            audio_language=str(metadata.get("audio_language", project.audio_language)),
            generate_audio=bool(metadata.get("generate_audio", True)),
        )

    def _execute_scene_generation(
        self,
        project_id: str,
        scene_id: str,
        scene_job_id: str,
    ) -> Project:
        try:
            project = self._generate_scene_sync(
                project_id,
                scene_id,
                queued_job_id=scene_job_id,
                requires_review=True,
                refresh_downstream_continuity=False,
            )
            self._release_scene_future(project_id, scene_id, scene_job_id)
            try:
                return self._refresh_downstream_scene_prompts_for_continuity(project_id, scene_id)
            except Exception as exc:
                self.logger.warning(
                    "downstream continuity prompt refresh failed | project_id=%s scene_id=%s error=%s",
                    project_id,
                    scene_id,
                    str(exc),
                )
                self.trace_logger.append(
                    project_id,
                    event_type="downstream_continuity_refresh",
                    step="scene_prompt_refresh",
                    status="failed",
                    details={
                        "source_scene_id": scene_id,
                        "error": str(exc),
                    },
                )
                return project
        finally:
            self._release_scene_future(project_id, scene_id, scene_job_id)

    def _start_final_video_job(
        self,
        project: Project,
        contract: FinalCompositionInput,
    ) -> FinalVideoJob:
        self._clear_existing_subtitle_delivery(project)
        previous_attempts = project.final_video_job.attempt_count if project.final_video_job else 0
        job = FinalVideoJob(
            job_id=f"fvg_{uuid4().hex[:10]}",
            status="running",
            attempt_count=previous_attempts + 1,
            provider="ffmpeg",
            input_scene_ids=contract.scene_ids,
            started_at=utc_now(),
            metadata={"clip_count": len(contract.clip_paths)},
        )
        project.final_video_job = job
        project.status = "composing"
        self._log(
            "final composition started",
            project_id=project.project_id,
            job_id=job.job_id,
            clip_count=len(contract.clip_paths),
        )
        return job

    def _mark_final_video_failed(
        self,
        project: Project,
        job: FinalVideoJob,
        error: Exception,
    ) -> None:
        job.status = "failed"
        job.failed_at = utc_now()
        job.error_message = str(error)
        project.status = "failed"
        project.add_event(
            "final_compose",
            "failed",
            "Final workflow composition failed",
            details={"job_id": job.job_id, "error": str(error)},
        )
        self._log(
            "final composition failed",
            project_id=project.project_id,
            job_id=job.job_id,
            error=str(error),
        )

    def _apply_final_composition_output(
        self,
        project: Project,
        job: FinalVideoJob,
        result: FinalCompositionOutput,
    ) -> None:
        project.final_video_rel_path = result.final_video_rel_path
        project.status = "delivered"

        job.status = "completed"
        job.completed_at = utc_now()
        job.final_video_rel_path = result.final_video_rel_path
        job.metadata = result.metadata

        project.add_event(
            "final_compose",
            "completed",
            "Final workflow video composed",
            details={
                "job_id": job.job_id,
                "final_video_rel_path": result.final_video_rel_path,
            },
        )
        project.add_event(
            "delivery_publish",
            "completed",
            "Delivery asset ready",
            details={"final_video_rel_path": result.final_video_rel_path},
        )
        self._log(
            "final composition completed",
            project_id=project.project_id,
            job_id=job.job_id,
            final_video_rel_path=result.final_video_rel_path,
        )

    def _queue_subtitle_sidecar(self, project_id: str) -> None:
        project = self.repo.load(project_id)
        if project.subtitle_mode == "disabled":
            project.subtitle_job = None
            self.repo.save(project)
            return

        if self._subtitle_eligibility_reason(project) != "eligible":
            project.subtitle_job = None
            self.repo.save(project)
            return

        if not self._subtitle_service_is_configured():
            project.subtitle_job = SubtitleJob(
                job_id=f"stj_{uuid4().hex[:10]}",
                status="skipped",
                provider=self.settings.subtitle_service_name,
                mode=project.subtitle_mode,
                completed_at=utc_now(),
                error_message="Subtitle service is not configured.",
                metadata={"skip_reason": "subtitle_service_not_configured"},
            )
            project.add_event(
                "subtitle_align",
                "skipped",
                "Subtitle sidecar skipped because subtitle service is not configured",
                details={"provider": self.settings.subtitle_service_name},
            )
            self.repo.save(project)
            return

        subtitle_job = SubtitleJob(
            job_id=f"stj_{uuid4().hex[:10]}",
            status="queued",
            provider=self.settings.subtitle_service_name,
            mode=project.subtitle_mode,
            metadata={"alignment_strategy": "text_alignment"},
        )
        project.subtitle_job = subtitle_job
        project.add_event(
            "subtitle_align",
            "queued",
            "Subtitle sidecar queued after final composition",
            details={
                "job_id": subtitle_job.job_id,
                "provider": subtitle_job.provider,
                "mode": subtitle_job.mode,
            },
        )
        self.repo.save(project)
        future = self._executor.submit(
            self._execute_subtitle_generation,
            project_id,
            subtitle_job.job_id,
        )
        with self._futures_lock:
            self._subtitle_futures[project_id] = future

    def _execute_subtitle_burn_export(self, project_id: str, subtitle_burn_job_id: str) -> Project:
        try:
            project = self.repo.load(project_id)
            subtitle_burn_job = project.subtitle_burn_job
            if subtitle_burn_job is None or subtitle_burn_job.job_id != subtitle_burn_job_id:
                return project

            subtitle_burn_job.status = "running"
            subtitle_burn_job.started_at = utc_now()
            subtitle_burn_job.error_message = None
            self.repo.save(project)
            self._log(
                "subtitle burn export started",
                project_id=project.project_id,
                job_id=subtitle_burn_job.job_id,
                provider=subtitle_burn_job.provider,
            )

            if not project.final_video_rel_path or not project.subtitle_srt_rel_path:
                raise RuntimeError("Subtitled video export requires final video and SRT subtitles.")

            output_rel_path = f"{project.project_id}/delivery/final_burned.mp4"
            burn_subtitles_into_video(
                ffmpeg_bin=self.settings.ffmpeg_bin,
                video_path=self.settings.artifact_dir / str(project.final_video_rel_path),
                subtitle_path=self.settings.artifact_dir / str(project.subtitle_srt_rel_path),
                output_path=self.settings.artifact_dir / output_rel_path,
            )
            return self._apply_subtitle_burn_output(project_id, subtitle_burn_job_id, output_rel_path)
        except Exception as exc:
            return self._mark_subtitle_burn_failed(project_id, subtitle_burn_job_id, exc)
        finally:
            self._release_subtitle_burn_future(project_id, subtitle_burn_job_id)

    def _execute_subtitle_generation(self, project_id: str, subtitle_job_id: str) -> Project:
        audio_path: Path | None = None
        try:
            project = self.repo.load(project_id)
            subtitle_job = project.subtitle_job
            if subtitle_job is None or subtitle_job.job_id != subtitle_job_id:
                return project

            subtitle_job.status = "running"
            subtitle_job.started_at = utc_now()
            subtitle_job.error_message = None
            self.repo.save(project)
            self._log(
                "subtitle generation started",
                project_id=project.project_id,
                job_id=subtitle_job.job_id,
                provider=subtitle_job.provider,
            )

            final_video_path = self.settings.artifact_dir / str(project.final_video_rel_path)
            delivery_dir = final_video_path.parent
            audio_path = delivery_dir / "final.subtitle-input.wav"
            extract_audio_track(
                ffmpeg_bin=self.settings.ffmpeg_bin,
                video_path=final_video_path,
                output_path=audio_path,
            )

            language = project.audio_language or project.dialogue_language or project.detected_input_language
            subtitle_text = self._build_project_subtitle_text(project)
            try:
                result = self._build_subtitle_client().align_known_text(
                    audio_path=audio_path,
                    subtitle_text=subtitle_text,
                    language=language,
                )
            except Exception as primary_error:
                self._log(
                    "subtitle text alignment failed; attempting ASR fallback",
                    project_id=project.project_id,
                    job_id=subtitle_job.job_id,
                    error=str(primary_error),
                )
                result = self._run_subtitle_asr_fallback(
                    audio_path=audio_path,
                    language=language,
                    primary_error=primary_error,
                )
            return self._apply_subtitle_alignment_result(project_id, subtitle_job_id, result)
        except Exception as exc:
            return self._mark_subtitle_job_failed(project_id, subtitle_job_id, exc)
        finally:
            if audio_path is not None and audio_path.exists():
                audio_path.unlink(missing_ok=True)
            self._release_subtitle_future(project_id, subtitle_job_id)

    def _run_subtitle_asr_fallback(
        self,
        *,
        audio_path: Path,
        language: str | None,
        primary_error: Exception,
    ) -> SubtitleAlignmentResult:
        if not self._subtitle_asr_fallback_is_configured():
            raise RuntimeError(
                "Subtitle text alignment failed and ASR fallback is unavailable. "
                f"Primary error: {primary_error}"
            ) from primary_error

        result = self._build_subtitle_asr_client().recognize_audio(
            audio_path=audio_path,
            language=language,
        )
        result.metadata["fallback_from"] = "text_alignment"
        result.metadata["fallback_reason"] = str(primary_error)
        return result

    def _apply_subtitle_alignment_result(
        self,
        project_id: str,
        subtitle_job_id: str,
        result: SubtitleAlignmentResult,
    ) -> Project:
        project = self.repo.load(project_id)
        subtitle_job = project.subtitle_job
        if subtitle_job is None or subtitle_job.job_id != subtitle_job_id:
            return project

        srt_rel_path = f"{project.project_id}/delivery/final.srt"
        vtt_rel_path = f"{project.project_id}/delivery/final.vtt"
        srt_path = self.settings.artifact_dir / srt_rel_path
        vtt_path = self.settings.artifact_dir / vtt_rel_path
        srt_path.parent.mkdir(parents=True, exist_ok=True)
        vtt_path.parent.mkdir(parents=True, exist_ok=True)
        srt_path.write_text(render_srt(result.cues), encoding="utf-8")
        vtt_path.write_text(render_vtt(result.cues), encoding="utf-8")

        project.subtitle_srt_rel_path = srt_rel_path
        project.subtitle_vtt_rel_path = vtt_rel_path
        subtitle_job.status = "completed"
        subtitle_job.completed_at = utc_now()
        subtitle_job.provider = result.provider
        subtitle_job.provider_task_id = str(result.metadata.get("task_id") or "") or None
        subtitle_job.metadata = dict(result.metadata)
        subtitle_job.metadata["alignment_strategy"] = result.alignment_strategy

        project.add_event(
            "subtitle_align",
            "completed",
            "Subtitle timestamps aligned against final delivery audio",
            details={
                "job_id": subtitle_job.job_id,
                "provider": subtitle_job.provider,
                "alignment_strategy": result.alignment_strategy,
                "cue_count": len(result.cues),
            },
        )
        project.add_event(
            "subtitle_publish",
            "completed",
            "Subtitle sidecar assets ready",
            details={
                "srt_rel_path": srt_rel_path,
                "vtt_rel_path": vtt_rel_path,
            },
        )
        self._log(
            "subtitle generation completed",
            project_id=project.project_id,
            job_id=subtitle_job.job_id,
            alignment_strategy=result.alignment_strategy,
            cue_count=len(result.cues),
        )
        return self.repo.save(project)

    def _mark_subtitle_job_failed(
        self,
        project_id: str,
        subtitle_job_id: str,
        error: Exception,
    ) -> Project:
        project = self.repo.load(project_id)
        subtitle_job = project.subtitle_job
        if subtitle_job is None or subtitle_job.job_id != subtitle_job_id:
            return project
        subtitle_job.status = "failed"
        subtitle_job.failed_at = utc_now()
        subtitle_job.error_message = str(error)
        project.add_event(
            "subtitle_align",
            "failed",
            "Subtitle sidecar generation failed",
            details={"job_id": subtitle_job.job_id, "error": str(error)},
        )
        self._log(
            "subtitle generation failed",
            project_id=project.project_id,
            job_id=subtitle_job.job_id,
            error=str(error),
        )
        return self.repo.save(project)

    def _apply_subtitle_burn_output(
        self,
        project_id: str,
        subtitle_burn_job_id: str,
        output_rel_path: str,
    ) -> Project:
        project = self.repo.load(project_id)
        subtitle_burn_job = project.subtitle_burn_job
        if subtitle_burn_job is None or subtitle_burn_job.job_id != subtitle_burn_job_id:
            return project

        project.subtitle_burned_video_rel_path = output_rel_path
        subtitle_burn_job.status = "completed"
        subtitle_burn_job.completed_at = utc_now()
        subtitle_burn_job.output_rel_path = output_rel_path
        project.add_event(
            "subtitle_burn",
            "completed",
            "Subtitled video export completed",
            details={
                "job_id": subtitle_burn_job.job_id,
                "output_rel_path": output_rel_path,
            },
        )
        project.add_event(
            "delivery_publish",
            "completed",
            "Subtitled delivery asset ready",
            details={"subtitle_burned_video_rel_path": output_rel_path},
        )
        self._log(
            "subtitle burn export completed",
            project_id=project.project_id,
            job_id=subtitle_burn_job.job_id,
            output_rel_path=output_rel_path,
        )
        return self.repo.save(project)

    def _mark_subtitle_burn_failed(
        self,
        project_id: str,
        subtitle_burn_job_id: str,
        error: Exception,
    ) -> Project:
        project = self.repo.load(project_id)
        subtitle_burn_job = project.subtitle_burn_job
        if subtitle_burn_job is None or subtitle_burn_job.job_id != subtitle_burn_job_id:
            return project
        subtitle_burn_job.status = "failed"
        subtitle_burn_job.failed_at = utc_now()
        subtitle_burn_job.error_message = str(error)
        project.add_event(
            "subtitle_burn",
            "failed",
            "Subtitled video export failed",
            details={"job_id": subtitle_burn_job.job_id, "error": str(error)},
        )
        self._log(
            "subtitle burn export failed",
            project_id=project.project_id,
            job_id=subtitle_burn_job.job_id,
            error=str(error),
        )
        return self.repo.save(project)

    def _build_project_subtitle_text(self, project: Project) -> str:
        lines: list[str] = []
        for scene in project.scenes:
            if scene.speech_mode == "none":
                continue
            spoken_text = scene.spoken_text.strip()
            if not spoken_text:
                continue
            lines.append(spoken_text)
        return "\n".join(lines).strip()

    def _subtitle_service_is_configured(self) -> bool:
        if self.settings.subtitle_service_name == "volcengine_speech":
            return bool(
                self.settings.volcengine_speech_app_id
                and self.settings.volcengine_speech_access_token
            )
        return False

    def _subtitle_asr_fallback_is_configured(self) -> bool:
        return self._subtitle_service_is_configured()

    def _build_subtitle_client(self) -> SubtitleClient:
        if self.settings.subtitle_service_name == "volcengine_speech":
            return VolcengineSpeechSubtitleClient(self.settings)
        raise ValueError(f"Unsupported subtitle service: {self.settings.subtitle_service_name}")

    def _build_subtitle_asr_client(self) -> VolcengineSpeechAsrClient:
        if self.settings.subtitle_service_name == "volcengine_speech":
            return VolcengineSpeechAsrClient(self.settings)
        raise ValueError(f"Unsupported subtitle service: {self.settings.subtitle_service_name}")

    def _clear_existing_subtitle_delivery(self, project: Project) -> None:
        for rel_path in (
            project.subtitle_srt_rel_path,
            project.subtitle_vtt_rel_path,
            project.subtitle_burned_video_rel_path,
            f"{project.project_id}/delivery/final_delivery.zip",
        ):
            if not rel_path:
                continue
            (self.settings.artifact_dir / rel_path).unlink(missing_ok=True)
        project.subtitle_srt_rel_path = None
        project.subtitle_vtt_rel_path = None
        project.subtitle_burned_video_rel_path = None
        project.subtitle_job = None
        project.subtitle_burn_job = None

    def _begin_workflow_run(
        self,
        project: Project,
        workflow_run_job_id: str | None,
    ) -> WorkflowRunJob:
        current_job = project.workflow_run_job
        if workflow_run_job_id:
            if current_job is None or current_job.job_id != workflow_run_job_id:
                raise RuntimeError("Workflow run job mismatch")
            workflow_run_job = current_job
            project.add_event(
                "workflow_run",
                "started",
                "Workflow run started",
                details={"job_id": workflow_run_job.job_id},
            )
        else:
            attempt_count = current_job.attempt_count if current_job else 0
            workflow_run_job = WorkflowRunJob(
                job_id=f"wfr_{uuid4().hex[:10]}",
                status="running",
                attempt_count=attempt_count + 1,
                queued_at=utc_now(),
                metadata={
                    "provider": project.provider,
                    "scene_count": project.scene_count or self.settings.default_scene_count,
                    "workflow_mode": project.workflow_mode,
                },
            )
            project.workflow_run_job = workflow_run_job
            project.add_event(
                "workflow_run",
                "started",
                "Workflow run started",
                details={"job_id": workflow_run_job.job_id},
            )

        workflow_run_job.status = "running"
        workflow_run_job.started_at = workflow_run_job.started_at or utc_now()
        workflow_run_job.failed_at = None
        workflow_run_job.completed_at = None
        workflow_run_job.error_message = None
        project.status = "workflow_running"
        self._log(
            "workflow started",
            project_id=project.project_id,
            job_id=workflow_run_job.job_id,
            provider=project.provider,
        )
        return workflow_run_job

    def _mark_workflow_step_running(
        self,
        project_id: str,
        workflow_run_job_id: str,
        step_name: str,
    ) -> None:
        project = self.repo.load(project_id)
        workflow_run_job = project.workflow_run_job
        if workflow_run_job is None or workflow_run_job.job_id != workflow_run_job_id:
            raise RuntimeError("Workflow run job not found while marking running step")
        workflow_run_job.current_step = step_name
        self._log(
            "workflow step running",
            project_id=project.project_id,
            job_id=workflow_run_job.job_id,
            step=step_name,
        )
        self.repo.save(project)

    def _mark_workflow_step_completed(
        self,
        project_id: str,
        workflow_run_job_id: str,
        step_name: str,
    ) -> None:
        project = self.repo.load(project_id)
        workflow_run_job = project.workflow_run_job
        if workflow_run_job is None or workflow_run_job.job_id != workflow_run_job_id:
            raise RuntimeError("Workflow run job not found while marking completed step")
        workflow_run_job.last_completed_step = step_name
        workflow_run_job.current_step = None
        if step_name not in workflow_run_job.completed_steps:
            workflow_run_job.completed_steps.append(step_name)
        self._log(
            "workflow step completed",
            project_id=project.project_id,
            job_id=workflow_run_job.job_id,
            step=step_name,
        )
        self.repo.save(project)

    def _validate_scene_generation_preconditions(self, project: Project, scene: Scene) -> None:
        for current in project.scenes:
            if current.scene_id != scene.scene_id and current.video_job and current.video_job.status in {"queued", "running"}:
                raise ValueError("Another scene is already generating for this project.")
        if scene.status in {"queued", "generating"}:
            raise ValueError("Scene generation is already active for this scene.")
        if scene.status == "approved":
            raise ValueError("Scene is already approved.")
        self._validate_scene_duration_support(project.provider, scene.duration_seconds)
        if scene.first_frame_source == "upload" and not scene.first_frame_image:
            raise ValueError("Upload a first-frame image before generating this scene.")
        if scene.first_frame_source == "continuity":
            if not scene.depends_on_scene:
                raise ValueError("Continuity first-frame mode requires a previous scene.")
            previous_scene = self._find_scene(project.scenes, {"scene_id": scene.depends_on_scene})
            if previous_scene is None or not previous_scene.final_frame_rel_path:
                raise ValueError("Continuity first-frame mode requires the previous scene final frame.")
        if project.workflow_mode != "hitl":
            return
        for previous_scene in sorted(project.scenes, key=lambda item: item.index):
            if previous_scene.index >= scene.index:
                break
            if previous_scene.status != "approved":
                raise ValueError("Approve earlier scenes before generating the next scene.")

    def _sync_hitl_project_status(self, project: Project) -> None:
        if project.workflow_mode != "hitl":
            return
        if any(scene.status == "failed" for scene in project.scenes):
            project.status = "failed"
            return
        if any(scene.status in {"queued", "generating"} for scene in project.scenes):
            project.status = "scene_videos_generating"
            return
        if any(scene.status == "pending_review" for scene in project.scenes):
            project.status = "awaiting_scene_review"
            return
        if project.scenes and all(scene.status == "approved" for scene in project.scenes):
            project.status = "ready_for_compose"
            return
        if any(scene.status == "approved" for scene in project.scenes):
            project.status = "ready_for_next_scene"
            return
        project.status = "ready_for_scene_generation"

    def _validate_scene_prompt_update(self, project: Project, scene: Scene) -> None:
        if scene.video_job and scene.video_job.status in {"queued", "running"}:
            raise ValueError("Cannot update scene prompt while generation is in progress.")
        if project.workflow_run_job and project.workflow_run_job.status in {"queued", "running"}:
            raise ValueError("Cannot update scene prompt while workflow run is active.")
        if scene.status == "approved":
            raise ValueError("Approved scenes are read-only. Reopen support is not available yet.")

    def _serialize_hitl_state(self, project: Project) -> dict[str, Any]:
        approved_scene_count = sum(1 for scene in project.scenes if scene.status == "approved")
        pending_review_count = sum(1 for scene in project.scenes if scene.status == "pending_review")
        active_scene = next(
            (
                scene.scene_id
                for scene in sorted(project.scenes, key=lambda item: item.index)
                if scene.status in {"queued", "generating", "pending_review", "planned", "draft", "failed"}
            ),
            None,
        )
        return {
            "workflow_mode": project.workflow_mode,
            "approved_scene_count": approved_scene_count,
            "pending_review_count": pending_review_count,
            "next_scene_id": active_scene,
            "can_compose": bool(project.scenes) and all(scene.status == "approved" for scene in project.scenes),
        }

    def _available_scene_actions(self, project: Project, scene: Scene) -> list[str]:
        actions: list[str] = []
        if project.workflow_mode == "hitl":
            if scene.status == "pending_review" and scene.video_rel_path:
                actions.append("approve")
            try:
                self._validate_scene_generation_preconditions(project, scene)
            except ValueError:
                return actions
            actions.append("generate")
            return actions
        if scene.status in {"draft", "planned", "failed"}:
            actions.append("generate")
        return actions

    def _get_workflow_future(self, project_id: str) -> Future[Project] | None:
        with self._futures_lock:
            return self._workflow_futures.get(project_id)

    def _get_scene_future(self, project_id: str) -> Future[Project] | None:
        with self._futures_lock:
            future = self._scene_futures.get(project_id)
            if future and future.done():
                self._scene_futures.pop(project_id, None)
                return None
            return future

    def _get_subtitle_future(self, project_id: str) -> Future[Project] | None:
        with self._futures_lock:
            future = self._subtitle_futures.get(project_id)
            if future and future.done():
                self._subtitle_futures.pop(project_id, None)
                return None
            return future

    def _get_subtitle_burn_future(self, project_id: str) -> Future[Project] | None:
        with self._futures_lock:
            future = self._subtitle_burn_futures.get(project_id)
            if future and future.done():
                self._subtitle_burn_futures.pop(project_id, None)
                return None
            return future

    def _scene_duration_bounds(self, provider_name: str) -> tuple[int, int] | None:
        capabilities = get_video_provider(self.settings, provider_name).get_capabilities()
        min_duration = capabilities.get("min_scene_duration_seconds")
        max_duration = capabilities.get("max_scene_duration_seconds")
        if not isinstance(min_duration, int) or not isinstance(max_duration, int):
            return None
        if min_duration <= 0 or max_duration < min_duration:
            return None
        return min_duration, max_duration

    def _validate_scene_duration_support(self, provider_name: str, duration_seconds: int) -> None:
        bounds = self._scene_duration_bounds(provider_name)
        if not bounds:
            return
        min_duration, max_duration = bounds
        if min_duration <= duration_seconds <= max_duration:
            return
        raise ValueError(
            f"Provider {provider_name} does not support {duration_seconds}s scene duration. "
            f"Supported per-scene durations: {min_duration}-{max_duration}s."
        )

    def _validate_project_scene_duration_distribution(
        self,
        *,
        provider_name: str,
        target_duration_seconds: int,
        scene_count: int,
    ) -> None:
        bounds = self._scene_duration_bounds(provider_name)
        if not bounds:
            return
        min_duration, max_duration = bounds

        durations = distribute_duration(target_duration_seconds, scene_count)
        if all(min_duration <= duration <= max_duration for duration in durations):
            return

        raise ValueError(
            f"Provider {provider_name} cannot split {target_duration_seconds}s across {scene_count} scenes. "
            f"Current scene durations would be {durations}, but supported per-scene durations are {min_duration}-{max_duration}s."
        )

    def _release_scene_future(self, project_id: str, scene_id: str, scene_job_id: str) -> None:
        with self._futures_lock:
            current_project = self.repo.load(project_id)
            current_scene = self._find_scene(current_project.scenes, {"scene_id": scene_id})
            current_job = current_scene.video_job if current_scene else None
            if current_job is not None and current_job.job_id == scene_job_id:
                self._scene_futures.pop(project_id, None)

    def _release_subtitle_future(self, project_id: str, subtitle_job_id: str) -> None:
        with self._futures_lock:
            current_project = self.repo.load(project_id)
            current_job = current_project.subtitle_job
            if current_job is not None and current_job.job_id == subtitle_job_id:
                self._subtitle_futures.pop(project_id, None)

    def _release_subtitle_burn_future(self, project_id: str, subtitle_burn_job_id: str) -> None:
        with self._futures_lock:
            current_project = self.repo.load(project_id)
            current_job = current_project.subtitle_burn_job
            if current_job is not None and current_job.job_id == subtitle_burn_job_id:
                self._subtitle_burn_futures.pop(project_id, None)

    def _log(self, message: str, **fields: Any) -> None:
        details = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
        if details:
            self.logger.info("%s | %s", message, details)
            return
        self.logger.info(message)
