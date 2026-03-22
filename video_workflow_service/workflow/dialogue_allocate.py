from __future__ import annotations

from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.contracts import (
    DialogueAllocation,
    DialogueAllocationInput,
    DialogueAllocationOutput,
)
from video_workflow_service.workflow.context_assembler import build_project_guidance_context
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    DIALOGUE_ALLOCATE_TEMPLATE_VERSION,
    build_dialogue_allocate_messages,
)
from video_workflow_service.workflow.scene_list_contracts import (
    build_scene_list_contract_repair_prompt,
    is_scene_list_contract_violation,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


def allocate_dialogue_step(
    contract: DialogueAllocationInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> DialogueAllocationOutput:
    project_guidance = dict(contract.project_guidance_context) or build_project_guidance_context(
        step_name="dialogue_allocate",
        target_duration_seconds=sum(max(0, scene.duration_seconds) for scene in contract.scenes),
        scene_count=len(contract.scenes),
        input_language=contract.input_language,
        dialogue_language=contract.dialogue_language,
        audio_language=contract.audio_language,
        creative_intent=contract.creative_intent,
        planning_notes=contract.planning_notes,
        dialogue_lines=contract.dialogue_lines,
    )
    input_payload = {
        "input_language": contract.input_language,
        "dialogue_lines": contract.dialogue_lines,
        "dialogue_language": contract.dialogue_language,
        "audio_language": contract.audio_language,
        "creative_intent": contract.creative_intent,
        "overall_story_arc": contract.overall_story_arc,
        "dialogue_strategy": contract.dialogue_strategy,
        "expected_scene_count": len(contract.scenes),
        "expected_scene_ids": [scene.scene_id for scene in contract.scenes],
        "project_guidance": project_guidance,
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "scene_index": scene.scene_index,
                "title": scene.title,
                "narrative": scene.narrative,
                "duration_seconds": scene.duration_seconds,
                "story_role": scene.story_role,
                "story_purpose": scene.story_purpose,
                "story_advance_goal": scene.story_advance_goal,
                "pacing_intent": scene.pacing_intent,
                "information_load": scene.information_load,
                "speech_expectation": scene.speech_expectation,
                "depends_on_scene": scene.depends_on_scene,
            }
            for scene in contract.scenes
        ],
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="dialogue_allocate",
        template_version=DIALOGUE_ALLOCATE_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=build_dialogue_allocate_messages,
        validator=lambda payload: _validate_dialogue_allocation_payload(payload, contract.scenes),
        repair_prompt_builder=_build_dialogue_allocate_repair_prompt,
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    return output


def _validate_dialogue_allocation_payload(
    payload: dict[str, Any],
    scenes: list[Any],
) -> DialogueAllocationOutput:
    raw_allocations = payload.get("allocations")
    if not isinstance(raw_allocations, list):
        raise ValueError("Dialogue allocation output must contain an allocations list")
    if len(raw_allocations) != len(scenes):
        raise ValueError("Dialogue allocation output returned the wrong number of scene allocations")

    expected_scene_ids = [scene.scene_id for scene in scenes]
    seen_scene_ids: list[str] = []
    previous_spoken_text = ""
    allocations: list[DialogueAllocation] = []
    for raw_item in raw_allocations:
        if not isinstance(raw_item, dict):
            raise ValueError("Each dialogue allocation item must be a JSON object")
        scene_id = _require_string(raw_item, "scene_id")
        spoken_text = str(raw_item.get("spoken_text", "")).strip()
        speech_mode = str(raw_item.get("speech_mode", "none")).strip().lower() or "none"
        delivery_notes = str(raw_item.get("delivery_notes", "")).strip()
        if speech_mode not in {"none", "once", "split"}:
            raise ValueError(f"Unsupported speech_mode: {speech_mode}")
        if speech_mode == "none":
            spoken_text = ""
        if scene_id in seen_scene_ids:
            raise ValueError(f"Duplicate dialogue allocation for scene_id={scene_id}")
        seen_scene_ids.append(scene_id)
        if previous_spoken_text and spoken_text and previous_spoken_text == spoken_text:
            raise ValueError("Adjacent scenes must not repeat the same full spoken_text")
        previous_spoken_text = spoken_text
        allocations.append(
            DialogueAllocation(
                scene_id=scene_id,
                spoken_text=spoken_text,
                speech_mode=speech_mode,
                delivery_notes=delivery_notes,
            )
        )
    if seen_scene_ids != expected_scene_ids:
        raise ValueError("Dialogue allocations must align with the planned scene order")
    return DialogueAllocationOutput(
        allocations=allocations,
        planning_notes=str(payload.get("planning_notes", "")).strip(),
    )


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"Dialogue allocation output missing {key}")
    return value


def _build_dialogue_allocate_repair_prompt(
    input_payload: dict[str, Any],
    parsed_payload: dict[str, Any],
    error: Exception,
) -> str | None:
    if not is_scene_list_contract_violation(error):
        return None
    return build_scene_list_contract_repair_prompt(
        collection_key="allocations",
        expected_scene_ids=list(input_payload.get("expected_scene_ids", [])),
        parsed_payload=parsed_payload,
        error=error,
        extra_rules=(
            "Return exactly one allocation object per input scene.",
            "If one scene contains multiple short sounds or utterances, merge them into a single `spoken_text` string in playback order and explain timing in `delivery_notes`.",
            "Do not split one scene into multiple allocation objects.",
        ),
    )
