from __future__ import annotations

import re
from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.contracts import (
    ScenePromptRenderInput,
    ScenePromptRenderOutput,
)
from video_workflow_service.workflow.context_assembler import (
    build_project_guidance_context,
    build_scene_guidance_context,
)
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    SCENE_PROMPT_RENDER_TEMPLATE_VERSION,
    build_scene_prompt_render_messages,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger

_CLAUSE_SPLIT_PATTERN = re.compile(r"(?<=[.;])\s+|,\s+(?=[A-Za-z])")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_AUDIENCE_META_PATTERN = re.compile(
    r"\b(viewers?|audience|engagement|retention|comment|comments|virality|viral|algorithm)\b",
    re.IGNORECASE,
)
_PLANNING_META_PATTERN = re.compile(
    r"\b(subvert(?:s|ed|ing|ion)?|expectation(?:s)?|hook(?:ed)?|ordinary moment|mundane scene|unanswered questions)\b",
    re.IGNORECASE,
)
_RENDER_META_PATTERN = re.compile(
    r"\b(scene intent|visual direction|continuity constraints|full continuity from prior scene|preserve all (?:details|original)|period-accurate|no anachronistic modern elements)\b",
    re.IGNORECASE,
)
_TIMECODE_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\b")
_DURATION_META_PATTERN = re.compile(
    r"\b(duration|runtime|approximate runtime|matches required)\b",
    re.IGNORECASE,
)
_CONTINUITY_SPLIT_PATTERN = re.compile(r"(?<=[.;])\s+")


