from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_workflow_service.domain.models import Scene
from video_workflow_service.providers.base import VideoGenerationRequest, VideoGenerationResult


@dataclass(slots=True)
class LanguageDetectInput:
    raw_prompt: str


@dataclass(slots=True)
class LanguageDetectOutput:
    input_language: str
    dialogue_language: str
    audio_language: str
    confidence: str = ""
    mixed_language: bool = False
    notes: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CharacterAnchorCandidate:
    character_id: str
    display_name: str
    story_role: str = ""
    visual_description: str = ""
    reference_prompt: str = ""


@dataclass(slots=True)
class CharacterAnchorInput:
    raw_prompt: str
    optimized_prompt: str = ""
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    scene1_first_frame_source: str = ""
    scene1_first_frame_image: str | None = None
    scene1_first_frame_analysis: dict[str, Any] = field(default_factory=dict)
    project_guidance_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CharacterAnchorOutput:
    characters: list[CharacterAnchorCandidate] = field(default_factory=list)
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PromptOptimizationInput:
    raw_prompt: str
    target_duration_seconds: int = 15
    scene_count: int = 3
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    scene1_first_frame_source: str = ""
    scene1_first_frame_prompt: str = ""
    scene1_first_frame_analysis: dict[str, Any] = field(default_factory=dict)
    project_guidance_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PromptOptimizationOutput:
    optimized_prompt: str
    creative_intent: str = ""
    style_guardrails: list[str] = field(default_factory=list)
    dialogue_lines: list[str] = field(default_factory=list)
    planning_notes: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StoryPlanSceneRole:
    scene_id: str
    scene_index: int
    duration_seconds: int
    role_label: str = ""
    narrative_purpose: str = ""
    story_advance_goal: str = ""
    pacing_intent: str = ""
    information_load: str = ""
    speech_expectation: str = ""


@dataclass(slots=True)
class StoryPlanInput:
    raw_prompt: str
    optimized_prompt: str
    target_duration_seconds: int
    scene_count: int
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    approximate_scene_durations: list[int] = field(default_factory=list)
    dialogue_lines: list[str] = field(default_factory=list)
    creative_intent: str = ""
    planning_notes: str = ""
    scene1_first_frame_source: str = ""
    scene1_first_frame_prompt: str = ""
    scene1_first_frame_analysis: dict[str, Any] = field(default_factory=dict)
    project_guidance_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StoryPlanOutput:
    overall_story_arc: str = ""
    dialogue_strategy: str = ""
    scene_roles: list[StoryPlanSceneRole] = field(default_factory=list)
    planning_notes: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SceneCharacterCastSceneInput:
    scene_id: str
    scene_index: int
    title: str
    narrative: str
    visual_goal: str
    continuity_notes: str
    duration_seconds: int
    story_role: str = ""
    story_purpose: str = ""
    story_advance_goal: str = ""
    pacing_intent: str = ""


@dataclass(slots=True)
class SceneCharacterCastInput:
    raw_prompt: str
    optimized_prompt: str
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    overall_story_arc: str = ""
    character_cards: list[dict[str, Any]] = field(default_factory=list)
    scenes: list[SceneCharacterCastSceneInput] = field(default_factory=list)
    project_guidance_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SceneCharacterParticipation:
    scene_id: str
    participating_character_ids: list[str] = field(default_factory=list)
    primary_character_id: str | None = None
    character_presence_notes: str = ""


@dataclass(slots=True)
class SceneCharacterCastOutput:
    scenes: list[SceneCharacterParticipation] = field(default_factory=list)
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScenePlanningInput:
    optimized_prompt: str
    target_duration_seconds: int
    scene_count: int
    raw_prompt: str = ""
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    dialogue_lines: list[str] = field(default_factory=list)
    creative_intent: str = ""
    planning_notes: str = ""
    scene1_first_frame_source: str = ""
    scene1_first_frame_prompt: str = ""
    scene1_first_frame_analysis: dict[str, Any] = field(default_factory=dict)
    overall_story_arc: str = ""
    dialogue_strategy: str = ""
    story_plan_scene_roles: list[StoryPlanSceneRole] = field(default_factory=list)
    project_guidance_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScenePlanningOutput:
    scenes: list[Scene]
    planning_notes: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DialogueAllocationSceneInput:
    scene_id: str
    scene_index: int
    title: str
    narrative: str
    visual_goal: str
    continuity_notes: str
    duration_seconds: int
    story_role: str = ""
    story_purpose: str = ""
    story_advance_goal: str = ""
    pacing_intent: str = ""
    information_load: str = ""
    speech_expectation: str = ""
    depends_on_scene: str | None = None


