from __future__ import annotations

from hashlib import md5
from pathlib import Path
from typing import Any
import json
import urllib.parse

from video_workflow_service.media.ffmpeg_pipeline import (
    extract_final_frame,
    render_color_clip,
    resolution_for_ratio,
)
from .base import VideoGenerationRequest, VideoGenerationResult, VideoProvider


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class MockVideoProvider(VideoProvider):
    name = "mock"

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "min_scene_duration_seconds": 1,
            "max_scene_duration_seconds": None,
            "supports_first_last_frame": True,
            "resolution": self.settings.default_resolution,
            "mode_model_mapping": {
                "text_to_video": "mock-text2video",
                "image_to_video": "mock-image2video",
                "first_last_frame": "mock-first-last-frame",
            },
        }

    def generate_video(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        scene_dir = self.settings.artifact_dir / request.project_id / "scenes"
        scene_dir.mkdir(parents=True, exist_ok=True)
        video_rel_path = f"{request.project_id}/scenes/{request.scene_id}.mp4"
        final_frame_rel_path = f"{request.project_id}/scenes/{request.scene_id}_last.png"
        video_path = self.settings.artifact_dir / video_rel_path
        final_frame_path = self.settings.artifact_dir / final_frame_rel_path
        meta_path = scene_dir / f"{request.scene_id}.json"

        resolved_input = self._resolve_local_image_input(request)
        generation_mode = self._determine_generation_mode(request, resolved_input)
        size = resolution_for_ratio(request.aspect_ratio, self.settings.default_resolution)

        render_color_clip(
            ffmpeg_bin=self.settings.ffmpeg_bin,
            color=self._color_for_request(request, resolved_input),
            output_path=video_path,
            duration_seconds=request.duration_seconds,
            size=size,
        )

        extract_final_frame(
            ffmpeg_bin=self.settings.ffmpeg_bin,
            video_path=video_path,
            output_path=final_frame_path,
        )

        metadata = {
            "prompt": request.prompt,
            "duration_seconds": request.duration_seconds,
            "aspect_ratio": request.aspect_ratio,
            "resolved_input": str(resolved_input) if resolved_input else None,
            "storyboard_notes": request.storyboard_notes,
            "capabilities": self.get_capabilities(),
        }
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return VideoGenerationResult(
            provider=self.name,
            model=self.get_capabilities()["mode_model_mapping"][generation_mode],
            generation_mode=generation_mode,
            video_rel_path=video_rel_path,
            final_frame_rel_path=final_frame_rel_path,
            metadata=metadata,
        )

    def _resolve_local_image_input(self, request: VideoGenerationRequest) -> Path | None:
        for candidate in (request.first_frame_image, request.image_url):
            path = self._normalize_local_path(candidate)
            if path is not None:
                return path
        return None

    def _normalize_local_path(self, candidate: str | None) -> Path | None:
        if not candidate:
            return None
        parsed = urllib.parse.urlparse(candidate)
        if parsed.scheme in {"http", "https"}:
            return None
        path = Path(parsed.path if parsed.scheme == "file" else candidate).expanduser().resolve()
        if not path.exists() or path.suffix.lower() not in IMAGE_SUFFIXES:
            return None
        return path

    def _determine_generation_mode(
        self,
        request: VideoGenerationRequest,
        resolved_input: Path | None,
    ) -> str:
        if request.first_frame_image and request.last_frame_image:
            return "first_last_frame"
        if resolved_input is not None:
            return "image_to_video"
        return "text_to_video"

    def _color_for_request(
        self,
        request: VideoGenerationRequest,
        resolved_input: Path | None,
    ) -> str:
        digest_source = request.prompt
        if resolved_input is not None:
            digest_source = f"{request.prompt}|{resolved_input}"
        digest = md5(digest_source.encode("utf-8")).hexdigest()
        return f"0x{digest[:6]}"
