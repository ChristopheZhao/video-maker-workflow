from __future__ import annotations

from typing import Any

from video_workflow_service.domain.models import Scene
from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.contracts import (
    DialogueAllocationInput,
    DialogueAllocationSceneInput,
    ScenePlanningInput,
    ScenePlanningOutput,
    StoryPlanSceneRole,
)
from video_workflow_service.workflow.context_assembler import build_project_guidance_context
from video_workflow_service.workflow.dialogue_allocate import allocate_dialogue_step
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    SCENE_PLAN_TEMPLATE_VERSION,
    build_scene_plan_messages,
)
from video_workflow_service.workflow.scene_list_contracts import (
    build_scene_list_contract_repair_prompt,
    is_scene_list_contract_violation,
)
from video_workflow_service.workflow.story_plan import distribute_duration
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


def build_scene_plan(
    contract: ScenePlanningInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> ScenePlanningOutput:
    durations = distribute_duration(contract.target_duration_seconds, contract.scene_count)
    project_guidance = dict(contract.project_guidance_context) or build_project_guidance_context(
        step_name="scene_plan",
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
        "dialogue_lines": contract.dialogue_lines,
        "creative_intent": contract.creative_intent,
        "planning_notes": contract.planning_notes,
        "scene1_first_frame_source": contract.scene1_first_frame_source,
        "scene1_first_frame_prompt": contract.scene1_first_frame_prompt,
        "scene1_first_frame_analysis": contract.scene1_first_frame_analysis,
        "overall_story_arc": contract.overall_story_arc,
        "dialogue_strategy": contract.dialogue_strategy,
        "expected_scene_count": len(durations),
        "expected_scene_ids": [f"scene-{index:02d}" for index in range(1, len(durations) + 1)],
        "story_plan_scene_roles": [
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
            for role in contract.story_plan_scene_roles
        ],
        "approximate_scene_durations": durations,
        "project_guidance": project_guidance,
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="scene_plan",
        template_version=SCENE_PLAN_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=build_scene_plan_messages,
        validator=lambda payload: _validate_scene_plan_payload(payload, durations, contract.story_plan_scene_roles),
        repair_prompt_builder=_build_scene_plan_repair_prompt,
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    allocation = allocate_dialogue_step(
        DialogueAllocationInput(
            raw_prompt=contract.raw_prompt,
            optimized_prompt=contract.optimized_prompt,
            dialogue_lines=contract.dialogue_lines,
            input_language=contract.input_language,
            dialogue_language=contract.dialogue_language,
            audio_language=contract.audio_language,
            creative_intent=contract.creative_intent,
            planning_notes=contract.planning_notes,
            overall_story_arc=contract.overall_story_arc,
            dialogue_strategy=contract.dialogue_strategy,
            project_guidance_context=build_project_guidance_context(
                step_name="dialogue_allocate",
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
            ),
            scenes=[
                DialogueAllocationSceneInput(
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
                    information_load=scene.information_load,
                    speech_expectation=scene.speech_expectation,
                    depends_on_scene=scene.depends_on_scene,
                )
                for scene in output.scenes
            ],
        ),
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
    )
    allocation_map = {item.scene_id: item for item in allocation.allocations}
    for scene in output.scenes:
        allocated = allocation_map[scene.scene_id]
        scene.spoken_text = allocated.spoken_text
        scene.speech_mode = allocated.speech_mode
        scene.delivery_notes = allocated.delivery_notes
        scene.provider_metadata = dict(scene.provider_metadata) | {
            "dialogue_allocate": allocation.provider_metadata,
        }
    return output


def plan_scenes_step(
    contract: ScenePlanningInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> ScenePlanningOutput:
    return build_scene_plan(
        contract,
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
    )
def _validate_scene_plan_payload(
    payload: dict[str, Any],
    durations: list[int],
    story_plan_scene_roles: list[StoryPlanSceneRole],
) -> ScenePlanningOutput:
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Scene planning output must contain a scenes list")
    if len(raw_scenes) != len(durations):
        raise ValueError("Scene planning output returned the wrong number of scenes")

    role_map = {role.scene_id: role for role in story_plan_scene_roles}
    scenes: list[Scene] = []
    for index, raw_scene in enumerate(raw_scenes, start=1):
        if not isinstance(raw_scene, dict):
            raise ValueError("Each planned scene must be a JSON object")
        title = _require_string(raw_scene, "title")
        narrative = _require_string(raw_scene, "narrative")
        visual_goal = _require_string(raw_scene, "visual_goal")
        continuity_notes = _require_string(raw_scene, "continuity_notes")
        scene_id = f"scene-{index:02d}"
        role = role_map.get(scene_id)
        scenes.append(
            Scene(
                scene_id=scene_id,
                index=index,
                title=title,
                duration_seconds=durations[index - 1],
                narrative=narrative,
                story_role=role.role_label if role else "",
                story_purpose=role.narrative_purpose if role else "",
                story_advance_goal=role.story_advance_goal if role else "",
                pacing_intent=role.pacing_intent if role else "",
                information_load=role.information_load if role else "",
                speech_expectation=role.speech_expectation if role else "",
                prompt="",
                visual_goal=visual_goal,
                spoken_text="",
                speech_mode="none",
                delivery_notes="",
                continuity_notes=continuity_notes,
                depends_on_scene=f"scene-{index - 1:02d}" if index > 1 else None,
            )
        )
    return ScenePlanningOutput(
        scenes=scenes,
        planning_notes=str(payload.get("planning_notes", "")).strip(),
    )


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"Scene planning output missing {key}")
    return value


def _build_scene_plan_repair_prompt(
    input_payload: dict[str, Any],
    parsed_payload: dict[str, Any],
    error: Exception,
) -> str | None:
    if not is_scene_list_contract_violation(error):
        return None
    return build_scene_list_contract_repair_prompt(
        collection_key="scenes",
        expected_scene_ids=list(input_payload.get("expected_scene_ids", [])),
        parsed_payload=parsed_payload,
        error=error,
        require_scene_id_field=False,
        extra_rules=(
            "Return exactly one scene-plan object per planned scene.",
            "Do not split one planned scene into multiple sub-shot objects.",
        ),
    )
