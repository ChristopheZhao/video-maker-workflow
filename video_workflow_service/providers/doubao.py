from __future__ import annotations

from mimetypes import guess_type
import logging
from pathlib import Path
import base64
from collections import OrderedDict
from dataclasses import dataclass
import json
import os
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

from video_workflow_service.media.ffmpeg_pipeline import extract_final_frame
from .base import VideoGenerationRequest, VideoGenerationResult, VideoProvider
from .content_model import ProviderContentItem, build_video_generation_content_items


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NormalizedVideoTaskResult:
    status: str = ""
    video_url: str | None = None
    last_frame_url: str | None = None
    resolution: str | None = None
    ratio: str | None = None
    duration: int | None = None
    generate_audio: bool | None = None


class DoubaoVideoProvider(VideoProvider):
    name = "doubao"

    def __init__(self, settings):
        super().__init__(settings)
        self.api_key = settings.doubao_api_key
        self.base_url = settings.doubao_base_url
        self.create_path = settings.doubao_create_path
        self.query_path = settings.doubao_query_path
        self.query_path_fallbacks = list(
            OrderedDict.fromkeys(
                [
                    self.query_path,
                    "/api/v3/videos/generations/{task_id}",
                    "/api/v3/contents/generations/tasks/{task_id}",
                ]
            )
        )
        self.mode_model_mapping = {
            "text_to_video": os.getenv("DOUBAO_T2V_MODEL", settings.doubao_default_model),
            "image_to_video": os.getenv("DOUBAO_I2V_SINGLE_MODEL", settings.doubao_default_model),
            "image_to_video_fallback": os.getenv(
                "DOUBAO_I2V_SINGLE_ALTER_MODEL",
                settings.doubao_default_model,
            ),
            "first_last_frame": os.getenv("DOUBAO_I2V_FLF_MODEL", settings.doubao_default_model),
        }
        self.poll_attempts = int(os.getenv("DOUBAO_POLL_ATTEMPTS", "90"))
        self.poll_interval_seconds = int(os.getenv("DOUBAO_POLL_INTERVAL_SECONDS", "5"))

    def get_capabilities(self) -> dict[str, object]:
        return {
            "min_scene_duration_seconds": self.settings.doubao_min_scene_duration_seconds,
            "max_scene_duration_seconds": self.settings.doubao_max_scene_duration_seconds,
            "supports_first_last_frame": True,
            "create_path": self.create_path,
            "query_path": self.query_path,
            "mode_model_mapping": self.mode_model_mapping,
            "configured": bool(self.api_key and self.base_url),
            "supports_native_audio": True,
        }

    def generate_video(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        if not self.api_key:
            raise RuntimeError("DOUBAO_API_KEY is missing. The workflow requires a real provider.")

        create_url = f"{self.base_url.rstrip('/')}{self.create_path}"
        generation_mode = self._determine_generation_mode(request)
        model = self.mode_model_mapping[generation_mode]
        prompt_text = self._compose_prompt_text(request)
        content_items = self._build_content_items(prompt_text, request)
        request_summary = self._summarize_request(request, generation_mode, content_items)
        payload = {
            "model": model,
            "content": self._serialize_content_items(content_items),
            "generate_audio": bool(request.generate_audio and self._supports_audio(model)),
            "return_last_frame": True,
            "watermark": False,
        }

        logger.info(
            "doubao generation requested | project_id=%s scene_id=%s mode=%s model=%s audio=%s has_image_url=%s has_first_frame=%s has_last_frame=%s content_items=%s",
            request.project_id,
            request.scene_id,
            generation_mode,
            model,
            payload["generate_audio"],
            bool(request.image_url),
            bool(request.first_frame_image),
            bool(request.last_frame_image),
            ",".join(request_summary["content_item_kinds"]),
        )
        task_id = self._create_task(create_url, payload)
        task_payload = self._poll_task(task_id)
        task_result = self._normalize_task_result(task_payload)
        video_url = task_result.video_url
        if not isinstance(video_url, str) or not video_url:
            raise RuntimeError(f"Doubao task {task_id} succeeded without video_url")

        last_frame_url = task_result.last_frame_url
        video_rel_path = f"{request.project_id}/scenes/{request.scene_id}.mp4"
        final_frame_rel_path = f"{request.project_id}/scenes/{request.scene_id}_last.png"
        video_path = self.settings.artifact_dir / video_rel_path
        final_frame_path = self.settings.artifact_dir / final_frame_rel_path

        self._download_file(video_url, video_path)
        if isinstance(last_frame_url, str) and last_frame_url:
            self._download_file(last_frame_url, final_frame_path)
        else:
            extract_final_frame(
                ffmpeg_bin=self.settings.ffmpeg_bin,
                video_path=video_path,
                output_path=final_frame_path,
            )

        metadata = {
            "task_id": task_id,
            "video_url": video_url,
            "last_frame_url": last_frame_url,
            "resolution": task_result.resolution,
            "ratio": task_result.ratio,
            "duration": task_result.duration,
            "generate_audio": (
                task_result.generate_audio
                if isinstance(task_result.generate_audio, bool)
                else payload["generate_audio"]
            ),
            "request_summary": request_summary,
        }
        logger.info(
            "doubao generation completed | task_id=%s scene_id=%s video_rel_path=%s",
            task_id,
            request.scene_id,
            video_rel_path,
        )
        return VideoGenerationResult(
            provider=self.name,
            model=model,
            generation_mode=generation_mode,
            video_rel_path=video_rel_path,
            final_frame_rel_path=final_frame_rel_path,
            metadata=metadata,
        )

    def _determine_generation_mode(self, request: VideoGenerationRequest) -> str:
        if request.first_frame_image and request.last_frame_image:
            return "first_last_frame"
        if request.image_url or request.first_frame_image:
            return "image_to_video"
        return "text_to_video"

    def _compose_prompt_text(self, request: VideoGenerationRequest) -> str:
        return (
            f"{request.prompt.strip()} --dur {request.duration_seconds} "
            f"--rt {request.aspect_ratio} --rs 720p"
        )

    def _build_content_items(
        self,
        prompt_text: str,
        request: VideoGenerationRequest,
    ) -> list[ProviderContentItem]:
        return build_video_generation_content_items(prompt_text=prompt_text, request=request)

    def _summarize_request(
        self,
        request: VideoGenerationRequest,
        generation_mode: str,
        content_items: list[ProviderContentItem],
    ) -> dict[str, object]:
        return {
            "generation_mode": generation_mode,
            "has_image_url": bool(request.image_url),
            "has_first_frame": bool(request.first_frame_image),
            "has_last_frame": bool(request.last_frame_image),
            "content_item_kinds": [item.kind for item in content_items],
        }

    def _serialize_content_items(
        self,
        items: list[ProviderContentItem],
    ) -> list[dict[str, object]]:
        content: list[dict[str, object]] = []
        has_last_frame = any(item.kind == "last_frame" for item in items)

        for item in items:
            if item.kind == "text":
                content.append({"type": "text", "text": item.value})
                continue

            image_url = self._materialize_image_input(item.value)
            if not image_url:
                continue

            payload: dict[str, object] = {"type": "image_url", "image_url": {"url": image_url}}
            if item.kind == "first_frame":
                payload["role"] = "first_frame"
            elif item.kind == "last_frame" and has_last_frame:
                payload["role"] = "last_frame"
            content.append(payload)
        return content

    def _materialize_image_input(self, candidate: str | None) -> str | None:
        if not candidate:
            return None
        if candidate.startswith("http://") or candidate.startswith("https://") or candidate.startswith("data:"):
            return candidate
        parsed = urllib.parse.urlparse(candidate)
        raw_path = parsed.path if parsed.scheme == "file" else candidate
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            return None
        mime_type, _ = guess_type(path.name)
        mime = mime_type or "image/png"
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    def _create_task(self, create_url: str, payload: dict[str, object]) -> str:
        request = urllib.request.Request(
            create_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Doubao create task failed: status={exc.code} body={error_body}"
            ) from exc
        task_id = body.get("id") or body.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError(f"Doubao create task returned no id: {body}")
        logger.info("doubao task created | task_id=%s create_url=%s", task_id, create_url)
        return task_id

    def _poll_task(self, task_id: str) -> dict[str, object]:
        errors: list[str] = []
        last_seen_status: str | None = None
        for _ in range(self.poll_attempts):
            for query_template in self.query_path_fallbacks:
                query_url = f"{self.base_url.rstrip('/')}{query_template.format(task_id=task_id)}"
                request = urllib.request.Request(
                    query_url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    method="GET",
                )
                try:
                    with urllib.request.urlopen(request, timeout=120) as response:
                        body = json.loads(response.read().decode("utf-8"))
                except HTTPError as exc:
                    error_body = exc.read().decode("utf-8", errors="ignore")
                    errors.append(f"url={query_url} status={exc.code} body={error_body[:240]}")
                    continue
                normalized = self._normalize_task_result(body)
                if normalized.status:
                    last_seen_status = normalized.status
                if self._is_success_status(normalized.status) or normalized.video_url:
                    logger.info("doubao task succeeded | task_id=%s query_url=%s", task_id, query_url)
                    return body
                if self._is_failed_status(normalized.status):
                    logger.error("doubao task failed | task_id=%s status=%s", task_id, normalized.status)
                    raise RuntimeError(f"Doubao task {task_id} failed: {body}")
            time.sleep(self.poll_interval_seconds)
        logger.error("doubao task timed out | task_id=%s", task_id)
        raise RuntimeError(
            f"Doubao task {task_id} timed out or could not be queried: last_status={last_seen_status or 'unknown'} {' | '.join(errors[-6:])}"
        )

    def _normalize_task_result(self, payload: dict[str, object]) -> NormalizedVideoTaskResult:
        return NormalizedVideoTaskResult(
            status=self._extract_task_status(payload),
            video_url=self._extract_video_url(payload),
            last_frame_url=self._extract_last_frame_url(payload),
            resolution=self._extract_scalar(payload, "resolution"),
            ratio=self._extract_scalar(payload, "ratio"),
            duration=self._extract_duration(payload),
            generate_audio=self._extract_generate_audio(payload),
        )

    def _extract_task_status(self, payload: dict[str, object]) -> str:
        data = payload.get("data")
        content = payload.get("content")
        data_dict = data if isinstance(data, dict) else {}
        content_dict = content if isinstance(content, dict) else {}
        status = (
            payload.get("status")
            or payload.get("task_status")
            or data_dict.get("status")
            or content_dict.get("status")
        )
        return str(status).strip().lower() if isinstance(status, str) and status.strip() else ""

    def _extract_video_url(self, payload: dict[str, object]) -> str | None:
        data = payload.get("data")
        content = payload.get("content")
        data_dict = data if isinstance(data, dict) else {}
        content_dict = content if isinstance(content, dict) else {}
        candidates = [
            payload.get("video_url"),
            content_dict.get("video_url"),
            data_dict.get("video_url"),
        ]
        video_result = data_dict.get("video_result")
        if isinstance(video_result, list) and video_result:
            first_item = video_result[0]
            if isinstance(first_item, dict):
                candidates.append(first_item.get("url"))
                candidates.append(first_item.get("video_url"))
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

    def _extract_last_frame_url(self, payload: dict[str, object]) -> str | None:
        data = payload.get("data")
        content = payload.get("content")
        data_dict = data if isinstance(data, dict) else {}
        content_dict = content if isinstance(content, dict) else {}
        candidates = [
            payload.get("last_frame_url"),
            content_dict.get("last_frame_url"),
            data_dict.get("last_frame_url"),
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

    def _is_success_status(self, status: str) -> bool:
        return status.lower() in {"success", "succeeded", "completed", "done"}

    def _is_failed_status(self, status: str) -> bool:
        return status.lower() in {"fail", "failed", "error", "cancelled", "canceled", "expired"}

    def _extract_scalar(self, payload: dict[str, object], key: str) -> str | None:
        data = payload.get("data")
        content = payload.get("content")
        data_dict = data if isinstance(data, dict) else {}
        content_dict = content if isinstance(content, dict) else {}
        candidates = [payload.get(key), data_dict.get(key), content_dict.get(key)]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

    def _extract_duration(self, payload: dict[str, object]) -> int | None:
        data = payload.get("data")
        content = payload.get("content")
        data_dict = data if isinstance(data, dict) else {}
        content_dict = content if isinstance(content, dict) else {}
        for candidate in (payload.get("duration"), data_dict.get("duration"), content_dict.get("duration")):
            if isinstance(candidate, int):
                return candidate
            if isinstance(candidate, str) and candidate.isdigit():
                return int(candidate)
        return None

    def _extract_generate_audio(self, payload: dict[str, object]) -> bool | None:
        data = payload.get("data")
        content = payload.get("content")
        data_dict = data if isinstance(data, dict) else {}
        content_dict = content if isinstance(content, dict) else {}
        for candidate in (
            payload.get("generate_audio"),
            data_dict.get("generate_audio"),
            content_dict.get("generate_audio"),
        ):
            if isinstance(candidate, bool):
                return candidate
        return None

    def _download_file(self, file_url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(file_url, timeout=180) as response:
            output_path.write_bytes(response.read())

    def _supports_audio(self, model: str) -> bool:
        return model.startswith("doubao-seedance-1-5-pro")