@dataclass(slots=True)
class DialogueAllocationInput:
    raw_prompt: str
    optimized_prompt: str
    dialogue_lines: list[str]
    scenes: list[DialogueAllocationSceneInput]
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    creative_intent: str = ""
    planning_notes: str = ""
    overall_story_arc: str = ""
    dialogue_strategy: str = ""
    project_guidance_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DialogueAllocation:
    scene_id: str
    spoken_text: str = ""
    speech_mode: str = "none"
    delivery_notes: str = ""


@dataclass(slots=True)
class DialogueAllocationOutput:
    allocations: list[DialogueAllocation] = field(default_factory=list)
    planning_notes: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FirstFrameAnalyzeInput:
    scene_id: str
    scene_index: int
    first_frame_source: str
    image_input: str
    title: str
    narrative: str
    visual_goal: str


@dataclass(slots=True)
class FirstFrameAnalyzeOutput:
    subject_presence: str = ""
    subject_pose: str = ""
    hand_prop_state: str = ""
    prop_description: str = ""
    framing: str = ""
    setting: str = ""
    lighting: str = ""
    wardrobe: str = ""
    continuation_constraints: str = ""
    analysis_notes: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_presence": self.subject_presence,
            "subject_pose": self.subject_pose,
            "hand_prop_state": self.hand_prop_state,
            "prop_description": self.prop_description,
            "framing": self.framing,
            "setting": self.setting,
            "lighting": self.lighting,
            "wardrobe": self.wardrobe,
            "continuation_constraints": self.continuation_constraints,
            "analysis_notes": self.analysis_notes,
        }


@dataclass(slots=True)
class ScenePromptRenderInput:
    scene_id: str
    scene_index: int
    scene_count: int
    title: str
    narrative: str
    visual_goal: str
    spoken_text: str
    speech_mode: str
    delivery_notes: str
    continuity_notes: str
    duration_seconds: int
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    working_prompt: str = ""
    first_frame_source: str = "auto_generate"
    first_frame_prompt: str = ""
    first_frame_analysis: dict[str, Any] = field(default_factory=dict)
    aspect_ratio: str = "9:16"
    project_guidance_context: dict[str, Any] = field(default_factory=dict)
    scene_guidance_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScenePromptRenderOutput:
    rendered_prompt: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StoryboardBinding:
    scene_id: str | None = None
    scene_index: int | None = None
    first_frame_source: str | None = None
    first_frame_image: str | None = None
    reference_image: str | None = None
    storyboard_notes: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "StoryboardBinding":
        scene_index = payload.get("scene_index")
        try:
            scene_index_value = int(scene_index) if scene_index is not None else None
        except (TypeError, ValueError):
            scene_index_value = None
        reference_image = payload.get("reference_image")
        first_frame_image = payload.get("first_frame_image")
        first_frame_source = payload.get("first_frame_source")
        return cls(
            scene_id=payload.get("scene_id"),
            scene_index=scene_index_value,
            first_frame_source=str(first_frame_source).strip() if first_frame_source is not None else None,
            first_frame_image=first_frame_image.strip()
            if isinstance(first_frame_image, str) and first_frame_image.strip()
            else None,
            reference_image=reference_image.strip()
            if isinstance(reference_image, str) and reference_image.strip()
            else None,
            storyboard_notes=str(payload.get("storyboard_notes", "")).strip(),
        )

    def validate(self) -> None:
        if self.scene_id is None and self.scene_index is None:
            raise ValueError("Storyboard item must contain scene_id or scene_index")
        if self.first_frame_source and self.first_frame_source not in {"auto_generate", "upload", "continuity"}:
            raise ValueError("first_frame_source must be auto_generate, upload, or continuity")
        if self.first_frame_source == "upload" and not self.first_frame_image:
            raise ValueError("first_frame_source=upload requires first_frame_image")
        if not self.reference_image and not self.storyboard_notes and not self.first_frame_source and not self.first_frame_image:
            raise ValueError(
                "Storyboard item must contain reference_image, storyboard_notes, first_frame_source, or first_frame_image"
            )


