from __future__ import annotations

import base64
from mimetypes import guess_type
from pathlib import Path
from typing import Any
import urllib.parse

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.workflow.contracts import (
    FirstFrameAnalyzeInput,
    FirstFrameAnalyzeOutput,
)
from video_workflow_service.workflow.llm_node import run_structured_llm_node
from video_workflow_service.workflow.llm_prompts import (
    FIRST_FRAME_ANALYZE_TEMPLATE_VERSION,
    build_first_frame_analyze_system_prompt,
    build_first_frame_analyze_user_text,
)
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


def analyze_first_frame_step(
    contract: FirstFrameAnalyzeInput,
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
) -> FirstFrameAnalyzeOutput:
    input_payload = {
        "scene_id": contract.scene_id,
        "scene_index": contract.scene_index,
        "first_frame_source": contract.first_frame_source,
        "title": contract.title,
        "narrative": contract.narrative,
        "visual_goal": contract.visual_goal,
    }
    output, result = run_structured_llm_node(
        settings=settings,
        trace_logger=trace_logger,
        project_id=project_id,
        step_name="first_frame_analyze",
        template_version=FIRST_FRAME_ANALYZE_TEMPLATE_VERSION,
        input_payload=input_payload,
        message_builder=lambda payload: _build_first_frame_analyze_messages(payload, contract.image_input),
        validator=_validate_first_frame_analyze_payload,
    )
    output.provider_metadata = {
        "provider": result.provider,
        "model": result.model,
        "template_version": result.template_version,
    } | result.metadata
    return output


def _build_first_frame_analyze_messages(
    input_payload: dict[str, Any],
    image_input: str,
) -> tuple[str, list[dict[str, object]]]:
    image_url = _materialize_image_input(image_input)
    if not image_url:
        raise ValueError("First-frame analysis requires a valid image input.")
    return (
        build_first_frame_analyze_system_prompt(),
        [
            {"type": "text", "text": build_first_frame_analyze_user_text(input_payload)},
            {"type": "image_url", "image_url": {"url": image_url}},
        ],
    )


def _materialize_image_input(candidate: str | None) -> str | None:
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


def _validate_first_frame_analyze_payload(payload: dict[str, Any]) -> FirstFrameAnalyzeOutput:
    return FirstFrameAnalyzeOutput(
        subject_presence=_normalize_text(payload.get("subject_presence", "")),
        subject_pose=_normalize_text(payload.get("subject_pose", "")),
        hand_prop_state=_normalize_text(payload.get("hand_prop_state", "")),
        prop_description=_normalize_text(payload.get("prop_description", "")),
        framing=_normalize_text(payload.get("framing", "")),
        setting=_normalize_text(payload.get("setting", "")),
        lighting=_normalize_text(payload.get("lighting", "")),
        wardrobe=_normalize_text(payload.get("wardrobe", "")),
        continuation_constraints=_normalize_text(payload.get("continuation_constraints", "")),
        analysis_notes=_normalize_text(payload.get("analysis_notes", "")),
    )


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()
