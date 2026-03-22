from __future__ import annotations

from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.context_assembler import build_project_guidance_context
from video_workflow_service.workflow.contracts import (
    StoryPlanInput,
    StoryPlanOutput,
    StoryPlanSceneRole,
)
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    STORY_PLAN_TEMPLATE_VERSION,
    build_story_plan_messages,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


def distribute_duration(total_seconds: int, scene_count: int) -> list[int]:
    base = total_seconds // scene_count
    remainder = total_seconds % scene_count
    durations = [base for _ in range(scene_count)]
    for idx in range(remainder):
        durations[idx] += 1
    return [max(5, duration) for duration in durations]


def build_story_plan(
    contract: StoryPlanInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> StoryPlanOutput:
    approximate_scene_durations = contract.approximate_scene_durations or distribute_duration(
        contract.target_duration_seconds,
        contract.scene_count,
    )
    project_guidance = dict(contract.project_guidance_context) or build_project_guidance_context(
        step_name="story_plan",
        target_duration_seconds=contract.target_duration_seconds,
        scene_count=contract.scene_count,
        input_language=contract.input_language,
        dialogue_language=contract.dialogue_language,
        audio_language=contract.audio_language,
        creative_intent=contract.creative_intent,
        planning_notes=contract.planning_notes,
        dialogue_lines=contract.dialogue_lines,
        scene1_first_frame_source=contract.scene1_first_frame_source,
        scene1_first_frame_prompt=contract.scene1_first_frame_prompt,
        scene1_first_frame_analysis=contract.scene1_first_frame_analysis,
    )
    input_payload = {
        "raw_prompt": contract.raw_prompt,
        "optimized_prompt": contract.optimized_prompt,
        "target_duration_seconds": contract.target_duration_seconds,
        "scene_count": contract.scene_count,
        "input_language": contract.input_language,
        "dialogue_language": contract.dialogue_language,
        "audio_language": contract.audio_language,
        "approximate_scene_durations": approximate_scene_durations,
        "dialogue_lines": contract.dialogue_lines,
        "creative_intent": contract.creative_intent,
        "planning_notes": contract.planning_notes,
        "scene1_first_frame_source": contract.scene1_first_frame_source,
        "scene1_first_frame_prompt": contract.scene1_first_frame_prompt,
        "scene1_first_frame_analysis": contract.scene1_first_frame_analysis,
        "project_guidance": project_guidance,
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="story_plan",
        template_version=STORY_PLAN_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=build_story_plan_messages,
        validator=lambda payload: _validate_story_plan_payload(payload, approximate_scene_durations),
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    return output


def story_plan_step(
    contract: StoryPlanInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> StoryPlanOutput:
    return build_story_plan(
        contract,
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
    )


def _validate_story_plan_payload(payload: dict[str, Any], durations: list[int]) -> StoryPlanOutput:
    raw_scene_roles = payload.get("scene_roles")
    if not isinstance(raw_scene_roles, list) or not raw_scene_roles:
        raise ValueError("Story plan output must contain a scene_roles list")
    if len(raw_scene_roles) != len(durations):
        raise ValueError("Story plan output returned the wrong number of scene roles")

    scene_roles: list[StoryPlanSceneRole] = []
    seen_ids: list[str] = []
    for index, raw_role in enumerate(raw_scene_roles, start=1):
        if not isinstance(raw_role, dict):
            raise ValueError("Each story plan scene role must be a JSON object")
        scene_id = str(raw_role.get("scene_id", f"scene-{index:02d}")).strip() or f"scene-{index:02d}"
        expected_scene_id = f"scene-{index:02d}"
        if scene_id != expected_scene_id:
            raise ValueError("Story plan scene roles must align with the planned scene order")
        if scene_id in seen_ids:
            raise ValueError(f"Duplicate story plan scene role for {scene_id}")
        seen_ids.append(scene_id)
        scene_roles.append(
            StoryPlanSceneRole(
                scene_id=scene_id,
                scene_index=index,
                duration_seconds=durations[index - 1],
                role_label=_require_string(raw_role, "role_label"),
                narrative_purpose=_require_string(raw_role, "narrative_purpose"),
                story_advance_goal=_require_string(raw_role, "story_advance_goal"),
                pacing_intent=_require_string(raw_role, "pacing_intent"),
                information_load=_require_string(raw_role, "information_load"),
                speech_expectation=_require_string(raw_role, "speech_expectation"),
            )
        )

    return StoryPlanOutput(
        overall_story_arc=_require_string(payload, "overall_story_arc"),
        dialogue_strategy=_require_string(payload, "dialogue_strategy"),
        scene_roles=scene_roles,
        planning_notes=str(payload.get("planning_notes", "")).strip(),
    )


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"Story plan output missing {key}")
    return value
