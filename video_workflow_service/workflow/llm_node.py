from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar
import json

from video_workflow_service.infrastructure.config import ServiceSettings
from video_workflow_service.llm.base import LLMMessage, LLMRequest
from video_workflow_service.llm.factory import get_llm_provider
from video_workflow_service.llm.model_registry import resolve_llm_model
from video_workflow_service.llm.provider_registry import resolve_llm_provider_name
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


T = TypeVar("T")


@dataclass(slots=True)
class StructuredWorkflowNodeResult:
    provider: str
    model: str
    step_name: str
    template_version: str
    raw_content: str
    parsed_payload: dict[str, Any]
    metadata: dict[str, Any]


def run_structured_llm_node(
    *,
    settings: ServiceSettings,
    trace_logger: WorkflowTraceLogger,
    project_id: str,
    step_name: str,
    template_version: str,
    input_payload: dict[str, Any],
    message_builder: Callable[[dict[str, Any]], tuple[Any, Any]],
    validator: Callable[[dict[str, Any]], T],
    repair_prompt_builder: Callable[[dict[str, Any], dict[str, Any], Exception], str | None] | None = None,
) -> tuple[T, StructuredWorkflowNodeResult]:
    provider_name = resolve_llm_provider_name(settings, step_name)
    model = resolve_llm_model(settings, step_name, provider_name=provider_name)
    provider = get_llm_provider(settings, provider_name=provider_name)
    system_prompt, user_prompt = message_builder(input_payload)
    request = LLMRequest(
        step_name=step_name,
        model=model,
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ],
        input_payload=input_payload,
        response_format={"type": "json_object"},
        metadata={"template_version": template_version},
    )
    trace_logger.append(
        project_id,
        event_type=f"{step_name}_requested",
        step=step_name,
        status="requested",
        details={
            "provider": provider.name,
            "model": model,
            "template_version": template_version,
            "input_payload": input_payload,
        },
    )
    response = None
    repair_attempted = False
    try:
        response = provider.generate(request)
        parsed_payload = _parse_json_payload(response.content)
        try:
            validated = validator(parsed_payload)
        except Exception as exc:
            repair_prompt = None
            if repair_prompt_builder is not None:
                repair_prompt = repair_prompt_builder(input_payload, parsed_payload, exc)
            if not repair_prompt:
                raise
            repair_attempted = True
            trace_logger.append(
                project_id,
                event_type=f"{step_name}_repair_requested",
                step=step_name,
                status="requested",
                details={
                    "provider": provider.name,
                    "model": model,
                    "template_version": template_version,
                    "validation_error": str(exc),
                    "invalid_output_payload": parsed_payload,
                },
            )
            repair_request = LLMRequest(
                step_name=step_name,
                model=model,
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=repair_prompt),
                ],
                input_payload=input_payload,
                response_format={"type": "json_object"},
                metadata={"template_version": template_version, "repair_attempt": 1},
            )
            response = provider.generate(repair_request)
            parsed_payload = _parse_json_payload(response.content)
            validated = validator(parsed_payload)
    except Exception as exc:
        failure_details = {
            "provider": provider.name,
            "model": model,
            "template_version": template_version,
            "error": str(exc),
        }
        if response is not None:
            failure_details["raw_content"] = response.content[:4000]
            failure_details["metadata"] = dict(response.metadata)
        if repair_attempted:
            failure_details["repair_attempted"] = True
        trace_logger.append(
            project_id,
            event_type=f"{step_name}_failed",
            step=step_name,
            status="failed",
            details=failure_details,
        )
        raise
    metadata = dict(response.metadata)
    if repair_attempted:
        metadata["repair_attempted"] = True
    result = StructuredWorkflowNodeResult(
        provider=response.provider,
        model=response.model,
        step_name=step_name,
        template_version=template_version,
        raw_content=response.content,
        parsed_payload=parsed_payload,
        metadata=metadata,
    )
    trace_logger.append(
        project_id,
        event_type=f"{step_name}_completed",
        step=step_name,
        status="completed",
        details={
            "provider": response.provider,
            "model": response.model,
            "template_version": template_version,
            "output_payload": parsed_payload,
            "metadata": metadata,
            "repair_attempted": repair_attempted,
        },
    )
    return validated, result


def _parse_json_payload(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = _strip_code_fence(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Structured LLM output was not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be a JSON object")
    return payload


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
