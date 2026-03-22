from __future__ import annotations

import re
from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.contracts import (
    PromptOptimizationInput,
    PromptOptimizationOutput,
)
from video_workflow_service.workflow.context_assembler import build_project_guidance_context
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    PROMPT_OPTIMIZE_TEMPLATE_VERSION,
    build_prompt_optimize_messages,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


def optimize_prompt_step(
    contract: PromptOptimizationInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> PromptOptimizationOutput:
    project_guidance = dict(contract.project_guidance_context) or build_project_guidance_context(
        step_name="prompt_optimize",
        target_duration_seconds=contract.target_duration_seconds,
        scene_count=contract.scene_count,
        input_language=contract.input_language,
        dialogue_language=contract.dialogue_language,
        audio_language=contract.audio_language,
        scene1_first_frame_source=contract.scene1_first_frame_source,
        scene1_first_frame_prompt=contract.scene1_first_frame_prompt,
        scene1_first_frame_analysis=contract.scene1_first_frame_analysis,
    )
    input_payload = {
        "raw_prompt": contract.raw_prompt,
        "target_duration_seconds": contract.target_duration_seconds,
        "scene_count": contract.scene_count,
        "input_language": contract.input_language,
        "dialogue_language": contract.dialogue_language,
        "audio_language": contract.audio_language,
        "scene1_first_frame_source": contract.scene1_first_frame_source,
        "scene1_first_frame_prompt": contract.scene1_first_frame_prompt,
        "scene1_first_frame_analysis": contract.scene1_first_frame_analysis,
        "project_guidance": project_guidance,
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="prompt_optimize",
        template_version=PROMPT_OPTIMIZE_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=build_prompt_optimize_messages,
        validator=_validate_prompt_optimization_payload,
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    return output


def optimize_prompt_text(prompt: str) -> str:
    normalized = re.sub(r"\s+", " ", prompt.strip())
    return (
        f"{normalized}. Preserve narrative continuity, stage visual escalation, "
        f"and plan dialogue delivery scene by scene."
    )


def _validate_prompt_optimization_payload(payload: dict[str, Any]) -> PromptOptimizationOutput:
    optimized_prompt = _require_string(payload, "optimized_prompt")
    creative_intent = _require_string(payload, "creative_intent")
    planning_notes = _require_string(payload, "planning_notes")
    style_guardrails = _require_string_list(payload.get("style_guardrails"))
    dialogue_lines = _require_string_list(payload.get("dialogue_lines"))
    return PromptOptimizationOutput(
        optimized_prompt=optimized_prompt,
        creative_intent=creative_intent,
        style_guardrails=style_guardrails,
        dialogue_lines=dialogue_lines,
        planning_notes=planning_notes,
    )


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"Prompt optimization output missing {key}")
    return value


def _require_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a list of strings in prompt optimization output")
    return [str(item).strip() for item in value if str(item).strip()]
