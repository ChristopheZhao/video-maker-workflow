from __future__ import annotations

import re
from typing import Any, Iterable

from video_workflow_service.workflow.context_types import (
    ProjectGuidanceContext,
    SceneGuidanceContext,
)
from video_workflow_service.workflow.node_context_policy import (
    shape_project_guidance_context,
    shape_scene_guidance_context,
)

_WHITESPACE_PATTERN = re.compile(r"\s+")


def build_project_guidance_context(
    *,
    step_name: str,
    target_duration_seconds: int,
    scene_count: int,
    input_language: str = "",
    dialogue_language: str = "",
    audio_language: str = "",
    language_confidence: str = "",
    creative_intent: str = "",
    style_guardrails: Iterable[str] = (),
    planning_notes: str = "",
    dialogue_lines: Iterable[str] = (),
    character_cards: Iterable[Any] = (),
    scene1_first_frame_source: str = "",
    scene1_first_frame_prompt: str = "",
    scene1_first_frame_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    opening_truth_summary = summarize_first_frame_anchor(
        scene1_first_frame_analysis or {},
        first_frame_source=scene1_first_frame_source,
        first_frame_prompt=scene1_first_frame_prompt,
    )
    guidance = ProjectGuidanceContext(
        target_duration_seconds=max(0, int(target_duration_seconds)),
        scene_count=max(0, int(scene_count)),
        input_language=_normalize_text(input_language),
        dialogue_language=_normalize_text(dialogue_language),
        audio_language=_normalize_text(audio_language),
        language_confidence=_normalize_text(language_confidence),
        creative_intent=_normalize_text(creative_intent),
        style_guardrails=_normalize_list(style_guardrails),
        planning_notes=_normalize_text(planning_notes),
        opening_truth_summary=opening_truth_summary,
        global_dialogue_intent=summarize_dialogue_intent(dialogue_lines),
        character_anchor_summary=summarize_character_anchors(character_cards),
        scene1_first_frame_source=_normalize_text(scene1_first_frame_source),
    )
    return shape_project_guidance_context(step_name, guidance.to_dict())


def build_scene_guidance_context(
    *,
    step_name: str,
    working_prompt: str = "",
    spoken_text: str = "",
    speech_mode: str = "none",
    delivery_notes: str = "",
    dialogue_language: str = "",
    audio_language: str = "",
    character_cards: Iterable[Any] = (),
    participating_character_ids: Iterable[str] = (),
    primary_character_id: str | None = None,
    character_presence_notes: str = "",
    first_frame_source: str = "",
    first_frame_analysis: dict[str, Any] | None = None,
    continuity_notes: str = "",
    first_frame_prompt: str = "",
) -> dict[str, Any]:
    guidance = SceneGuidanceContext(
        working_prompt=_normalize_text(working_prompt),
        dialogue_language=_normalize_text(dialogue_language),
        audio_language=_normalize_text(audio_language),
        character_presence_summary=summarize_scene_character_presence(
            character_cards=character_cards,
            participating_character_ids=participating_character_ids,
            primary_character_id=primary_character_id,
            character_presence_notes=character_presence_notes,
        ),
        first_frame_source=_normalize_text(first_frame_source),
        first_frame_anchor_summary=summarize_first_frame_anchor(
            first_frame_analysis or {},
            first_frame_source=first_frame_source,
            first_frame_prompt=first_frame_prompt,
        ),
        continuity_anchor_summary=summarize_continuity_anchor(continuity_notes),
        dialogue_guidance=summarize_dialogue_guidance(
            spoken_text=spoken_text,
            speech_mode=speech_mode,
            delivery_notes=delivery_notes,
        ),
    )
    return shape_scene_guidance_context(step_name, guidance.to_dict())


def summarize_first_frame_anchor(
    first_frame_analysis: dict[str, Any],
    *,
    first_frame_source: str = "",
    first_frame_prompt: str = "",
) -> str:
    parts = _normalize_list(
        first_frame_analysis.get(key, "")
        for key in (
            "subject_presence",
            "subject_pose",
            "hand_prop_state",
            "framing",
            "setting",
            "lighting",
            "continuation_constraints",
        )
    )
    if parts:
        return ". ".join(_dedupe_adjacent(parts[:4]))
    if _normalize_text(first_frame_source) == "auto_generate":
        return _normalize_text(first_frame_prompt)
    return ""


def summarize_dialogue_intent(dialogue_lines: Iterable[str]) -> str:
    lines = _normalize_list(dialogue_lines)
    if not lines:
        return ""
    if len(lines) == 1:
        return f"Primary dialogue line: {lines[0]}"
    preview = " | ".join(lines[:2])
    if len(lines) > 2:
        preview += " | ..."
    return f"Primary dialogue lines: {preview}"


def summarize_dialogue_guidance(*, spoken_text: str, speech_mode: str, delivery_notes: str) -> str:
    normalized_mode = _normalize_text(speech_mode).lower() or "none"
    normalized_delivery = _normalize_text(delivery_notes)
    if normalized_mode == "none" or not _normalize_text(spoken_text):
        return "Silent scene. No spoken dialogue."
    if normalized_mode == "split":
        base = "Use only the allocated dialogue fragment for this scene."
    else:
        base = "Deliver the allocated line once in this scene."
    if normalized_delivery:
        return f"{base} {normalized_delivery}"
    return base


def summarize_character_anchors(character_cards: Iterable[Any]) -> str:
    summaries: list[str] = []
    for card in character_cards:
        display_name = _normalize_text(_field_value(card, "display_name"))
        story_role = _normalize_text(_field_value(card, "story_role"))
        visual_description = _normalize_text(_field_value(card, "visual_description"))
        approval_status = _normalize_text(_field_value(card, "approval_status"))
        if not display_name and not visual_description:
            continue
        summary = display_name or "Unnamed character"
        if story_role:
            summary = f"{summary} ({story_role})"
        if visual_description:
            summary = f"{summary}: {visual_description}"
        if approval_status and approval_status != "approved":
            summary = f"{summary} [{approval_status}]"
        summaries.append(summary)
    if not summaries:
        return ""
    return " | ".join(_dedupe_adjacent(summaries[:3]))


def summarize_scene_character_presence(
    *,
    character_cards: Iterable[Any],
    participating_character_ids: Iterable[str],
    primary_character_id: str | None,
    character_presence_notes: str,
) -> str:
    ids = {str(item).strip() for item in participating_character_ids if str(item).strip()}
    if not ids:
        return ""
    primary = _normalize_text(primary_character_id)
    selected: list[str] = []
    for card in character_cards:
        character_id = _normalize_text(_field_value(card, "character_id"))
        if character_id not in ids:
            continue
        display_name = _normalize_text(_field_value(card, "display_name")) or character_id
        story_role = _normalize_text(_field_value(card, "story_role"))
        label = display_name
        if primary and character_id == primary:
            label = f"{label} (primary)"
        elif story_role:
            label = f"{label} ({story_role})"
        selected.append(label)
    if not selected:
        return ""
    summary = "Scene characters: " + ", ".join(_dedupe_adjacent(selected))
    notes = _normalize_text(character_presence_notes)
    if notes:
        summary = f"{summary}. {notes}"
    return summary


def summarize_continuity_anchor(continuity_notes: str) -> str:
    normalized = _normalize_text(continuity_notes)
    if not normalized:
        return ""
    clauses = [fragment.strip(" .") for fragment in re.split(r"(?<=[.;])\s+", normalized) if fragment.strip()]
    return ". ".join(_dedupe_adjacent(clauses[:2]))


def _normalize_text(value: Any) -> str:
    return _WHITESPACE_PATTERN.sub(" ", str(value or "")).strip()


def _normalize_list(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if normalized:
            result.append(normalized.rstrip("."))
    return result


def _field_value(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)


def _dedupe_adjacent(values: list[str]) -> list[str]:
    deduped: list[str] = []
    previous = ""
    for value in values:
        key = value.casefold()
        if key == previous:
            continue
        deduped.append(value)
        previous = key
    return deduped
