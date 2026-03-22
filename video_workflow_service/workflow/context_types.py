from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ProjectGuidanceContext:
    target_duration_seconds: int = 0
    scene_count: int = 0
    input_language: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    language_confidence: str = ""
    creative_intent: str = ""
    style_guardrails: list[str] = field(default_factory=list)
    planning_notes: str = ""
    opening_truth_summary: str = ""
    global_dialogue_intent: str = ""
    character_anchor_summary: str = ""
    scene1_first_frame_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SceneGuidanceContext:
    working_prompt: str = ""
    dialogue_language: str = ""
    audio_language: str = ""
    character_presence_summary: str = ""
    first_frame_source: str = ""
    first_frame_anchor_summary: str = ""
    continuity_anchor_summary: str = ""
    dialogue_guidance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
