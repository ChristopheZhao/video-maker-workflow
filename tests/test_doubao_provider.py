from __future__ import annotations

import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from video_workflow_service.infrastructure.config import load_settings
from video_workflow_service.providers.content_model import build_video_generation_content_items
from video_workflow_service.providers.doubao import DoubaoVideoProvider
from video_workflow_service.workflow.contracts import SceneGenerationInput


class DoubaoProviderTestCase(unittest.TestCase):
    def test_auto_generated_first_frame_uses_first_frame_request_field(self) -> None:
        contract = SceneGenerationInput(
            project_id="prj_test",
            provider="doubao",
            scene_id="scene-01",
            scene_index=1,
            prompt="A generated opening still continuation.",
            duration_seconds=5,
            aspect_ratio="16:9",
            first_frame_source="auto_generate",
            first_frame_image="data:image/png;base64,Zmlyc3Q=",
        )

        request = contract.to_provider_request()

        self.assertEqual(request.first_frame_image, "data:image/png;base64,Zmlyc3Q=")
        self.assertIsNone(request.image_url)

        with TemporaryDirectory() as tmp_dir:
            provider = DoubaoVideoProvider(load_settings(tmp_dir))
            items = provider._build_content_items("prompt", request)
            content = provider._serialize_content_items(items)

        self.assertEqual(len(content), 2)
        self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64,Zmlyc3Q=")
        self.assertEqual(content[1]["role"], "first_frame")

    def test_upload_first_frame_uses_first_frame_request_field(self) -> None:
        contract = SceneGenerationInput(
            project_id="prj_test",
            provider="doubao",
            scene_id="scene-01",
            scene_index=1,
            prompt="A close-up reveal.",
            duration_seconds=5,
            aspect_ratio="16:9",
            first_frame_source="upload",
            first_frame_image="data:image/png;base64,Zmlyc3Q=",
        )

        request = contract.to_provider_request()

        self.assertEqual(request.first_frame_image, "data:image/png;base64,Zmlyc3Q=")
        self.assertIsNone(request.image_url)

        with TemporaryDirectory() as tmp_dir:
            provider = DoubaoVideoProvider(load_settings(tmp_dir))
            items = provider._build_content_items("prompt", request)
            content = provider._serialize_content_items(items)

        self.assertEqual(len(content), 2)
        self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64,Zmlyc3Q=")
        self.assertEqual(content[1]["role"], "first_frame")

    def test_first_last_frame_pair_emits_explicit_roles(self) -> None:
        contract = SceneGenerationInput(
            project_id="prj_test",
            provider="doubao",
            scene_id="scene-01",
            scene_index=1,
            prompt="A start and end frame transition.",
            duration_seconds=5,
            aspect_ratio="16:9",
            first_frame_source="upload",
            first_frame_image="data:image/png;base64,Zmlyc3Q=",
        )
        request = contract.to_provider_request()
        request.last_frame_image = "data:image/png;base64,bGFzdA=="

        with TemporaryDirectory() as tmp_dir:
            provider = DoubaoVideoProvider(load_settings(tmp_dir))
            items = provider._build_content_items("prompt", request)
            content = provider._serialize_content_items(items)

        self.assertEqual([item.kind for item in items], ["text", "first_frame", "last_frame"])
        self.assertEqual(content[1]["role"], "first_frame")
        self.assertEqual(content[2]["role"], "last_frame")

    def test_poll_task_accepts_nested_completed_status_and_video_result(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            provider = DoubaoVideoProvider(load_settings(tmp_dir))
            provider.poll_attempts = 1
            provider.poll_interval_seconds = 0
            payload = {
                "data": {
                    "status": "COMPLETED",
                    "video_result": [
                        {"url": "https://example.test/video.mp4"},
                    ],
                }
            }

            with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
                result = provider._poll_task("task-123")

        self.assertEqual(result["data"]["status"], "COMPLETED")
        self.assertEqual(provider._extract_task_status(result), "completed")
        self.assertEqual(provider._extract_video_url(result), "https://example.test/video.mp4")

    def test_content_item_builder_keeps_business_semantics(self) -> None:
        contract = SceneGenerationInput(
            project_id="prj_test",
            provider="doubao",
            scene_id="scene-02",
            scene_index=2,
            prompt="Continuation shot.",
            duration_seconds=5,
            aspect_ratio="16:9",
            first_frame_source="continuity",
            first_frame_image="data:image/png;base64,Y29udGludWl0eQ==",
        )

        items = build_video_generation_content_items(
            prompt_text="Continuation shot --dur 5 --rt 16:9 --rs 720p",
            request=contract.to_provider_request(),
        )

        self.assertEqual([item.kind for item in items], ["text", "first_frame"])

    def test_reference_image_stays_plain_image_without_role(self) -> None:
        contract = SceneGenerationInput(
            project_id="prj_test",
            provider="doubao",
            scene_id="scene-03",
            scene_index=3,
            prompt="Reference-driven shot.",
            duration_seconds=5,
            aspect_ratio="16:9",
            reference_image="data:image/png;base64,cmVm",
        )

        request = contract.to_provider_request()

        with TemporaryDirectory() as tmp_dir:
            provider = DoubaoVideoProvider(load_settings(tmp_dir))
            items = provider._build_content_items("prompt", request)
            content = provider._serialize_content_items(items)

        self.assertEqual([item.kind for item in items], ["text", "image"])
        self.assertNotIn("role", content[1])

    def test_generate_video_records_request_summary_for_uploaded_first_frame(self) -> None:
        contract = SceneGenerationInput(
            project_id="prj_test",
            provider="doubao",
            scene_id="scene-04",
            scene_index=1,
            prompt="A locked opening frame.",
            duration_seconds=5,
            aspect_ratio="16:9",
            first_frame_source="upload",
            first_frame_image="data:image/png;base64,Zmlyc3Q=",
        )
        request = contract.to_provider_request()

        with TemporaryDirectory() as tmp_dir:
            provider = DoubaoVideoProvider(load_settings(tmp_dir))
            provider.api_key = "test-key"

            def _fake_download(_url: str, output_path) -> None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"fake")

            with patch.object(provider, "_create_task", return_value="task-123"), patch.object(
                provider,
                "_poll_task",
                return_value={
                    "status": "succeeded",
                    "video_url": "https://example.test/video.mp4",
                    "last_frame_url": "https://example.test/last.png",
                    "duration": 5,
                    "ratio": "16:9",
                    "resolution": "720p",
                },
            ), patch.object(provider, "_download_file", side_effect=_fake_download):
                result = provider.generate_video(request)

        summary = result.metadata["request_summary"]
        self.assertEqual(summary["generation_mode"], "image_to_video")
        self.assertTrue(summary["has_first_frame"])
        self.assertFalse(summary["has_image_url"])
        self.assertEqual(summary["content_item_kinds"], ["text", "first_frame"])


class _FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
