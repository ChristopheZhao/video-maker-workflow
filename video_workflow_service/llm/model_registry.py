from __future__ import annotations

from video_workflow_service.infrastructure.config import ServiceSettings


_STEP_MODEL_ATTRS = {
    "character_anchor": "llm_character_anchor_model",
    "scene_character_cast": "llm_scene_character_cast_model",
    "prompt_optimize": "llm_prompt_optimize_model",
    "story_plan": "llm_story_plan_model",
    "scene_plan": "llm_scene_plan_model",
    "dialogue_allocate": "llm_dialogue_allocate_model",
    "first_frame_analyze": "llm_first_frame_analyze_model",
    "scene_prompt_render": "llm_scene_prompt_render_model",
    "dialogue_split": "llm_dialogue_split_model",
}


def resolve_llm_model(
    settings: ServiceSettings,
    step_name: str,
    provider_name: str | None = None,
) -> str:
    override_attr = _STEP_MODEL_ATTRS.get(step_name)
    if override_attr:
        override = getattr(settings, override_attr, None)
        if isinstance(override, str) and override.strip():
            return override.strip()
    resolved_provider = (provider_name or settings.llm_provider).strip().lower()
    if resolved_provider == "deepseek":
        return settings.deepseek_default_model
    return settings.llm_default_model
