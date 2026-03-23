from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from video_workflow_service.infrastructure.config import load_settings
from video_workflow_service.subtitles.volcengine_asr import VolcengineSpeechAsrClient


class SubtitleClientTestCase(unittest.TestCase):
    def test_volcengine_asr_client_recognizes_audio_with_utterance_timestamps(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "VOLCENGINE_SPEECH_APP_ID=test_app",
                        "VOLCENGINE_SPEECH_ACCESS_TOKEN=test_token",
                        "VOLCENGINE_SPEECH_BASE_URL=https://openspeech.bytedance.com",
                        "VOLCENGINE_SPEECH_ASR_SUBMIT_PATH=/api/v3/auc/bigmodel/recognize/flash",
                        "VOLCENGINE_SPEECH_ASR_RESOURCE_ID=volc.bigasr.auc_turbo",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            client = VolcengineSpeechAsrClient(settings)
            audio_path = root / "sample.wav"
            audio_path.write_bytes(b"RIFFfake-audio-data")
            captured_requests: list[dict[str, object]] = []

            def fake_urlopen(request, timeout=0):
                payload = json.loads(request.data.decode("utf-8")) if request.data else {}
                captured_requests.append(
                    {
                        "url": request.full_url,
                        "body": payload,
                        "resource_id": request.headers.get("X-api-resource-id"),
                    }
                )
                return _FakeResponse(
                    payload={
                        "result": {
                            "text": "他终于看见了真正的草原。",
                            "utterances": [
                                {"text": "他终于看见了真正的草原。", "start_time": 0, "end_time": 1200}
                            ],
                        }
                    },
                    headers={"X-Api-Status-Code": "20000000"},
                )

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = client.recognize_audio(
                    audio_path=audio_path,
                    language="zh",
                )

            self.assertEqual(result.provider, "volcengine_speech_asr")
            self.assertEqual(result.alignment_strategy, "asr_recognition")
            self.assertEqual(len(result.cues), 1)
            self.assertEqual(result.cues[0].start_time_ms, 0)
            self.assertEqual(result.cues[0].end_time_ms, 1200)
            self.assertEqual(result.cues[0].text, "他终于看见了真正的草原。")
            self.assertEqual(len(captured_requests), 1)
            self.assertTrue(captured_requests[0]["url"].endswith("/recognize/flash"))
            self.assertIn("data", captured_requests[0]["body"]["audio"])
            self.assertEqual(captured_requests[0]["body"]["request"]["show_utterances"], True)
            self.assertEqual(captured_requests[0]["resource_id"], "volc.bigasr.auc_turbo")


class _FakeResponse:
    def __init__(self, payload: dict[str, object], headers: dict[str, str]):
        self._payload = payload
        self.headers = headers

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
