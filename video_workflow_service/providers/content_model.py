from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .base import VideoGenerationRequest


ContentItemKind = Literal["text", "image", "first_frame", "last_frame"]


@dataclass(slots=True)
class ProviderContentItem:
    kind: ContentItemKind
    value: str

    @classmethod
    def text(cls, value: str) -> "ProviderContentItem":
        return cls(kind="text", value=value)

    @classmethod
    def image(cls, value: str) -> "ProviderContentItem":
        return cls(kind="image", value=value)

    @classmethod
    def first_frame(cls, value: str) -> "ProviderContentItem":
        return cls(kind="first_frame", value=value)

    @classmethod
    def last_frame(cls, value: str) -> "ProviderContentItem":
        return cls(kind="last_frame", value=value)


def build_video_generation_content_items(
    *,
    prompt_text: str,
    request: VideoGenerationRequest,
) -> list[ProviderContentItem]:
    items: list[ProviderContentItem] = []
    if prompt_text.strip():
        items.append(ProviderContentItem.text(prompt_text.strip()))

    if request.first_frame_image and request.last_frame_image:
        items.append(ProviderContentItem.first_frame(request.first_frame_image))
        items.append(ProviderContentItem.last_frame(request.last_frame_image))
        return items

    if request.first_frame_image:
        items.append(ProviderContentItem.first_frame(request.first_frame_image))
        return items

    if request.image_url:
        items.append(ProviderContentItem.image(request.image_url))

    return items
