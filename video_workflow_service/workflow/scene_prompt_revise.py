from __future__ import annotations

from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.contracts import (
    ScenePromptRevisionInput,
    ScenePromptRevisionOutput,
)
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    SCENE_PROMPT_REVISE_TEMPLATE_VERSION,
    build_scene_prompt_revise_messages,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


def revise_scene_prompt_step(
    contract: ScenePromptRevisionInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> ScenePromptRevisionOutput:
    input_payload = {
        "scene_id": contract.scene_id,
        "scene_index": contract.scene_index,
        "scene_count": contract.scene_count,
        "raw_prompt": contract.raw_prompt,
        "current_prompt": contract.current_prompt,
        "current_rendered_prompt": contract.current_rendered_prompt,
        "title": contract.title,
        "narrative": contract.narrative,
        "visual_goal": contract.visual_goal,
        "spoken_text": contract.spoken_text,
        "speech_mode": contract.speech_mode,
        "delivery_notes": contract.delivery_notes,
        "continuity_notes": contract.continuity_notes,
        "first_frame_source": contract.first_frame_source,
        "first_frame_prompt": contract.first_frame_prompt,
        "first_frame_analysis": contract.first_frame_analysis,
        "input_language": contract.input_language,
        "dialogue_language": contract.dialogue_language,
        "audio_language": contract.audio_language,
        "feedback": contract.feedback,
        "requested_scope": contract.requested_scope,
        "project_guidance": dict(contract.project_guidance_context),
        "scene_guidance": dict(contract.scene_guidance_context),
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="scene_prompt_revise",
        template_version=SCENE_PROMPT_REVISE_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=build_scene_prompt_revise_messages,
        validator=lambda payload: _validate_scene_prompt_revision_payload(
            payload,
            requested_scope=contract.requested_scope,
        ),
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    return output


def _validate_scene_prompt_revision_payload(
    payload: dict[str, Any],
    *,
    requested_scope: str,
) -> ScenePromptRevisionOutput:
    outcome = _require_string(payload, "outcome")
    if outcome not in {"revised", "requires_start_state_edit"}:
        raise ValueError("Scene prompt revision output has invalid outcome")
    revised_prompt = str(payload.get("revised_prompt", "")).strip()
    revised_first_frame_prompt = str(payload.get("revised_first_frame_prompt", "")).strip()
    change_summary = str(payload.get("change_summary", "")).strip()
    rejection_reason = str(payload.get("rejection_reason", "")).strip()
    if outcome == "revised":
        if requested_scope == "prompt_only" and not revised_prompt:
            raise ValueError("Scene prompt revision output missing revised_prompt for prompt_only scope")
        if requested_scope == "opening_still_and_prompt" and not revised_first_frame_prompt:
            raise ValueError(
                "Scene prompt revision output missing revised_first_frame_prompt for opening_still_and_prompt scope"
            )
    if outcome == "requires_start_state_edit" and not rejection_reason:
        raise ValueError("Scene prompt revision output missing rejection_reason")
    return ScenePromptRevisionOutput(
        outcome=outcome,
        revised_prompt=revised_prompt,
        revised_first_frame_prompt=revised_first_frame_prompt,
        change_summary=change_summary,
        rejection_reason=rejection_reason,
    )


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"Scene prompt revision output missing {key}")
    return value
