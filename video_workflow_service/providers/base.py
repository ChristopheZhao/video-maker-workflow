from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings


@dataclass(slots=True)
class VideoGenerationRequest:
    project_id: str
    scene_id: str
    scene_index: int
    prompt: str
    duration_seconds: int
    aspect_ratio: str
    image_url: str | None = None
    first_frame_image: str | None = None
    last_frame_image: str | None = None
    storyboard_notes: str = ""
    audio_language: str = ""
    generate_audio: bool = False


@dataclass(slots=True)
class VideoGenerationResult:
    provider: str
    model: str
    generation_mode: str
    video_rel_path: str
    final_frame_rel_path: str
    metadata: dict[str, Any] = field(default_factory=dict)


class VideoProvider(ABC):
    name: str

    def __init__(self, settings: ServiceSettings):
        self.settings = settings

    @abstractmethod
    def get_capabilities(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def generate_video(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        raise NotImplementedError
