from __future__ import annotations

import json
import urllib.request
from urllib.error import HTTPError

from .base import LLMProvider, LLMRequest, LLMResponse


class DoubaoArkLLMProvider(LLMProvider):
    name = "doubao"

    def __init__(self, settings):
        super().__init__(settings)
        self.api_key = settings.doubao_llm_api_key
        self.base_url = settings.doubao_llm_base_url
        self.chat_path = settings.doubao_llm_chat_path
        self.timeout_seconds = settings.llm_timeout_seconds

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("Doubao LLM provider requires DOUBAO_API_KEY or DOUBAO_LLM_API_KEY.")
        url = f"{self.base_url.rstrip('/')}{self.chat_path}"
        payload = self._build_payload(request, include_response_format=True)
        metadata: dict[str, object] = {
            "url": url,
            "response_format_fallback": False,
            "initial_error": None,
        }
        try:
            body = self._send_request(url, payload)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            metadata["initial_error"] = _extract_error_metadata(exc.code, error_body)
            if request.response_format and _should_retry_without_response_format(exc.code, error_body):
                payload = self._build_payload(request, include_response_format=False)
                body = self._send_request(url, payload)
                metadata["response_format_fallback"] = True
            else:
                raise RuntimeError(
                    f"Doubao LLM request failed: status={exc.code} body={error_body}"
                ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                f"Doubao LLM request timed out after {self.timeout_seconds}s during {request.step_name}"
            ) from exc

        content = _extract_message_content(body)
        if not content:
            raise RuntimeError(f"Doubao LLM response contained no message content: {body}")
        return LLMResponse(
            provider=self.name,
            model=request.model,
            content=content,
            metadata=metadata | {"usage": body.get("usage"), "id": body.get("id")},
        )

    def _build_payload(self, request: LLMRequest, *, include_response_format: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
        }
        if include_response_format and request.response_format:
            payload["response_format"] = request.response_format
        return payload

    def _send_request(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        http_request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


def _extract_message_content(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                extracted = _normalize_content(content)
                if extracted:
                    return extracted
    output = payload.get("output")
    if isinstance(output, list):
        extracted = _normalize_content(output)
        if extracted:
            return extracted
    return ""


def _normalize_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    fragments.append(item["text"])
                elif isinstance(item.get("content"), str):
                    fragments.append(item["content"])
            elif isinstance(item, str):
                fragments.append(item)
        return "\n".join(fragment.strip() for fragment in fragments if fragment.strip()).strip()
    return ""


def _should_retry_without_response_format(status_code: int, error_body: str) -> bool:
    if status_code != 400:
        return False
    details = _extract_error_metadata(status_code, error_body)
    error_code = str(details.get("code") or "")
    error_param = str(details.get("param") or "")
    normalized_param = error_param.lower()
    return (
        error_code == "InvalidParameter"
        and normalized_param in {"response_format", "response_format.type"}
    )


def _extract_error_metadata(status_code: int, error_body: str) -> dict[str, object]:
    details: dict[str, object] = {
        "status": status_code,
        "code": "",
        "param": "",
        "type": "",
        "message": error_body,
    }
    try:
        payload = json.loads(error_body)
    except json.JSONDecodeError:
        return details
    if not isinstance(payload, dict):
        return details
    error = payload.get("error")
    if not isinstance(error, dict):
        return details
    code = error.get("code")
    param = error.get("param")
    error_type = error.get("type")
    message = error.get("message")
    if isinstance(code, str):
        details["code"] = code
    if isinstance(param, str):
        details["param"] = param
    if isinstance(error_type, str):
        details["type"] = error_type
    if isinstance(message, str):
        details["message"] = message
    return details
