from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from video_workflow_service import WorkflowService, load_settings
from video_workflow_service.llm.base import LLMResponse
from video_workflow_service.llm.deepseek import DeepSeekLLMProvider
from video_workflow_service.llm.doubao_ark import DoubaoArkLLMProvider
from video_workflow_service.llm.model_registry import resolve_llm_model
from video_workflow_service.llm.provider_registry import resolve_llm_provider_name
from video_workflow_service.workflow.contracts import (
    DialogueAllocationInput,
    DialogueAllocationSceneInput,
)
from video_workflow_service.workflow.dialogue_allocate import allocate_dialogue_step
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


class LLMWorkflowTestCase(unittest.TestCase):
    def test_settings_default_llm_provider_falls_back_to_mock_without_key(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(tmp_dir)
            self.assertEqual(settings.llm_provider, "mock")

    def test_model_registry_supports_per_node_override(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                        "VIDEO_WORKFLOW_LLM_DEFAULT_MODEL=doubao-seed-2-0-lite-260215",
                        "VIDEO_WORKFLOW_LLM_CHARACTER_ANCHOR_MODEL=doubao-character-anchor-pro",
                        "VIDEO_WORKFLOW_LLM_SCENE_CHARACTER_CAST_MODEL=doubao-scene-cast-pro",
                        "VIDEO_WORKFLOW_LLM_STORY_PLAN_MODEL=doubao-story-plan-pro",
                        "VIDEO_WORKFLOW_LLM_SCENE_PLAN_MODEL=doubao-scene-plan-pro",
                        "VIDEO_WORKFLOW_LLM_DIALOGUE_ALLOCATE_MODEL=doubao-dialogue-pro",
                        "VIDEO_WORKFLOW_LLM_SCENE_PROMPT_RENDER_MODEL=doubao-render-pro",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            self.assertEqual(resolve_llm_model(settings, "character_anchor"), "doubao-character-anchor-pro")
            self.assertEqual(resolve_llm_model(settings, "scene_character_cast"), "doubao-scene-cast-pro")
            self.assertEqual(resolve_llm_model(settings, "prompt_optimize"), "doubao-seed-2-0-lite-260215")
            self.assertEqual(resolve_llm_model(settings, "story_plan"), "doubao-story-plan-pro")
            self.assertEqual(resolve_llm_model(settings, "scene_plan"), "doubao-scene-plan-pro")
            self.assertEqual(resolve_llm_model(settings, "dialogue_allocate"), "doubao-dialogue-pro")
            self.assertEqual(resolve_llm_model(settings, "scene_prompt_render"), "doubao-render-pro")

    def test_model_registry_uses_deepseek_default_model_for_deepseek_provider(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                        "DEEPSEEK_DEFAULT_MODEL=deepseek-chat",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            self.assertEqual(
                resolve_llm_model(settings, "prompt_optimize", provider_name="deepseek"),
                "deepseek-chat",
            )

    def test_provider_registry_supports_per_node_override(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=test_key",
                        "DEEPSEEK_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                        "VIDEO_WORKFLOW_LLM_PROMPT_OPTIMIZE_PROVIDER=deepseek",
                        "VIDEO_WORKFLOW_LLM_DIALOGUE_ALLOCATE_PROVIDER=deepseek",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            self.assertEqual(resolve_llm_provider_name(settings, "prompt_optimize"), "deepseek")
            self.assertEqual(resolve_llm_provider_name(settings, "dialogue_allocate"), "deepseek")
            self.assertEqual(resolve_llm_provider_name(settings, "scene_plan"), "doubao")

    def test_doubao_llm_provider_parses_chat_completion_response(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            provider = DoubaoArkLLMProvider(settings)
            captured_request: dict[str, object] = {}
            payload = {
                "id": "chatcmpl-123",
                "choices": [
                    {
                        "message": {
                            "content": '{"optimized_prompt":"ok","creative_intent":"intent","style_guardrails":[],"dialogue_lines":[],"planning_notes":"notes"}'
                        }
                    }
                ],
            }

            def fake_urlopen(request, timeout=0):
                captured_request["url"] = request.full_url
                captured_request["body"] = json.loads(request.data.decode("utf-8"))
                return _FakeResponse(payload)

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                response = provider.generate(
                    request=_FakeLLMRequest()
                )

            self.assertEqual(response.provider, "doubao")
            self.assertIn("/api/v3/chat/completions", str(captured_request["url"]))
            self.assertEqual(captured_request["body"]["response_format"]["type"], "json_object")
            self.assertIn("optimized_prompt", response.content)

    def test_doubao_llm_provider_retries_without_response_format_when_model_rejects_it(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            provider = DoubaoArkLLMProvider(settings)
            captured_bodies: list[dict[str, object]] = []
            payload = {
                "id": "chatcmpl-456",
                "choices": [
                    {
                        "message": {
                            "content": '{"optimized_prompt":"ok","creative_intent":"intent","style_guardrails":[],"dialogue_lines":[],"planning_notes":"notes"}'
                        }
                    }
                ],
            }

            def fake_urlopen(request, timeout=0):
                body = json.loads(request.data.decode("utf-8"))
                captured_bodies.append(body)
                if len(captured_bodies) == 1:
                    raise HTTPError(
                        request.full_url,
                        400,
                        "Bad Request",
                        hdrs=None,
                        fp=BytesIO(
                            b'{"error":{"code":"InvalidParameter","message":"The parameter `response_format.type` specified in the request are not valid: `json_object` is not supported by this model.","param":"response_format.type","type":""}}'
                        ),
                    )
                return _FakeResponse(payload)

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                response = provider.generate(
                    request=_FakeLLMRequest()
                )

            self.assertEqual(len(captured_bodies), 2)
            self.assertIn("response_format", captured_bodies[0])
            self.assertNotIn("response_format", captured_bodies[1])
            self.assertEqual(response.metadata["response_format_fallback"], True)
            self.assertEqual(response.metadata["initial_error"]["code"], "InvalidParameter")
            self.assertEqual(response.metadata["initial_error"]["param"], "response_format.type")
            self.assertIn("response_format.type", response.metadata["initial_error"]["message"])
            self.assertIn("optimized_prompt", response.content)

    def test_doubao_llm_provider_does_not_retry_unrelated_invalid_parameter(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            provider = DoubaoArkLLMProvider(settings)
            captured_bodies: list[dict[str, object]] = []

            def fake_urlopen(request, timeout=0):
                body = json.loads(request.data.decode("utf-8"))
                captured_bodies.append(body)
                raise HTTPError(
                    request.full_url,
                    400,
                    "Bad Request",
                    hdrs=None,
                    fp=BytesIO(
                        b'{"error":{"code":"InvalidParameter","message":"The parameter `size` specified in the request is not valid: image size must be at least 3686400 pixels.","param":"size","type":""}}'
                    ),
                )

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Doubao LLM request failed: status=400",
                ):
                    provider.generate(request=_FakeLLMRequest())

            self.assertEqual(len(captured_bodies), 1)

    def test_doubao_llm_provider_does_not_retry_when_only_message_mentions_response_format(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            provider = DoubaoArkLLMProvider(settings)
            captured_bodies: list[dict[str, object]] = []

            def fake_urlopen(request, timeout=0):
                body = json.loads(request.data.decode("utf-8"))
                captured_bodies.append(body)
                raise HTTPError(
                    request.full_url,
                    400,
                    "Bad Request",
                    hdrs=None,
                    fp=BytesIO(
                        b'{"error":{"code":"InvalidParameter","message":"The parameter `response_format.type` specified in the request are not valid: `json_object` is not supported by this model.","param":"","type":""}}'
                    ),
                )

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Doubao LLM request failed: status=400",
                ):
                    provider.generate(request=_FakeLLMRequest())

            self.assertEqual(len(captured_bodies), 1)

    def test_doubao_llm_provider_surfaces_step_name_on_timeout(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DOUBAO_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=doubao",
                        "VIDEO_WORKFLOW_LLM_TIMEOUT_SECONDS=3",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            provider = DoubaoArkLLMProvider(settings)

            with patch("urllib.request.urlopen", side_effect=TimeoutError("The read operation timed out")):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Doubao LLM request timed out after 3s during prompt_optimize",
                ):
                    provider.generate(request=_FakeLLMRequest())

    def test_deepseek_llm_provider_parses_chat_completion_response(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=deepseek",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            provider = DeepSeekLLMProvider(settings)
            captured_request: dict[str, object] = {}
            payload = {
                "id": "chatcmpl-ds-123",
                "choices": [
                    {
                        "message": {
                            "content": '{"optimized_prompt":"ok","creative_intent":"intent","style_guardrails":[],"dialogue_lines":[],"planning_notes":"notes"}'
                        }
                    }
                ],
            }

            def fake_urlopen(request, timeout=0):
                captured_request["url"] = request.full_url
                captured_request["body"] = json.loads(request.data.decode("utf-8"))
                return _FakeResponse(payload)

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                response = provider.generate(request=_FakeLLMRequest(model="deepseek-chat"))

            self.assertEqual(response.provider, "deepseek")
            self.assertEqual(captured_request["url"], "https://api.deepseek.com/chat/completions")
            self.assertEqual(captured_request["body"]["response_format"]["type"], "json_object")
            self.assertEqual(captured_request["body"]["model"], "deepseek-chat")
            self.assertIn("optimized_prompt", response.content)

    def test_deepseek_llm_provider_surfaces_step_name_on_timeout(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=deepseek",
                        "VIDEO_WORKFLOW_LLM_TIMEOUT_SECONDS=3",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            provider = DeepSeekLLMProvider(settings)

            with patch("urllib.request.urlopen", side_effect=TimeoutError("The read operation timed out")):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "DeepSeek LLM request timed out after 3s during prompt_optimize",
                ):
                    provider.generate(request=_FakeLLMRequest(model="deepseek-chat"))

    def test_deepseek_llm_provider_surfaces_empty_content(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=test_key",
                        "VIDEO_WORKFLOW_LLM_PROVIDER=deepseek",
                    ]
                ),
                encoding="utf-8",
            )
            settings = load_settings(root)
            provider = DeepSeekLLMProvider(settings)
            payload = {"id": "chatcmpl-ds-empty", "choices": [{"message": {"content": ""}}]}

            with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "DeepSeek LLM response contained no message content",
                ):
                    provider.generate(request=_FakeLLMRequest(model="deepseek-chat"))

    def test_dialogue_heavy_scene_plan_avoids_adjacent_duplicate_full_line(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            prompt = (
                'The woman picked up the flowers in her hand and said slowly: '
                '"They think I\'m just a healer\'s wife, would you believe me if I told you what I really am."'
            )
            project = service.create_project(
                title="Dialogue Split",
                prompt=prompt,
                target_duration_seconds=15,
                provider="mock",
                scene_count=2,
                workflow_mode="hitl",
            )

            optimized = service.optimize_prompt(project.project_id)
            planned = service.plan_scenes(project.project_id)

            self.assertTrue(optimized.optimized_prompt)
            self.assertEqual(len(planned.scenes), 2)
            spoken_texts = [scene.spoken_text for scene in planned.scenes if scene.spoken_text]
            self.assertGreaterEqual(len(spoken_texts), 1)
            if len(spoken_texts) == 2:
                self.assertNotEqual(spoken_texts[0], spoken_texts[1])
            self.assertTrue(planned.scenes[0].story_role)
            self.assertTrue(planned.scenes[0].story_purpose)
            self.assertTrue(planned.scenes[-1].story_advance_goal)
            self.assertEqual(planned.scenes[0].speech_mode, "none")
            self.assertTrue(planned.scenes[-1].spoken_text)
            for scene in planned.scenes:
                lowered_prompt = scene.prompt.lower()
                self.assertNotIn("viewers", lowered_prompt)
                self.assertNotIn("engagement", lowered_prompt)

            trace_path = settings.log_dir / project.project_id / "workflow_trace.jsonl"
            self.assertTrue(trace_path.exists())
            trace_lines = [
                json.loads(line)
                for line in trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            event_types = {line["event_type"] for line in trace_lines}
            self.assertIn("prompt_optimize_requested", event_types)
            self.assertIn("prompt_optimize_completed", event_types)
            self.assertIn("story_plan_requested", event_types)
            self.assertIn("story_plan_completed", event_types)
            self.assertIn("scene_plan_requested", event_types)
            self.assertIn("scene_plan_completed", event_types)
            self.assertIn("dialogue_allocate_requested", event_types)
            self.assertIn("dialogue_allocate_completed", event_types)
            self.assertIn("scene_prompt_render_requested", event_types)
            self.assertIn("scene_prompt_render_completed", event_types)
            dialogue_allocate_requested = next(
                line for line in trace_lines if line["event_type"] == "dialogue_allocate_requested"
            )
            payload = dialogue_allocate_requested["details"]["input_payload"]
            self.assertNotIn("raw_prompt", payload)
            self.assertNotIn("optimized_prompt", payload)
            self.assertNotIn("planning_notes", payload)
            self.assertNotIn("visual_goal", payload["scenes"][0])
            self.assertNotIn("continuity_notes", payload["scenes"][0])

    def test_dialogue_allocate_repairs_scene_contract_violation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            trace_logger = WorkflowTraceLogger(settings)
            provider = _SequenceLLMProvider(
                [
                    LLMResponse(
                        provider="deepseek",
                        model="deepseek-chat",
                        content=json.dumps(
                            {
                                "allocations": [
                                    {
                                        "scene_id": "scene-01",
                                        "spoken_text": "",
                                        "speech_mode": "none",
                                        "delivery_notes": "silent opening",
                                    },
                                    {
                                        "scene_id": "scene-02",
                                        "spoken_text": "（猫轻声喵叫）",
                                        "speech_mode": "once",
                                        "delivery_notes": "cat sound",
                                    },
                                    {
                                        "scene_id": "scene-02",
                                        "spoken_text": "（狗友好地吠叫）",
                                        "speech_mode": "once",
                                        "delivery_notes": "dog sound",
                                    },
                                ],
                                "planning_notes": "invalid duplicate scene split",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                    LLMResponse(
                        provider="deepseek",
                        model="deepseek-chat",
                        content=json.dumps(
                            {
                                "allocations": [
                                    {
                                        "scene_id": "scene-01",
                                        "spoken_text": "",
                                        "speech_mode": "none",
                                        "delivery_notes": "silent opening",
                                    },
                                    {
                                        "scene_id": "scene-02",
                                        "spoken_text": "（猫轻声喵叫） （狗友好地吠叫）",
                                        "speech_mode": "once",
                                        "delivery_notes": "cat sound first, then dog response",
                                    },
                                ],
                                "planning_notes": "repaired",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ]
            )

            with (
                patch("video_workflow_service.workflow.llm_node.resolve_llm_provider_name", return_value="deepseek"),
                patch("video_workflow_service.workflow.llm_node.resolve_llm_model", return_value="deepseek-chat"),
                patch("video_workflow_service.workflow.llm_node.get_llm_provider", return_value=provider),
            ):
                output = allocate_dialogue_step(
                    DialogueAllocationInput(
                        raw_prompt="一个两场景的动物重逢预告片。",
                        optimized_prompt="一个两场景的动物重逢预告片。",
                        dialogue_lines=["（猫轻声喵叫）", "（狗友好地吠叫）"],
                        input_language="zh",
                        dialogue_language="zh",
                        audio_language="zh",
                        creative_intent="温馨动物预告",
                        overall_story_arc="猫狗先相遇，再一起行动。",
                        dialogue_strategy="第二场包含两段短促动物声音。",
                        scenes=[
                            DialogueAllocationSceneInput(
                                scene_id="scene-01",
                                scene_index=1,
                                title="开场",
                                narrative="静默铺垫",
                                visual_goal="固定镜头",
                                continuity_notes="保持角色一致",
                                duration_seconds=5,
                                story_role="Setup",
                                story_purpose="建立氛围",
                                story_advance_goal="铺垫",
                                pacing_intent="slow",
                                information_load="light",
                                speech_expectation="silent",
                            ),
                            DialogueAllocationSceneInput(
                                scene_id="scene-02",
                                scene_index=2,
                                title="相遇",
                                narrative="猫和狗相遇并互动",
                                visual_goal="中景互动",
                                continuity_notes="保持角色一致",
                                duration_seconds=5,
                                story_role="Meet",
                                story_purpose="建立关系",
                                story_advance_goal="推进",
                                pacing_intent="warm",
                                information_load="medium",
                                speech_expectation="partial",
                                depends_on_scene="scene-01",
                            ),
                        ],
                    ),
                    settings=settings,
                    trace_logger=trace_logger,
                    project_id="repair-contract-project",
                )

            self.assertEqual(len(provider.requests), 2)
            self.assertEqual([item.scene_id for item in output.allocations], ["scene-01", "scene-02"])
            self.assertTrue(output.provider_metadata["repair_attempted"])
            self.assertIn("exactly 2 objects", provider.requests[1].messages[1].content)
            self.assertIn("scene-01, scene-02", provider.requests[1].messages[1].content)

    def test_dialogue_allocate_does_not_retry_non_contract_validation_error(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            trace_logger = WorkflowTraceLogger(settings)
            provider = _SequenceLLMProvider(
                [
                    LLMResponse(
                        provider="deepseek",
                        model="deepseek-chat",
                        content=json.dumps(
                            {
                                "allocations": [
                                    {
                                        "spoken_text": "",
                                        "speech_mode": "none",
                                        "delivery_notes": "missing scene id",
                                    },
                                    {
                                        "scene_id": "scene-02",
                                        "spoken_text": "",
                                        "speech_mode": "none",
                                        "delivery_notes": "ok",
                                    },
                                ],
                                "planning_notes": "invalid missing scene id",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ]
            )

            with (
                patch("video_workflow_service.workflow.llm_node.resolve_llm_provider_name", return_value="deepseek"),
                patch("video_workflow_service.workflow.llm_node.resolve_llm_model", return_value="deepseek-chat"),
                patch("video_workflow_service.workflow.llm_node.get_llm_provider", return_value=provider),
            ):
                with self.assertRaisesRegex(ValueError, "Dialogue allocation output missing scene_id"):
                    allocate_dialogue_step(
                        DialogueAllocationInput(
                            raw_prompt="一个两场景的动物重逢预告片。",
                            optimized_prompt="一个两场景的动物重逢预告片。",
                            dialogue_lines=[],
                            input_language="zh",
                            dialogue_language="zh",
                            audio_language="zh",
                            scenes=[
                                DialogueAllocationSceneInput(
                                    scene_id="scene-01",
                                    scene_index=1,
                                    title="开场",
                                    narrative="静默铺垫",
                                    visual_goal="固定镜头",
                                    continuity_notes="保持角色一致",
                                    duration_seconds=5,
                                ),
                                DialogueAllocationSceneInput(
                                    scene_id="scene-02",
                                    scene_index=2,
                                    title="相遇",
                                    narrative="猫和狗相遇并互动",
                                    visual_goal="中景互动",
                                    continuity_notes="保持角色一致",
                                    duration_seconds=5,
                                ),
                            ],
                        ),
                        settings=settings,
                        trace_logger=trace_logger,
                        project_id="non-contract-project",
                    )

            self.assertEqual(len(provider.requests), 1)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _FakeLLMRequest:
    step_name = "prompt_optimize"
    messages = []
    input_payload = {}
    response_format = {"type": "json_object"}
    temperature = 0.2
    metadata = {}

    def __init__(self, model: str = "doubao-seed-2-0-lite-260215"):
        self.model = model


class _SequenceLLMProvider:
    name = "sequence"

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("No more fake LLM responses configured")
        return self._responses.pop(0)


if __name__ == "__main__":
    unittest.main()
