from __future__ import annotations

from dataclasses import asdict
import re

from video_workflow_service.workflow.contracts import LanguageDetectInput, LanguageDetectOutput
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]+")
_QUOTED_SEGMENT_PATTERN = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{2,})[\"“”'‘’]")


def detect_language_step(
    contract: LanguageDetectInput,
    *,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> LanguageDetectOutput:
    trace_logger.append(
        project_id,
        event_type="language_detect_requested",
        step="language_detect",
        status="requested",
        details={"raw_prompt": contract.raw_prompt},
    )
    output = _detect_languages(contract.raw_prompt)
    trace_logger.append(
        project_id,
        event_type="language_detect_completed",
        step="language_detect",
        status="completed",
        details=asdict(output),
    )
    return output


def _detect_languages(raw_prompt: str) -> LanguageDetectOutput:
    normalized_prompt = str(raw_prompt or "").strip()
    input_language, input_mixed = _classify_language(normalized_prompt)
    dialogue_text = _extract_dialogue_text(normalized_prompt)
    dialogue_language, dialogue_mixed = _classify_language(dialogue_text)

    if not dialogue_language:
        dialogue_language = input_language or "en"
    audio_language = dialogue_language or input_language or "en"
    confidence = "high"
    if input_mixed or dialogue_mixed:
        confidence = "medium"
    if not normalized_prompt:
        confidence = "low"

    notes_parts: list[str] = []
    if input_mixed:
        notes_parts.append("Input mixes Chinese and English tokens; dominant language selected.")
    if dialogue_mixed:
        notes_parts.append("Dialogue mixes Chinese and English tokens; dominant spoken language selected.")

    return LanguageDetectOutput(
        input_language=input_language or "en",
        dialogue_language=dialogue_language,
        audio_language=audio_language,
        confidence=confidence,
        mixed_language=bool(input_mixed or dialogue_mixed),
        notes=" ".join(notes_parts).strip(),
        provider_metadata={"provider": "deterministic", "step_name": "language_detect"},
    )


def _extract_dialogue_text(raw_prompt: str) -> str:
    quoted_segments = [segment.strip() for segment in _QUOTED_SEGMENT_PATTERN.findall(raw_prompt) if segment.strip()]
    if quoted_segments:
        return " ".join(quoted_segments)
    if ":" in raw_prompt:
        tail = raw_prompt.split(":", 1)[1].strip()
        if tail:
            return tail
    if "：" in raw_prompt:
        tail = raw_prompt.split("：", 1)[1].strip()
        if tail:
            return tail
    return raw_prompt


def _classify_language(text: str) -> tuple[str, bool]:
    normalized = str(text or "").strip()
    if not normalized:
        return "", False
    cjk_count = len(_CJK_PATTERN.findall(normalized))
    latin_word_count = len(_LATIN_WORD_PATTERN.findall(normalized))
    if cjk_count and not latin_word_count:
        return "zh", False
    if latin_word_count and not cjk_count:
        return "en", False
    if cjk_count and latin_word_count:
        if cjk_count >= max(2, latin_word_count):
            return "zh", True
        return "en", True
    return "en", False
