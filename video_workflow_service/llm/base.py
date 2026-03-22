from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from abc import ABC, abstractmethod

from video_workflow_service.infrastructure.config import ServiceSettings


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: Any


@dataclass(slots=True)
class LLMRequest:
    step_name: str
    model: str
    messages: list[LLMMessage]
    input_payload: dict[str, Any] = field(default_factory=dict)
    response_format: dict[str, Any] | None = None
    temperature: float = 0.2
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResponse:
    provider: str
    model: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    name = "base"

    def __init__(self, settings: ServiceSettings):
        self.settings = settings

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
