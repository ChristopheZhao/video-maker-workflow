from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
from pathlib import Path
import urllib.request
from urllib.error import HTTPError

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


_MOCK_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WlAb9sAAAAASUVORK5CYII="
)


@dataclass(slots=True)
class FirstFramePrepareInput:
    project_id: str
    provider: str
    scene_id: str
    scene_index: int
    prompt: str
    aspect_ratio: str
    model: str = ""


@dataclass(slots=True)
class FirstFramePrepareOutput:
    first_frame_image: str
    first_frame_prompt: str
    first_frame_origin: str = "generated"
    first_frame_status: str = "ready"
    provider_metadata: dict[str, object] = field(default_factory=dict)


def prepare_first_frame_step(
    contract: FirstFramePrepareInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> FirstFramePrepareOutput:
    trace_logger.append(
        project_id,
        event_type="first_frame_prepare_requested",
        step="first_frame_prepare",
        status="requested",
        details={
            "scene_id": contract.scene_id,
            "provider": contract.provider,
            "aspect_ratio": contract.aspect_ratio,
            "prompt": contract.prompt,
        },
    )
    if contract.provider == "mock":
        output = _prepare_mock_first_frame(contract, settings)
    elif contract.provider == "doubao":
        output = _prepare_doubao_first_frame(contract, settings)
    else:
        raise ValueError(f"Unsupported first-frame provider: {contract.provider}")
    trace_logger.append(
        project_id,
        event_type="first_frame_prepare_completed",
        step="first_frame_prepare",
        status="completed",
        details={
            "scene_id": contract.scene_id,
            "first_frame_image": output.first_frame_image,
            "first_frame_origin": output.first_frame_origin,
            "provider_metadata": output.provider_metadata,
        },
    )
    return output


def _prepare_mock_first_frame(
    contract: FirstFramePrepareInput,
    settings: ServiceSettings,
) -> FirstFramePrepareOutput:
    output_path = settings.artifact_dir / contract.project_id / "first_frames" / f"{contract.scene_id}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(_MOCK_PNG_BASE64))
    return FirstFramePrepareOutput(
        first_frame_image=str(output_path),
        first_frame_prompt=contract.prompt,
        provider_metadata={"provider": "mock", "model": "mock-first-frame"},
    )


def _prepare_doubao_first_frame(
    contract: FirstFramePrepareInput,
    settings: ServiceSettings,
) -> FirstFramePrepareOutput:
    if not settings.doubao_api_key:
        raise RuntimeError("DOUBAO_API_KEY is missing. The workflow requires a real provider.")
    url = f"{settings.doubao_base_url.rstrip('/')}{settings.doubao_image_generate_path}"
    payload = {
        "model": contract.model or settings.image_default_model,
        "prompt": contract.prompt,
        "size": _aspect_ratio_to_image_size(contract.aspect_ratio),
        "response_format": "b64_json",
        "watermark": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.doubao_api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"Doubao first-frame generation failed: status={exc.code} body={error_body}"
        ) from exc

    image_item = _extract_image_item(body)
    output_path = settings.artifact_dir / contract.project_id / "first_frames" / f"{contract.scene_id}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(image_item.get("b64_json"), str) and image_item["b64_json"]:
        output_path.write_bytes(base64.b64decode(image_item["b64_json"]))
    elif isinstance(image_item.get("url"), str) and image_item["url"]:
        _download_file(image_item["url"], output_path)
    else:
        raise RuntimeError(f"Doubao first-frame generation returned no image payload: {body}")
    return FirstFramePrepareOutput(
        first_frame_image=str(output_path),
        first_frame_prompt=contract.prompt,
        provider_metadata={
            "provider": "doubao",
            "model": payload["model"],
            "url": url,
            "response_format": payload["response_format"],
        },
    )


def _extract_image_item(payload: dict[str, object]) -> dict[str, object]:
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            return nested[0]
        return data
    raise RuntimeError(f"Unexpected image generation payload: {payload}")


def _download_file(url: str, output_path: Path) -> None:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=120) as response:
        output_path.write_bytes(response.read())


def _aspect_ratio_to_image_size(aspect_ratio: str) -> str:
    normalized = str(aspect_ratio or "").strip()
    if normalized == "9:16":
        return "1440x2560"
    if normalized == "16:9":
        return "2560x1440"
    if normalized == "1:1":
        return "2048x2048"
    return "1440x2560"
