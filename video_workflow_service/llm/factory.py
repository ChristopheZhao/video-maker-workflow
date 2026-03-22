from __future__ import annotations

from video_workflow_service.infrastructure.config import ServiceSettings

from .base import LLMProvider
from .deepseek import DeepSeekLLMProvider
from .doubao_ark import DoubaoArkLLMProvider
from .mock import MockLLMProvider

_LLM_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {}


def register_llm_provider(provider_cls: type[LLMProvider]) -> None:
    _LLM_PROVIDER_REGISTRY[provider_cls.name.strip().lower()] = provider_cls


def get_llm_provider(settings: ServiceSettings, provider_name: str | None = None) -> LLMProvider:
    resolved_name = (provider_name or settings.llm_provider).strip().lower()
    provider_cls = _LLM_PROVIDER_REGISTRY.get(resolved_name)
    if provider_cls is None:
        raise ValueError(f"Unsupported llm provider: {provider_name or settings.llm_provider}")
    return provider_cls(settings)


register_llm_provider(DoubaoArkLLMProvider)
register_llm_provider(DeepSeekLLMProvider)
register_llm_provider(MockLLMProvider)
