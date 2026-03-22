from __future__ import annotations

from video_workflow_service.infrastructure.config import ServiceSettings


_STEP_PROVIDER_ATTRS = {
    "character_anchor": "llm_character_anchor_provider",
    "scene_character_cast": "llm_scene_character_cast_provider",
    "prompt_optimize": "llm_prompt_optimize_provider",
    "story_plan": "llm_story_plan_provider",
    "scene_plan": "llm_scene_plan_provider",
    "dialogue_allocate": "llm_dialogue_allocate_provider",
    "first_frame_analyze": "llm_first_frame_analyze_provider",
    "scene_prompt_render": "llm_scene_prompt_render_provider",
    "dialogue_split": "llm_dialogue_split_provider",
}


def resolve_llm_provider_name(settings: ServiceSettings, step_name: str) -> str:
    override_attr = _STEP_PROVIDER_ATTRS.get(step_name)
    if override_attr:
        override = getattr(settings, override_attr, None)
        if isinstance(override, str) and override.strip():
            return override.strip().lower()
    return settings.llm_provider
