from __future__ import annotations

import base64
import json
from pathlib import Path
import urllib.request
import uuid
from urllib.error import HTTPError

from .service import SubtitleAlignmentResult, SubtitleCue


class VolcengineSpeechAsrClient:
    name = "volcengine_speech_asr"

    def __init__(self, settings):
        self.app_id = settings.volcengine_speech_app_id
        self.access_token = settings.volcengine_speech_access_token
        self.base_url = settings.volcengine_speech_base_url
        self.recognize_path = settings.volcengine_speech_asr_submit_path
        self.resource_id = settings.volcengine_speech_asr_resource_id
        self.model_name = settings.volcengine_speech_asr_model_name
        self.timeout_seconds = settings.subtitle_request_timeout_seconds

    def recognize_audio(
        self,
        *,
        audio_path: Path,
        language: str | None = None,
    ) -> SubtitleAlignmentResult:
        if not self.app_id or not self.access_token:
            raise RuntimeError(
                "Volcengine speech ASR client requires VOLCENGINE_SPEECH_APP_ID and VOLCENGINE_SPEECH_ACCESS_TOKEN."
            )
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise RuntimeError(f"ASR fallback audio file does not exist: {audio_file}")

        payload = self._recognize_audio(audio_path=audio_file)
        cues = self._extract_cues(payload)
        if not cues:
            raise RuntimeError("Volcengine ASR fallback returned no utterance cues.")
        return SubtitleAlignmentResult(
            provider=self.name,
            alignment_strategy="asr_recognition",
            cues=cues,
            metadata={
                "request_language": language,
                "audio_file_name": audio_file.name,
                "audio_size_bytes": audio_file.stat().st_size,
                "utterance_count": len(cues),
            },
        )

    def _recognize_audio(self, *, audio_path: Path) -> dict[str, object]:
        payload = {
            "user": {"uid": self.app_id},
            "audio": {"data": base64.b64encode(audio_path.read_bytes()).decode("ascii")},
            "request": {
                "model_name": self.model_name,
                "show_utterances": True,
                "enable_punc": True,
            },
        }
        headers, response_payload = self._json_request(
            path=self.recognize_path,
            body=payload,
            action_name="run ASR fallback recognition",
            request_id=str(uuid.uuid4()),
        )
        status_code = str(headers.get("X-Api-Status-Code", "")).strip()
        if status_code and status_code != "20000000":
            raise RuntimeError(
                f"Volcengine ASR fallback recognition failed: code={status_code} message={headers.get('X-Api-Message', '')}"
            )
        return response_payload

    def _json_request(
        self,
        *,
        path: str,
        body: dict[str, object],
        action_name: str,
        request_id: str,
    ) -> tuple[dict[str, str], dict[str, object]]:
        url = f"{self.base_url.rstrip('/')}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Api-App-Key": self.app_id,
                "X-Api-Access-Key": self.access_token,
                "X-Api-Resource-Id": self.resource_id,
                "X-Api-Request-Id": request_id,
                "X-Api-Sequence": "-1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                headers = {key: value for key, value in response.headers.items()}
                raw_body = response.read().decode("utf-8", errors="ignore").strip()
                payload = json.loads(raw_body) if raw_body else {}
                return headers, payload
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Volcengine ASR fallback {action_name} failed: status={exc.code} body={error_body}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                f"Volcengine ASR fallback {action_name} timed out after {self.timeout_seconds}s"
            ) from exc

    def _extract_cues(self, payload: dict[str, object]) -> list[SubtitleCue]:
        cues: list[SubtitleCue] = []
        result = payload.get("result")
        if not isinstance(result, dict):
            return cues
        utterances = result.get("utterances")
        if not isinstance(utterances, list):
            return cues
        for item in utterances:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            cues.append(
                SubtitleCue(
                    start_time_ms=max(0, int(item.get("start_time", 0) or 0)),
                    end_time_ms=max(0, int(item.get("end_time", 0) or 0)),
                    text=text,
                )
            )
        return cues