@dataclass(slots=True)
class StoryboardUploadInput:
    items: list[StoryboardBinding] = field(default_factory=list)

    @classmethod
    def from_payloads(cls, payloads: list[dict[str, Any]]) -> "StoryboardUploadInput":
        bindings: list[StoryboardBinding] = []
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            binding = StoryboardBinding.from_payload(payload)
            binding.validate()
            bindings.append(binding)
        return cls(items=bindings)


@dataclass(slots=True)
class StoryboardUploadOutput:
    updated_scene_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScenePromptUpdateInput:
    prompt: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScenePromptUpdateInput":
        return cls(prompt=str(payload.get("prompt", "")).strip())

    def validate(self) -> None:
        if not self.prompt:
            raise ValueError("Scene prompt must not be empty")


@dataclass(slots=True)
class ScenePromptRevisionRequest:
    feedback: str
    scope: str = "prompt_only"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScenePromptRevisionRequest":
        return cls(
            feedback=str(payload.get("feedback", "")).strip(),
            scope=str(payload.get("scope", "prompt_only")).strip().lower() or "prompt_only",
        )

    def validate(self) -> None:
        if not self.feedback:
            raise ValueError("Scene feedback must not be empty")
        if self.scope not in {"prompt_only", "opening_still_and_prompt"}:
            raise ValueError("scope must be prompt_only or opening_still_and_prompt")


@dataclass(slots=True)
class ScenePromptRevisionInput:
    scene_id: str
    scene_index: int
    scene_count: int
    raw_prompt: str
    current_prompt: str
    current_rendered_prompt: str = ""
    title: str = ""
    narrative: str = ""
    visual_goal: str = ""
    spoken_text: str = ""
    speech_mode: str = "none"
    delivery_notes: str = ""
    continuity_notes: str = ""
    first_frame_source: str = "auto_generate"
    first_frame_prompt: str = ""
    first_frame_analysis: dict[str, Any] = field(default_factory=dict)
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    feedback: str = ""
    requested_scope: str = "prompt_only"
    project_guidance_context: dict[str, Any] = field(default_factory=dict)
    scene_guidance_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScenePromptRevisionOutput:
    outcome: str
    revised_prompt: str = ""
    revised_first_frame_prompt: str = ""
    change_summary: str = ""
    rejection_reason: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SceneGenerationInput:
    project_id: str
    provider: str
    scene_id: str
    scene_index: int
    prompt: str
    duration_seconds: int
    aspect_ratio: str
    first_frame_source: str = "auto_generate"
    first_frame_image: str | None = None
    reference_image: str | None = None
    continuity_source_scene_id: str | None = None
    continuity_image: str | None = None
    storyboard_notes: str = ""
    audio_language: str = ""
    generate_audio: bool = True

    def to_provider_request(self) -> VideoGenerationRequest:
        provider_image_url = self.reference_image
        provider_first_frame_image = None
        if self.first_frame_source in {"auto_generate", "upload", "continuity"}:
            provider_first_frame_image = self.first_frame_image
        return VideoGenerationRequest(
            project_id=self.project_id,
            scene_id=self.scene_id,
            scene_index=self.scene_index,
            prompt=self.prompt,
            duration_seconds=self.duration_seconds,
            aspect_ratio=self.aspect_ratio,
            image_url=provider_image_url,
            first_frame_image=provider_first_frame_image,
            storyboard_notes=self.storyboard_notes,
            audio_language=self.audio_language,
            generate_audio=self.generate_audio,
        )


@dataclass(slots=True)
class SceneGenerationOutput:
    scene_id: str
    provider: str
    model: str
    generation_mode: str
    video_rel_path: str
    final_frame_rel_path: str
    provider_task_id: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_provider_result(
        cls,
        request: SceneGenerationInput,
        result: VideoGenerationResult,
    ) -> "SceneGenerationOutput":
        task_id = result.metadata.get("task_id")
        return cls(
            scene_id=request.scene_id,
            provider=result.provider,
            model=result.model,
            generation_mode=result.generation_mode,
            video_rel_path=result.video_rel_path,
            final_frame_rel_path=result.final_frame_rel_path,
            provider_task_id=str(task_id) if isinstance(task_id, str) and task_id else None,
            provider_metadata=dict(result.metadata),
        )


@dataclass(slots=True)
class FinalCompositionInput:
    project_id: str
    scene_ids: list[str]
    clip_paths: list[Path]
    output_rel_path: str


@dataclass(slots=True)
class FinalCompositionOutput:
    final_video_rel_path: str
    metadata: dict[str, Any] = field(default_factory=dict)
