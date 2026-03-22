from __future__ import annotations

from typing import Any

from video_workflow_service.infrastructure.config import ServiceSettings
from .base import VideoProvider
from .doubao import DoubaoVideoProvider
from .mock import MockVideoProvider

PROVIDER_REGISTRY = {
    "doubao": DoubaoVideoProvider,
    "mock": MockVideoProvider,
}


def get_video_provider(settings: ServiceSettings, provider_name: str | None) -> VideoProvider:
    normalized = str(provider_name or settings.default_provider).strip().lower()
    provider_cls = PROVIDER_REGISTRY.get(normalized)
    if provider_cls is None:
        raise ValueError(f"Unsupported video provider: {normalized}")
    return provider_cls(settings)


def list_video_providers(settings: ServiceSettings) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for name, provider_cls in sorted(PROVIDER_REGISTRY.items()):
        provider = provider_cls(settings)
        providers.append(
            {
                "name": name,
                "capabilities": provider.get_capabilities(),
            }
        )
    return providers
