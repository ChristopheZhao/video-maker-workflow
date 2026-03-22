from __future__ import annotations

import json
import urllib.request
from urllib.error import HTTPError

from .base import LLMProvider, LLMRequest, LLMResponse


class DeepSeekLLMProvider(LLMProvider):
    name = "deepseek"

    def __init__(self, settings):
        super().__init__(settings)
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url
        self.chat_path = settings.deepseek_chat_path
        self.timeout_seconds = settings.llm_timeout_seconds

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("DeepSeek LLM provider requires DEEPSEEK_API_KEY.")
        url = f"{self.base_url.rstrip('/')}{self.chat_path}"
        payload = self._build_payload(request)
        try:
            body = self._send_request(url, payload)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"DeepSeek LLM request failed: status={exc.code} body={error_body}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                f"DeepSeek LLM request timed out after {self.timeout_seconds}s during {request.step_name}"
            ) from exc

        content = _extract_message_content(body)
        if not content:
            raise RuntimeError(f"DeepSeek LLM response contained no message content: {body}")
        return LLMResponse(
            provider=self.name,
            model=request.model,
            content=content,
            metadata={"url": url, "usage": body.get("usage"), "id": body.get("id")},
        )

    def _build_payload(self, request: LLMRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
        }
        if request.response_format:
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
                if isinstance(content, str):
                    return content.strip()
    return ""
