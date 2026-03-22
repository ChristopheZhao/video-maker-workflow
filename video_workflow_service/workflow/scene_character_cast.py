from __future__ import annotations

from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.context_assembler import build_project_guidance_context
from video_workflow_service.workflow.contracts import (
    SceneCharacterCastInput,
    SceneCharacterCastOutput,
    SceneCharacterParticipation,
)
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    SCENE_CHARACTER_CAST_TEMPLATE_VERSION,
    build_scene_character_cast_messages,
)
from video_workflow_service.workflow.scene_list_contracts import (
    build_scene_list_contract_repair_prompt,
    is_scene_list_contract_violation,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


def scene_character_cast_step(
    contract: SceneCharacterCastInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> SceneCharacterCastOutput:
    project_guidance = dict(contract.project_guidance_context) or build_project_guidance_context(
        step_name="scene_character_cast",
        target_duration_seconds=sum(max(0, scene.duration_seconds) for scene in contract.scenes),
        scene_count=len(contract.scenes),
        input_language=contract.input_language,
        dialogue_language=contract.dialogue_language,
        audio_language=contract.audio_language,
        character_cards=contract.character_cards,
    )
    input_payload = {
        "raw_prompt": contract.raw_prompt,
        "optimized_prompt": contract.optimized_prompt,
        "input_language": contract.input_language,
        "dialogue_language": contract.dialogue_language,
        "audio_language": contract.audio_language,
        "overall_story_arc": contract.overall_story_arc,
        "character_cards": list(contract.character_cards),
        "expected_scene_count": len(contract.scenes),
        "expected_scene_ids": [scene.scene_id for scene in contract.scenes],
        "project_guidance": project_guidance,
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "scene_index": scene.scene_index,
                "title": scene.title,
                "narrative": scene.narrative,
                "visual_goal": scene.visual_goal,
                "continuity_notes": scene.continuity_notes,
                "duration_seconds": scene.duration_seconds,
                "story_role": scene.story_role,
                "story_purpose": scene.story_purpose,
                "story_advance_goal": scene.story_advance_goal,
                "pacing_intent": scene.pacing_intent,
            }
            for scene in contract.scenes
        ],
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="scene_character_cast",
        template_version=SCENE_CHARACTER_CAST_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=build_scene_character_cast_messages,
        validator=lambda payload: _validate_scene_character_cast_payload(
            payload,
            contract.scenes,
            contract.character_cards,
        ),
        repair_prompt_builder=_build_scene_character_cast_repair_prompt,
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    return output


def _validate_scene_character_cast_payload(
    payload: dict[str, Any],
    scenes: list[Any],
    character_cards: list[dict[str, Any]],
) -> SceneCharacterCastOutput:
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list):
        raise ValueError("Scene character cast output must contain a scenes list")
    if len(raw_scenes) != len(scenes):
        raise ValueError("Scene character cast output returned the wrong number of scenes")

    expected_scene_ids = [scene.scene_id for scene in scenes]
    anchored_ids = {
        str(item.get("character_id", "")).strip()
        for item in character_cards
        if isinstance(item, dict) and str(item.get("character_id", "")).strip()
    }
    participations: list[SceneCharacterParticipation] = []
    seen_scene_ids: list[str] = []
    for raw_item in raw_scenes:
        if not isinstance(raw_item, dict):
            raise ValueError("Each scene character cast item must be a JSON object")
        scene_id = _require_string(raw_item, "scene_id")
        if scene_id in seen_scene_ids:
            raise ValueError(f"Duplicate scene character cast for scene_id={scene_id}")
        seen_scene_ids.append(scene_id)
        raw_ids = raw_item.get("participating_character_ids", [])
        if raw_ids in ("", None):
            raw_ids = []
        if not isinstance(raw_ids, list):
            raise ValueError("participating_character_ids must be a list")
        participating_character_ids: list[str] = []
        for raw_id in raw_ids:
            character_id = str(raw_id).strip()
            if not character_id:
                continue
            if character_id not in anchored_ids:
                raise ValueError(f"Unknown character_id in scene cast output: {character_id}")
            if character_id not in participating_character_ids:
                participating_character_ids.append(character_id)
        raw_primary = raw_item.get("primary_character_id")
        primary_character_id = str(raw_primary).strip() if raw_primary not in (None, "") else None
        if primary_character_id and primary_character_id not in participating_character_ids:
            raise ValueError("primary_character_id must be included in participating_character_ids")
        participations.append(
            SceneCharacterParticipation(
                scene_id=scene_id,
                participating_character_ids=participating_character_ids,
                primary_character_id=primary_character_id,
                character_presence_notes=str(raw_item.get("character_presence_notes", "")).strip(),
            )
        )
    if seen_scene_ids != expected_scene_ids:
        raise ValueError("Scene character cast output must preserve planned scene order")
    return SceneCharacterCastOutput(scenes=participations)


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"Scene character cast output missing {key}")
    return value


def _build_scene_character_cast_repair_prompt(
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
        extra_rules=(
            "Return exactly one participation object per input scene.",
            "All participating characters for the same scene must stay inside one scene object.",
        ),
    )
