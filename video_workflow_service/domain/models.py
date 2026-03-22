from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class WorkflowEvent:
    step: str
    status: str
    message: str
    timestamp: str = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowEvent":
        return cls(
            step=str(payload.get("step", "")),
            status=str(payload.get("status", "")),
            message=str(payload.get("message", "")),
            timestamp=str(payload.get("timestamp", utc_now())),
            details=dict(payload.get("details") or {}),
        )


@dataclass(slots=True)
class SceneVideoJob:
    job_id: str
    scene_id: str
    provider: str
    status: str = "pending"
    attempt_count: int = 0
    generation_mode: str | None = None
    continuity_source_scene_id: str | None = None
    provider_task_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    error_message: str | None = None
    video_rel_path: str | None = None
    final_frame_rel_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SceneVideoJob":
        return cls(
            job_id=str(payload.get("job_id", "")),
            scene_id=str(payload.get("scene_id", "")),
            provider=str(payload.get("provider", "")),
            status=str(payload.get("status", "pending")),
            attempt_count=int(payload.get("attempt_count", 0)),
            generation_mode=payload.get("generation_mode"),
            continuity_source_scene_id=payload.get("continuity_source_scene_id"),
            provider_task_id=payload.get("provider_task_id"),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            failed_at=payload.get("failed_at"),
            error_message=payload.get("error_message"),
            video_rel_path=payload.get("video_rel_path"),
            final_frame_rel_path=payload.get("final_frame_rel_path"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class FinalVideoJob:
    job_id: str
    status: str = "pending"
    attempt_count: int = 0
    provider: str = "ffmpeg"
    input_scene_ids: list[str] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    error_message: str | None = None
    final_video_rel_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FinalVideoJob":
        return cls(
            job_id=str(payload.get("job_id", "")),
            status=str(payload.get("status", "pending")),
            attempt_count=int(payload.get("attempt_count", 0)),
            provider=str(payload.get("provider", "ffmpeg")),
            input_scene_ids=[str(item) for item in payload.get("input_scene_ids", [])],
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            failed_at=payload.get("failed_at"),
            error_message=payload.get("error_message"),
            final_video_rel_path=payload.get("final_video_rel_path"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class WorkflowRunJob:
    job_id: str
    status: str = "pending"
    attempt_count: int = 0
    queued_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    error_message: str | None = None
    current_step: str | None = None
    last_completed_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowRunJob":
        return cls(
            job_id=str(payload.get("job_id", "")),
            status=str(payload.get("status", "pending")),
            attempt_count=int(payload.get("attempt_count", 0)),
            queued_at=payload.get("queued_at"),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            failed_at=payload.get("failed_at"),
            error_message=payload.get("error_message"),
            current_step=payload.get("current_step"),
            last_completed_step=payload.get("last_completed_step"),
            completed_steps=[str(item) for item in payload.get("completed_steps", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class CharacterCard:
    character_id: str
    display_name: str
    story_role: str = ""
    visual_description: str = ""
    reference_image: str | None = None
    reference_prompt: str = ""
    approval_status: str = "pending"
    source: str = "generated"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CharacterCard":
        return cls(
            character_id=str(payload.get("character_id", "")),
            display_name=str(payload.get("display_name", "")),
            story_role=str(payload.get("story_role", "")),
            visual_description=str(payload.get("visual_description", "")),
            reference_image=payload.get("reference_image"),
            reference_prompt=str(payload.get("reference_prompt", "")),
            approval_status=str(payload.get("approval_status", "pending")),
            source=str(payload.get("source", "generated")),
        )


@dataclass(slots=True)
class Scene:
    scene_id: str
    index: int
    title: str
    duration_seconds: int
    narrative: str
    participating_character_ids: list[str] = field(default_factory=list)
    primary_character_id: str | None = None
    character_presence_notes: str = ""
    story_role: str = ""
    story_purpose: str = ""
    story_advance_goal: str = ""
    pacing_intent: str = ""
    information_load: str = ""
    speech_expectation: str = ""
    prompt: str = ""
    rendered_prompt: str = ""
    approved_prompt: str = ""
    prompt_stale: bool = False
    prompt_stale_reasons: list[str] = field(default_factory=list)
    visual_goal: str = ""
    spoken_text: str = ""
    speech_mode: str = "none"
    delivery_notes: str = ""
    continuity_notes: str = ""
    first_frame_source: str = "auto_generate"
    first_frame_image: str | None = None
    first_frame_prompt: str = ""
    first_frame_origin: str | None = None
    first_frame_status: str = "pending"
    first_frame_analysis: dict[str, Any] = field(default_factory=dict)
    first_frame_job: dict[str, Any] = field(default_factory=dict)
    reference_image: str | None = None
    storyboard_notes: str = ""
    depends_on_scene: str | None = None
    status: str = "draft"
    review_status: str = "pending_generation"
    video_rel_path: str | None = None
    final_frame_rel_path: str | None = None
    generation_mode: str = "text_to_video"
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    video_job: SceneVideoJob | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Scene":
        video_job_payload = payload.get("video_job")
        return cls(
            scene_id=str(payload.get("scene_id", "")),
            index=int(payload.get("index", 0)),
            title=str(payload.get("title", "")),
            duration_seconds=int(payload.get("duration_seconds", 0)),
            participating_character_ids=[str(item) for item in payload.get("participating_character_ids", [])],
            primary_character_id=payload.get("primary_character_id"),
            character_presence_notes=str(payload.get("character_presence_notes", "")),
            story_role=str(payload.get("story_role", "")),
            story_purpose=str(payload.get("story_purpose", "")),
            story_advance_goal=str(payload.get("story_advance_goal", "")),
            pacing_intent=str(payload.get("pacing_intent", "")),
            information_load=str(payload.get("information_load", "")),
            speech_expectation=str(payload.get("speech_expectation", "")),
            prompt=str(payload.get("prompt", payload.get("rendered_prompt", ""))),
            rendered_prompt=str(payload.get("rendered_prompt", payload.get("prompt", ""))),
            approved_prompt=str(payload.get("approved_prompt", "")),
            prompt_stale=bool(payload.get("prompt_stale", False)),
            prompt_stale_reasons=[str(item) for item in payload.get("prompt_stale_reasons", [])],
            narrative=str(payload.get("narrative", "")),
            visual_goal=str(payload.get("visual_goal", "")),
            spoken_text=str(payload.get("spoken_text", "")),
            speech_mode=str(payload.get("speech_mode", "none")),
            delivery_notes=str(payload.get("delivery_notes", "")),
            continuity_notes=str(payload.get("continuity_notes", "")),
            first_frame_source=str(payload.get("first_frame_source", "auto_generate")),
            first_frame_image=payload.get("first_frame_image"),
            first_frame_prompt=str(payload.get("first_frame_prompt", "")),
            first_frame_origin=payload.get("first_frame_origin"),
            first_frame_status=str(payload.get("first_frame_status", "pending")),
            first_frame_analysis=dict(payload.get("first_frame_analysis") or {}),
            first_frame_job=dict(payload.get("first_frame_job") or {}),
            reference_image=payload.get("reference_image"),
            storyboard_notes=str(payload.get("storyboard_notes", "")),
            depends_on_scene=payload.get("depends_on_scene"),
            status=str(payload.get("status", "draft")),
            review_status=str(payload.get("review_status", "pending_generation")),
            video_rel_path=payload.get("video_rel_path"),
            final_frame_rel_path=payload.get("final_frame_rel_path"),
            generation_mode=str(payload.get("generation_mode", "text_to_video")),
            provider_metadata=dict(payload.get("provider_metadata") or {}),
            video_job=SceneVideoJob.from_dict(video_job_payload)
            if isinstance(video_job_payload, dict)
            else None,
        )


@dataclass(slots=True)
class Project:
    project_id: str
    title: str
    raw_prompt: str
    target_duration_seconds: int
    aspect_ratio: str
    provider: str
    workflow_mode: str = "auto"
    scene_count: int | None = None
    scene1_first_frame_source: str = "auto_generate"
    scene1_first_frame_image: str | None = None
    scene1_first_frame_prompt: str = ""
    scene1_first_frame_origin: str | None = None
    scene1_first_frame_status: str = "pending"
    scene1_first_frame_analysis: dict[str, Any] = field(default_factory=dict)
    scene1_first_frame_job: dict[str, Any] = field(default_factory=dict)
    detected_input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    language_detection_confidence: str = ""
    language_detection_notes: str = ""
    character_cards: list[CharacterCard] = field(default_factory=list)
    status: str = "draft"
    optimized_prompt: str | None = None
    scenes: list[Scene] = field(default_factory=list)
    final_video_rel_path: str | None = None
    final_video_job: FinalVideoJob | None = None
    workflow_run_job: WorkflowRunJob | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    events: list[WorkflowEvent] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = utc_now()

    def add_event(
        self,
        step: str,
        status: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            WorkflowEvent(
                step=step,
                status=status,
                message=message,
                details=dict(details or {}),
            )
        )
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Project":
        final_video_job_payload = payload.get("final_video_job")
        workflow_run_job_payload = payload.get("workflow_run_job")
        return cls(
            project_id=str(payload.get("project_id", "")),
            title=str(payload.get("title", "")),
            raw_prompt=str(payload.get("raw_prompt", "")),
            target_duration_seconds=int(payload.get("target_duration_seconds", 0)),
            aspect_ratio=str(payload.get("aspect_ratio", "16:9")),
            provider=str(payload.get("provider", "mock")),
            workflow_mode=str(payload.get("workflow_mode", "auto")),
            scene_count=int(payload["scene_count"]) if payload.get("scene_count") is not None else None,
            scene1_first_frame_source=str(payload.get("scene1_first_frame_source", "auto_generate")),
            scene1_first_frame_image=payload.get("scene1_first_frame_image"),
            scene1_first_frame_prompt=str(payload.get("scene1_first_frame_prompt", "")),
            scene1_first_frame_origin=payload.get("scene1_first_frame_origin"),
            scene1_first_frame_status=str(payload.get("scene1_first_frame_status", "pending")),
            scene1_first_frame_analysis=dict(payload.get("scene1_first_frame_analysis") or {}),
            scene1_first_frame_job=dict(payload.get("scene1_first_frame_job") or {}),
            detected_input_language=str(payload.get("detected_input_language", "")),
            dialogue_language=str(payload.get("dialogue_language", "")),
            audio_language=str(payload.get("audio_language", "")),
            language_detection_confidence=str(payload.get("language_detection_confidence", "")),
            language_detection_notes=str(payload.get("language_detection_notes", "")),
            character_cards=[CharacterCard.from_dict(item) for item in payload.get("character_cards", [])],
            status=str(payload.get("status", "draft")),
            optimized_prompt=payload.get("optimized_prompt"),
            scenes=[Scene.from_dict(item) for item in payload.get("scenes", [])],
            final_video_rel_path=payload.get("final_video_rel_path"),
            final_video_job=FinalVideoJob.from_dict(final_video_job_payload)
            if isinstance(final_video_job_payload, dict)
            else None,
            workflow_run_job=WorkflowRunJob.from_dict(workflow_run_job_payload)
            if isinstance(workflow_run_job_payload, dict)
            else None,
            created_at=str(payload.get("created_at", utc_now())),
            updated_at=str(payload.get("updated_at", utc_now())),
            events=[WorkflowEvent.from_dict(item) for item in payload.get("events", [])],
        )
