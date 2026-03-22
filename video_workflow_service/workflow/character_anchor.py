from __future__ import annotations

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.contracts import (
    CharacterAnchorCandidate,
    CharacterAnchorInput,
    CharacterAnchorOutput,
)
from video_workflow_service.workflow.context_assembler import build_project_guidance_context
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    CHARACTER_ANCHOR_TEMPLATE_VERSION,
    build_character_anchor_messages,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


def character_anchor_step(
    contract: CharacterAnchorInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> CharacterAnchorOutput:
    project_guidance = dict(contract.project_guidance_context) or build_project_guidance_context(
        step_name="character_anchor",
        target_duration_seconds=0,
        scene_count=0,
        input_language=contract.input_language,
        dialogue_language=contract.dialogue_language,
        audio_language=contract.audio_language,
        scene1_first_frame_source=contract.scene1_first_frame_source,
        scene1_first_frame_analysis=contract.scene1_first_frame_analysis,
    )
    input_payload = {
        "raw_prompt": contract.raw_prompt,
        "optimized_prompt": contract.optimized_prompt,
        "input_language": contract.input_language,
        "dialogue_language": contract.dialogue_language,
        "audio_language": contract.audio_language,
        "scene1_first_frame_source": contract.scene1_first_frame_source,
        "scene1_first_frame_image_present": bool(contract.scene1_first_frame_image),
        "scene1_first_frame_analysis": contract.scene1_first_frame_analysis,
        "project_guidance": project_guidance,
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="character_anchor",
        template_version=CHARACTER_ANCHOR_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=build_character_anchor_messages,
        validator=_validate_character_anchor_payload,
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    return output


def _validate_character_anchor_payload(payload: dict[str, object]) -> CharacterAnchorOutput:
    raw_characters = payload.get("characters", [])
    if raw_characters in ("", None):
        raw_characters = []
    if not isinstance(raw_characters, list):
        raise ValueError("Character anchor output must contain a characters list")
    candidates: list[CharacterAnchorCandidate] = []
    for index, item in enumerate(raw_characters[:3], start=1):
        if not isinstance(item, dict):
            continue
        display_name = str(item.get("display_name", "")).strip()
        visual_description = str(item.get("visual_description", "")).strip()
        if not display_name and not visual_description:
            continue
        character_id = str(item.get("character_id", "")).strip() or f"char-{index:02d}"
        candidates.append(
            CharacterAnchorCandidate(
                character_id=character_id,
                display_name=display_name or f"Character {index}",
                story_role=str(item.get("story_role", "")).strip(),
                visual_description=visual_description,
                reference_prompt=str(item.get("reference_prompt", "")).strip(),
            )
        )
    return CharacterAnchorOutput(characters=candidates)