def render_scene_prompt_step(
    contract: ScenePromptRenderInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> ScenePromptRenderOutput:
    project_guidance = dict(contract.project_guidance_context) or build_project_guidance_context(
        step_name="scene_prompt_render",
        target_duration_seconds=contract.duration_seconds,
        scene_count=contract.scene_count,
        input_language=contract.input_language,
        dialogue_language=contract.dialogue_language,
        audio_language=contract.audio_language,
    )
    scene_guidance = dict(contract.scene_guidance_context) or build_scene_guidance_context(
        step_name="scene_prompt_render",
        working_prompt=contract.working_prompt,
        spoken_text=contract.spoken_text,
        speech_mode=contract.speech_mode,
        delivery_notes=contract.delivery_notes,
        dialogue_language=contract.dialogue_language,
        audio_language=contract.audio_language,
        first_frame_source=contract.first_frame_source,
        first_frame_analysis=contract.first_frame_analysis,
        continuity_notes=contract.continuity_notes,
        first_frame_prompt=contract.first_frame_prompt,
    )
    input_payload = {
        "scene_id": contract.scene_id,
        "scene_index": contract.scene_index,
        "scene_count": contract.scene_count,
        "title": contract.title,
        "working_prompt": contract.working_prompt,
        "narrative": contract.narrative,
        "visual_goal": contract.visual_goal,
        "spoken_text": contract.spoken_text,
        "speech_mode": contract.speech_mode,
        "delivery_notes": contract.delivery_notes,
        "dialogue_language": contract.dialogue_language,
        "audio_language": contract.audio_language,
        "continuity_notes": contract.continuity_notes,
        "duration_seconds": contract.duration_seconds,
        "input_language": contract.input_language,
        "first_frame_source": contract.first_frame_source,
        "first_frame_prompt": contract.first_frame_prompt,
        "first_frame_analysis": contract.first_frame_analysis,
        "aspect_ratio": contract.aspect_ratio,
        "project_guidance": project_guidance,
        "scene_guidance": scene_guidance,
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="scene_prompt_render",
        template_version=SCENE_PROMPT_RENDER_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=build_scene_prompt_render_messages,
        validator=_validate_scene_prompt_render_payload,
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    return output


def render_scene_generation_prompt(
    *,
    title: str,
    working_prompt: str = "",
    narrative: str,
    visual_goal: str,
    spoken_text: str,
    speech_mode: str,
    delivery_notes: str,
    continuity_notes: str,
    input_language: str = "",
    dialogue_language: str = "",
    audio_language: str = "",
    first_frame_source: str = "auto_generate",
    first_frame_prompt: str = "",
    first_frame_analysis: dict[str, Any] | None = None,
) -> str:
    title_text = _normalize_text(title)
    working_prompt_text = _clean_scene_text(working_prompt, drop_duration_meta=False)
    narrative_text = _clean_scene_text(narrative, drop_duration_meta=False)
    visual_text = _clean_scene_text(visual_goal, drop_duration_meta=False)
    delivery_text = _clean_scene_text(delivery_notes, drop_duration_meta=False)
    continuity_text = _naturalize_continuity_text(continuity_notes)
    first_frame_prompt_text = _normalize_text(first_frame_prompt)
    first_frame_analysis_dict = dict(first_frame_analysis or {})

    parts: list[str] = []
    opening_truth = build_first_frame_grounding_text(
        first_frame_source,
        first_frame_analysis_dict,
        first_frame_prompt_text,
    )
    if opening_truth:
        parts.append(opening_truth)
    elif title_text:
        parts.append(f"{title_text}.")
    main_action = _choose_main_scene_text(working_prompt_text, narrative_text, title_text)
    if main_action:
        parts.append(main_action)
    if visual_text:
        parts.append(visual_text)
    if continuity_text:
        parts.append(continuity_text)

    spoken_text = _normalize_text(spoken_text)
    output_language = _render_prompt_language(
        input_language=input_language,
        dialogue_language=dialogue_language,
        audio_language=audio_language,
    )
    spoken_language_text = _spoken_language_phrase(
        spoken_language=dialogue_language or audio_language,
        output_language=output_language,
    )
    if speech_mode == "none" or not spoken_text:
        parts.append("本场不出现口播台词。" if output_language == "zh" else "No spoken dialogue in this scene.")
    elif speech_mode == "once":
        if spoken_language_text:
            if output_language == "zh":
                parts.append(f'用{spoken_language_text}完整说出这句台词一次：“{spoken_text}”。')
            else:
                parts.append(f'She delivers the line once in {spoken_language_text}: "{spoken_text}".')
        else:
            parts.append(f'完整说出这句台词一次：“{spoken_text}”。' if output_language == "zh" else f'She speaks: "{spoken_text}" once.')
    else:
        if spoken_language_text:
            if output_language == "zh":
                parts.append(f'仅用{spoken_language_text}说出这一段台词：“{spoken_text}”。')
            else:
                parts.append(f'She delivers only this segment in {spoken_language_text}: "{spoken_text}".')
        else:
            parts.append(f'只说出这一段台词：“{spoken_text}”。' if output_language == "zh" else f'She speaks only this segment: "{spoken_text}".')
    if delivery_text:
        parts.append(delivery_text)
    return " ".join(part for part in parts if part)


def build_first_frame_grounding_text(
    first_frame_source: str,
    first_frame_analysis: dict[str, Any],
    first_frame_prompt: str,
) -> str:
    if first_frame_source not in {"upload", "continuity", "auto_generate"}:
        return ""
    truth_parts: list[str] = []
    for key in (
        "framing",
        "subject_pose",
        "hand_prop_state",
        "setting",
        "lighting",
    ):
        value = _compress_grounding_fact(first_frame_analysis.get(key, ""))
        if value:
            truth_parts.append(value.rstrip("."))
    if truth_parts:
        return ". ".join(_dedupe_adjacent(truth_parts[:3])) + "."
    if first_frame_source == "auto_generate" and first_frame_prompt:
        return f"{first_frame_prompt.rstrip('.')}."
    if first_frame_source in {"upload", "continuity"}:
        return ""
    return ""


def _clean_scene_text(text: str, *, drop_duration_meta: bool) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    clauses = [
        _normalize_text(fragment)
        for fragment in _CLAUSE_SPLIT_PATTERN.split(normalized)
        if _normalize_text(fragment)
    ]
    cleaned: list[str] = []
    for clause in clauses:
        if _is_meta_clause(clause, drop_duration_meta=drop_duration_meta):
            continue
        cleaned.append(clause.rstrip("."))
    if not cleaned:
        return ""
    return ". ".join(_dedupe_adjacent(cleaned)).strip()


def _is_meta_clause(clause: str, *, drop_duration_meta: bool) -> bool:
    if _AUDIENCE_META_PATTERN.search(clause):
        return True
    if _PLANNING_META_PATTERN.search(clause):
        return True
    if _RENDER_META_PATTERN.search(clause):
        return True
    if drop_duration_meta and (_TIMECODE_PATTERN.search(clause) or _DURATION_META_PATTERN.search(clause)):
        return True
    return False


def _choose_main_scene_text(working_prompt_text: str, narrative_text: str, title_text: str) -> str:
    if working_prompt_text:
        return working_prompt_text
    if narrative_text:
        return narrative_text
    if title_text:
        return f"{title_text}."
    return ""


def _naturalize_continuity_text(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    clauses = [
        _normalize_text(fragment)
        for fragment in _CONTINUITY_SPLIT_PATTERN.split(normalized)
        if _normalize_text(fragment)
    ]
    cleaned: list[str] = []
    for clause in clauses:
        rewritten = _rewrite_continuity_clause(clause)
        if rewritten and not _is_meta_clause(rewritten, drop_duration_meta=True):
            cleaned.append(rewritten.rstrip("."))
    return ". ".join(_dedupe_adjacent(cleaned[:2])).strip()


def _rewrite_continuity_clause(clause: str) -> str:
    rewritten = re.sub(
        r"^(?:full continuity from prior scene|continuity constraints|preserve all confirmed first-frame details|preserve all original details|preserve original details)\s*:?\s*",
        "",
        clause,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(
        r"^maintain\s+(.+?)\s+continuity$",
        r"Keep \1 consistent",
        rewritten,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(
        r"^retain\s+(.+?)\s+continuity$",
        r"Keep \1 consistent",
        rewritten,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(r"\bno abrupt cut\b", "continuous carry-over from the prior shot", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\bsame\s+", "", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\bperiod-accurate\b", "", rewritten, flags=re.IGNORECASE)
    rewritten = re.sub(r"\s*,\s*,", ", ", rewritten)
    rewritten = _normalize_text(rewritten.strip(" .,:;"))
    if "," in rewritten and not re.match(r"^(keep|maintain|retain|continuous)\b", rewritten, re.IGNORECASE):
        rewritten = f"Keep {rewritten}"
    return _normalize_text(rewritten)


def _compress_grounding_fact(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"\bis already established\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bis already\b", "is", text, flags=re.IGNORECASE)
    text = re.sub(r"\balready\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bfully visible on screen\b", "already on screen", text, flags=re.IGNORECASE)
    text = re.sub(r"\bwith both hands at (?:her|his|their) waist\b", "in both hands at waist height", text, flags=re.IGNORECASE)
    return _normalize_text(text.strip(" .,:;"))


def _dedupe_adjacent(parts: list[str]) -> list[str]:
    deduped: list[str] = []
    previous = ""
    for part in parts:
        key = part.casefold()
        if key == previous:
            continue
        deduped.append(part)
        previous = key
    return deduped


def _normalize_text(text: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", str(text or "")).strip()


def _render_prompt_language(*, input_language: str, dialogue_language: str, audio_language: str) -> str:
    for value in (input_language, dialogue_language, audio_language):
        normalized = _normalize_text(value).lower()
        if normalized in {"zh", "en"}:
            return normalized
    return ""


def _spoken_language_phrase(*, spoken_language: str, output_language: str) -> str:
    normalized = _normalize_text(spoken_language).lower()
    if normalized == "zh":
        return "自然中文" if output_language == "zh" else "natural Mandarin Chinese"
    if normalized == "en":
        return "自然英文" if output_language == "zh" else "natural English"
    return ""


def _validate_scene_prompt_render_payload(payload: dict[str, Any]) -> ScenePromptRenderOutput:
    rendered_prompt = _normalize_text(payload.get("rendered_prompt", ""))
    if not rendered_prompt:
        raise ValueError("Scene prompt render output missing rendered_prompt")
    return ScenePromptRenderOutput(rendered_prompt=rendered_prompt)
