from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings


@dataclass(slots=True)
class SubtitleCue:
    start_time_ms: int
    end_time_ms: int
    text: str


@dataclass(slots=True)
class SubtitleAlignmentResult:
    provider: str
    alignment_strategy: str
    cues: list[SubtitleCue]
    metadata: dict[str, Any] = field(default_factory=dict)


class SubtitleClient(ABC):
    name = "base"

    def __init__(self, settings: ServiceSettings):
        self.settings = settings

    @abstractmethod
    def align_known_text(
        self,
        *,
        audio_path: Path,
        subtitle_text: str,
        language: str | None = None,
    ) -> SubtitleAlignmentResult:
        raise NotImplementedError
