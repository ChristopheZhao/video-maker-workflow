from __future__ import annotations

from typing import Any


_PROJECT_GUIDANCE_FIELDS_BY_NODE: dict[str, tuple[str, ...]] = {
    "character_anchor": (
        "input_language",
        "dialogue_language",
        "audio_language",
        "language_confidence",
        "character_anchor_summary",
        "opening_truth_summary",
        "scene1_first_frame_source",
    ),
    "scene_character_cast": (
        "input_language",
        "dialogue_language",
        "audio_language",
        "language_confidence",
        "character_anchor_summary",
    ),
    "prompt_optimize": (
        "target_duration_seconds",
        "scene_count",
        "input_language",
        "dialogue_language",
        "audio_language",
        "language_confidence",
        "opening_truth_summary",
        "scene1_first_frame_source",
    ),
    "story_plan": (
        "target_duration_seconds",
        "scene_count",
        "input_language",
        "dialogue_language",
        "audio_language",
        "language_confidence",
        "creative_intent",
        "style_guardrails",
        "planning_notes",
        "opening_truth_summary",
        "global_dialogue_intent",
        "scene1_first_frame_source",
    ),
    "scene_plan": (
        "target_duration_seconds",
        "scene_count",
        "input_language",
        "dialogue_language",
        "audio_language",
        "creative_intent",
        "style_guardrails",
        "planning_notes",
        "opening_truth_summary",
        "global_dialogue_intent",
        "scene1_first_frame_source",
    ),
    "dialogue_allocate": (
        "input_language",
        "dialogue_language",
        "audio_language",
        "creative_intent",
        "planning_notes",
        "global_dialogue_intent",
    ),
    "scene_prompt_render": (
        "dialogue_language",
        "audio_language",
        "creative_intent",
        "style_guardrails",
    ),
}

_SCENE_GUIDANCE_FIELDS_BY_NODE: dict[str, tuple[str, ...]] = {
    "scene_prompt_render": (
        "working_prompt",
        "dialogue_language",
        "audio_language",
        "character_presence_summary",
        "first_frame_source",
        "first_frame_anchor_summary",
        "continuity_anchor_summary",
        "dialogue_guidance",
    ),
}


def shape_project_guidance_context(step_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = _PROJECT_GUIDANCE_FIELDS_BY_NODE.get(step_name, ())
    return {
        field: value
        for field in allowed_fields
        if (value := payload.get(field)) not in ("", None, [], {})
    }


def shape_scene_guidance_context(step_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = _SCENE_GUIDANCE_FIELDS_BY_NODE.get(step_name, ())
    return {
        field: value
        for field in allowed_fields
        if (value := payload.get(field)) not in ("", None, [], {})
    }
