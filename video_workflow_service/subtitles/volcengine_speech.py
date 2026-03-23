from __future__ import annotations

import json
from pathlib import Path
import urllib.parse
import urllib.request
import uuid
from urllib.error import HTTPError

from .service import SubtitleAlignmentResult, SubtitleClient, SubtitleCue


class VolcengineSpeechSubtitleClient(SubtitleClient):
    name = "volcengine_speech"

    def __init__(self, settings):
        super().__init__(settings)
        self.app_id = settings.volcengine_speech_app_id
        self.access_token = settings.volcengine_speech_access_token
        self.base_url = settings.volcengine_speech_base_url
        self.ata_submit_path = settings.volcengine_speech_ata_submit_path
        self.ata_query_path = settings.volcengine_speech_ata_query_path
        self.punctuation_mode = settings.volcengine_speech_ata_punctuation_mode
        self.timeout_seconds = settings.subtitle_request_timeout_seconds

    def align_known_text(
        self,
        *,
        audio_path: Path,
        subtitle_text: str,
        language: str | None = None,
    ) -> SubtitleAlignmentResult:
        if not self.app_id or not self.access_token:
            raise RuntimeError(
                "Volcengine speech subtitle client requires VOLCENGINE_SPEECH_APP_ID and VOLCENGINE_SPEECH_ACCESS_TOKEN."
            )
        normalized_text = subtitle_text.strip()
        if not normalized_text:
            raise RuntimeError("Subtitle alignment requires non-empty subtitle text.")

        task_id = self._submit_audio(audio_path=audio_path, subtitle_text=normalized_text)
        payload = self._query_alignment(task_id=task_id)
        cues = self._extract_cues(payload)
        if not cues:
            raise RuntimeError("Volcengine subtitle alignment returned no subtitle cues.")
        return SubtitleAlignmentResult(
            provider=self.name,
            alignment_strategy="text_alignment",
            cues=cues,
            metadata={
                "task_id": task_id,
                "request_language": language,
                "duration": payload.get("duration"),
                "utterance_count": len(cues),
            },
        )

    def _submit_audio(self, *, audio_path: Path, subtitle_text: str) -> str:
        query = urllib.parse.urlencode(
            {
                "appid": self.app_id,
                "caption_type": "speech",
                "sta_punc_mode": str(self.punctuation_mode),
            }
        )
        url = f"{self.base_url.rstrip('/')}{self.ata_submit_path}?{query}"
        boundary = f"subtitle-boundary-{uuid.uuid4().hex}"
        body = self._build_submit_body(audio_path=audio_path, subtitle_text=subtitle_text, boundary=boundary)
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Authorization": f"Bearer; {self.access_token}",
            },
            method="POST",
        )
        payload = self._load_json_response(request, action_name="submit subtitle alignment task")
        code = _normalize_status_code(payload.get("code"))
        if code != 0:
            raise RuntimeError(
                f"Volcengine subtitle alignment submit failed: code={payload.get('code')} message={payload.get('message')}"
            )
        task_id = str(payload.get("id", "")).strip()
        if not task_id:
            raise RuntimeError(f"Volcengine subtitle alignment submit returned no task id: {payload}")
        return task_id

    def _query_alignment(self, *, task_id: str) -> dict[str, object]:
        query = urllib.parse.urlencode(
            {
                "appid": self.app_id,
                "id": task_id,
                "blocking": "1",
            }
        )
        url = f"{self.base_url.rstrip('/')}{self.ata_query_path}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer; {self.access_token}"},
            method="GET",
        )
        payload = self._load_json_response(request, action_name="query subtitle alignment result")
        code = _normalize_status_code(payload.get("code"))
        if code != 0:
            raise RuntimeError(
                f"Volcengine subtitle alignment query failed: code={payload.get('code')} message={payload.get('message')}"
            )
        return payload

    def _build_submit_body(self, *, audio_path: Path, subtitle_text: str, boundary: str) -> bytes:
        audio_bytes = audio_path.read_bytes()
        parts = [
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="data"; filename="{audio_path.name}"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode("utf-8")
            + audio_bytes
            + b"\r\n",
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="audio-text"\r\n\r\n'
                f"{subtitle_text}\r\n"
            ).encode("utf-8"),
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
        return b"".join(parts)

    def _load_json_response(self, request: urllib.request.Request, *, action_name: str) -> dict[str, object]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Volcengine speech subtitle {action_name} failed: status={exc.code} body={error_body}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                f"Volcengine speech subtitle {action_name} timed out after {self.timeout_seconds}s"
            ) from exc

    def _extract_cues(self, payload: dict[str, object]) -> list[SubtitleCue]:
        cues: list[SubtitleCue] = []
        utterances = payload.get("utterances")
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


def _normalize_status_code(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -1
