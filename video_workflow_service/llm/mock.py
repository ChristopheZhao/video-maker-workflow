from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re

from .base import LLMProvider, LLMRequest, LLMResponse


@dataclass(slots=True)
class _ScenePlanDraft:
    title: str
    narrative: str
    visual_goal: str
    spoken_text: str
    speech_mode: str
    continuity_notes: str


class MockLLMProvider(LLMProvider):
    name = "mock"

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.step_name == "prompt_optimize":
            payload = self._build_prompt_optimize_payload(request.input_payload)
        elif request.step_name == "character_anchor":
            payload = self._build_character_anchor_payload(request.input_payload)
        elif request.step_name == "scene_character_cast":
            payload = self._build_scene_character_cast_payload(request.input_payload)
        elif request.step_name == "story_plan":
            payload = self._build_story_plan_payload(request.input_payload)
        elif request.step_name == "scene_plan":
            payload = self._build_scene_plan_payload(request.input_payload)
        elif request.step_name == "dialogue_allocate":
            payload = self._build_dialogue_allocate_payload(request.input_payload)
        elif request.step_name == "first_frame_analyze":
            payload = self._build_first_frame_analyze_payload(request.input_payload)
        elif request.step_name == "scene_prompt_render":
            payload = self._build_scene_prompt_render_payload(request.input_payload)
        elif request.step_name == "scene_prompt_revise":
            payload = self._build_scene_prompt_revise_payload(request.input_payload)
        else:
            raise ValueError(f"Unsupported mock llm step: {request.step_name}")
        return LLMResponse(
            provider=self.name,
            model=request.model,
            content=json.dumps(payload, ensure_ascii=False),
            metadata={"step_name": request.step_name},
        )

    def _build_prompt_optimize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_prompt = str(payload.get("raw_prompt", "")).strip()
        normalized = re.sub(r"\s+", " ", raw_prompt)
        dialogue_lines = _extract_dialogue_lines(raw_prompt)
        creative_intent = "Cinematic narrative with stable protagonist continuity."
        style_guardrails = [
            "Keep character identity stable across scenes.",
            "Avoid repeating the same full spoken line across adjacent scenes.",
            "Prefer visual progression before dialogue repetition.",
        ]
        planning_notes = (
            "Allocate dialogue deliberately across scenes and reserve full-line delivery for the most revealing beat."
        )
        optimized_prompt = (
            f"{normalized}. Preserve narrative continuity, stage visual escalation, and plan dialogue delivery scene by scene."
        )
        return {
            "optimized_prompt": optimized_prompt,
            "creative_intent": creative_intent,
            "style_guardrails": style_guardrails,
            "dialogue_lines": dialogue_lines,
            "planning_notes": planning_notes,
        }

    def _build_character_anchor_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_prompt = str(payload.get("raw_prompt", "")).strip()
        candidates = _extract_character_candidates(raw_prompt)
        characters: list[dict[str, str]] = []
        for index, candidate in enumerate(candidates[:3], start=1):
            display_name = candidate["display_name"]
            story_role = candidate["story_role"]
            visual_description = candidate["visual_description"]
            characters.append(
                {
                    "character_id": f"char-{index:02d}",
                    "display_name": display_name,
                    "story_role": story_role,
                    "visual_description": visual_description,
                    "reference_prompt": (
                        f"Portrait reference of {display_name}. {visual_description}. Clean neutral background, stable identity features."
                    ),
                }
            )
        return {"characters": characters}

    def _build_story_plan_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scene_count = max(1, int(payload.get("scene_count", 1)))
        dialogue_lines = [str(item).strip() for item in payload.get("dialogue_lines", []) if str(item).strip()]
        approximate_durations = [
            int(item) for item in payload.get("approximate_scene_durations", []) if str(item).strip()
        ] or _distribute_duration(max(5, int(payload.get("target_duration_seconds", 5))), scene_count)
        scene_roles: list[dict[str, str]] = []
        for index in range(scene_count):
            is_first = index == 0
            is_last = index == scene_count - 1
            role_label = "setup"
            narrative_purpose = "Establish the protagonist and immediate dramatic context."
            story_advance_goal = "Set up the hidden tension beneath the ordinary surface."
            pacing_intent = "Measured opening beat with room for visual orientation."
            information_load = "medium"
            speech_expectation = "silent"
            if is_last:
                role_label = "reveal"
                narrative_purpose = "Deliver the main reveal or decisive turn in the scene sequence."
                story_advance_goal = "Advance the story through the core revelation."
                pacing_intent = "Focused payoff beat with concentrated emotional delivery."
                information_load = "high"
                speech_expectation = "main spoken reveal" if dialogue_lines else "silent reveal"
            elif not is_first:
                role_label = "develop"
                narrative_purpose = "Bridge the setup into the reveal with visible progression."
                story_advance_goal = "Move the audience from tension toward revelation."
                pacing_intent = "Escalate slightly from the previous beat without resolving everything."
                information_load = "medium"
                speech_expectation = "partial speech or silence"
            scene_roles.append(
                {
                    "scene_id": f"scene-{index + 1:02d}",
                    "role_label": role_label,
                    "narrative_purpose": narrative_purpose,
                    "story_advance_goal": story_advance_goal,
                    "pacing_intent": pacing_intent,
                    "information_load": information_load,
                    "speech_expectation": speech_expectation,
                    "duration_seconds": str(approximate_durations[min(index, len(approximate_durations) - 1)]),
                }
            )
        return {
            "overall_story_arc": "Move from apparent normalcy into a controlled reveal with scene-by-scene escalation.",
            "dialogue_strategy": (
                "Keep dialogue attached to the strongest reveal beat and allow setup scenes to remain silent when that creates better progression."
            ),
            "scene_roles": scene_roles,
            "planning_notes": "Each scene should carry a distinct story function rather than serving as a visual leftover.",
        }

    def _build_scene_character_cast_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        character_cards = [
            item for item in payload.get("character_cards", [])
            if isinstance(item, dict)
        ]
        scenes = [item for item in payload.get("scenes", []) if isinstance(item, dict)]
        output_scenes: list[dict[str, Any]] = []
        for scene in scenes:
            scene_text = " ".join(
                str(scene.get(field, "")).strip()
                for field in (
                    "title",
                    "narrative",
                    "visual_goal",
                    "continuity_notes",
                    "story_role",
                    "story_purpose",
                    "story_advance_goal",
                )
            ).lower()
            participating: list[dict[str, Any]] = []
            for card in character_cards:
                display_name = str(card.get("display_name", "")).strip()
                if display_name and display_name.lower() in scene_text:
                    participating.append(card)
            output_scenes.append(
                {
                    "scene_id": str(scene.get("scene_id", "")),
                    "participating_character_ids": [
                        str(card.get("character_id", "")).strip()
                        for card in participating
                        if str(card.get("character_id", "")).strip()
                    ],
                    "primary_character_id": (
                        str(participating[0].get("character_id", "")).strip() if participating else None
                    ),
                    "character_presence_notes": (
                        "Scene features " + ", ".join(
                            str(card.get("display_name", "")).strip()
                            for card in participating
                            if str(card.get("display_name", "")).strip()
                        )
                        if participating
                        else ""
                    ),
                }
            )
        return {"scenes": output_scenes}

    def _build_scene_plan_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        optimized_prompt = str(payload.get("optimized_prompt", "")).strip()
        scene_count = max(1, int(payload.get("scene_count", 1)))
        target_duration_seconds = max(5, int(payload.get("target_duration_seconds", 5)))
        approximate_durations = _distribute_duration(target_duration_seconds, scene_count)
        story_plan_roles = [item for item in payload.get("story_plan_scene_roles", []) if isinstance(item, dict)]
        sentence_candidates = [
            segment.strip()
            for segment in re.split(r"[。！？!?;\n]+", optimized_prompt)
            if segment.strip()
        ] or [optimized_prompt or "Create a short visual sequence."]
        scenes: list[dict[str, Any]] = []
        for index in range(scene_count):
            base_focus = sentence_candidates[min(index, len(sentence_candidates) - 1)]
            role = story_plan_roles[index] if index < len(story_plan_roles) else {}
            role_label = str(role.get("role_label", "")).strip().lower()
            narrative_purpose = str(role.get("narrative_purpose", "")).strip()
            story_advance_goal = str(role.get("story_advance_goal", "")).strip()
            pacing_intent = str(role.get("pacing_intent", "")).strip()
            visual_goal = "Establish emotional setup and camera movement."
            if role_label == "develop":
                visual_goal = "Show visible progression with slightly tighter framing and stronger expression."
            elif role_label == "reveal":
                visual_goal = "Land the reveal beat and resolve the spoken moment with a decisive close-up."
            scenes.append(
                {
                    "title": f"Scene {index + 1}",
                    "narrative": " ".join(
                        part for part in [base_focus, narrative_purpose, story_advance_goal] if part
                    ).strip(),
                    "visual_goal": visual_goal,
                    "continuity_notes": " ".join(
                        part
                        for part in [
                            "Maintain costume, props, and camera direction continuity.",
                            pacing_intent,
                        ]
                        if part
                    ).strip(),
                    "duration_seconds": approximate_durations[index],
                }
            )
        return {"scenes": scenes}

    def _build_dialogue_allocate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scenes = [item for item in payload.get("scenes", []) if isinstance(item, dict)]
        dialogue_lines = [str(item).strip() for item in payload.get("dialogue_lines", []) if str(item).strip()]
        allocations: list[dict[str, str]] = []
        dialogue_segments = _allocate_dialogue_segments(dialogue_lines, len(scenes))
        for index, scene in enumerate(scenes):
            speech_expectation = str(scene.get("speech_expectation", "")).strip().lower()
            spoken_text = dialogue_segments[index] if index < len(dialogue_segments) else ""
            if "silent" in speech_expectation and index < len(scenes) - 1:
                spoken_text = ""
            elif "main spoken reveal" in speech_expectation and dialogue_lines:
                spoken_text = dialogue_lines[0]
            speech_mode = "none"
            delivery_notes = ""
            if spoken_text:
                speech_mode = "split" if len(dialogue_lines) <= 1 and len(scenes) > 1 and index < len(scenes) - 1 else "once"
                if speech_mode == "split":
                    delivery_notes = "Deliver this fragment as a restrained partial reveal tied to the ongoing visual beat."
                else:
                    delivery_notes = "Deliver the line once with calm, deliberate emphasis that matches the reveal beat."
            allocations.append(
                {
                    "scene_id": str(scene.get("scene_id", "")),
                    "spoken_text": spoken_text,
                    "speech_mode": speech_mode,
                    "delivery_notes": delivery_notes,
                }
            )
        return {
            "allocations": allocations,
            "planning_notes": "Keep dialogue attached to the strongest reveal beat and allow silent setup scenes when useful.",
        }

    def _build_scene_prompt_render_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        from video_workflow_service.workflow.scene_prompt_render import render_scene_generation_prompt

        return {
            "rendered_prompt": render_scene_generation_prompt(
                title=str(payload.get("title", "")),
                working_prompt=str(payload.get("working_prompt", "")),
                narrative=str(payload.get("narrative", "")),
                visual_goal=str(payload.get("visual_goal", "")),
                spoken_text=str(payload.get("spoken_text", "")),
                speech_mode=str(payload.get("speech_mode", "none")),
                delivery_notes=str(payload.get("delivery_notes", "")),
                continuity_notes=str(payload.get("continuity_notes", "")),
                input_language=str(payload.get("input_language", "")),
                dialogue_language=str(payload.get("dialogue_language", "")),
                audio_language=str(payload.get("audio_language", "")),
                first_frame_source=str(payload.get("first_frame_source", "auto_generate")),
                first_frame_prompt=str(payload.get("first_frame_prompt", "")),
                first_frame_analysis=dict(payload.get("first_frame_analysis") or {}),
            )
        }

    def _build_first_frame_analyze_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        narrative = str(payload.get("narrative", "")).lower()
        visual_goal = str(payload.get("visual_goal", "")).lower()
        mentions_flowers = "flower" in narrative or "flower" in visual_goal
        return {
            "subject_presence": "The protagonist is already fully visible on screen.",
            "subject_pose": "She faces the camera with a steady upper-body pose and minimal motion at the start.",
            "hand_prop_state": (
                "She is already holding the flower bundle in both hands."
                if mentions_flowers
                else "Her hands are already in frame with the current prop state established."
            ),
            "prop_description": "A small dried flower bundle is already in her hands." if mentions_flowers else "",
            "framing": "A stable medium close-up portrait framing is already established.",
            "setting": "An interior rustic room setting is already established.",
            "lighting": "Soft warm ambient light is already established across the frame.",
            "wardrobe": "The same high-collar period blouse and dark skirt must remain unchanged.",
            "continuation_constraints": (
                "Do not restage the opening action. Continue from the existing pose, framing, and prop state."
            ),
            "analysis_notes": "Treat the provided still as the opening truth for continuation."
        }

    def _build_scene_prompt_revise_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        feedback = str(payload.get("feedback", "")).strip()
        requested_scope = str(payload.get("requested_scope", "prompt_only")).strip().lower()
        current_prompt = str(payload.get("current_prompt", "")).strip()
        first_frame_prompt = str(payload.get("first_frame_prompt", "")).strip()
        first_frame_source = str(payload.get("first_frame_source", "")).strip().lower()
        input_language = str(payload.get("input_language", "")).strip().lower()
        if requested_scope == "prompt_only" and first_frame_source == "continuity" and _feedback_targets_start_state(feedback):
            rejection_reason = (
                "The feedback changes the inherited scene start state and cannot be applied through prompt-only revision."
            )
            if input_language == "zh":
                rejection_reason = "该反馈会改变继承来的场景起始状态，不能仅通过提示词改写完成。"
            return {
                "outcome": "requires_start_state_edit",
                "revised_prompt": "",
                "revised_first_frame_prompt": "",
                "change_summary": "",
                "rejection_reason": rejection_reason,
            }

        revised_prompt = current_prompt
        if feedback:
            revised_prompt = (
                f"{current_prompt} 根据用户反馈调整：{feedback}"
                if input_language == "zh"
                else f"{current_prompt} Revised to reflect user feedback: {feedback}"
            ).strip()
        revised_first_frame_prompt = ""
        if requested_scope == "opening_still_and_prompt":
            revised_first_frame_prompt = (
                f"{first_frame_prompt} 开场修正：{feedback}"
                if input_language == "zh"
                else f"{first_frame_prompt} Opening-state revision: {feedback}"
            ).strip()
        change_summary = (
            f"已根据反馈调整场景提示词：{feedback}"
            if input_language == "zh"
            else f"Adjusted the scene prompt from user feedback: {feedback}"
        )
        return {
            "outcome": "revised",
            "revised_prompt": revised_prompt,
            "revised_first_frame_prompt": revised_first_frame_prompt,
            "change_summary": change_summary,
            "rejection_reason": "",
        }


def _extract_dialogue_lines(prompt: str) -> list[str]:
    candidates = re.findall(r"[\"“”]([^\"“”]{2,})[\"“”]", prompt)
    dialogue_lines = [candidate.strip() for candidate in candidates if candidate.strip()]
    if dialogue_lines:
        return dialogue_lines
    if ":" in prompt:
        tail = prompt.split(":", 1)[1].strip()
        if tail:
            return [tail]
    return []


def _distribute_duration(total_seconds: int, scene_count: int) -> list[int]:
    base = total_seconds // scene_count
    remainder = total_seconds % scene_count
    durations = [base for _ in range(scene_count)]
    for index in range(remainder):
        durations[index] += 1
    return [max(5, value) for value in durations]


def _allocate_dialogue_segments(dialogue_lines: list[str], scene_count: int) -> list[str]:
    if scene_count <= 0:
        return []
    if not dialogue_lines:
        return [""] * scene_count
    if len(dialogue_lines) >= scene_count:
        return dialogue_lines[:scene_count]
    if len(dialogue_lines) == 1 and scene_count > 1:
        result = [""] * scene_count
        result[-1] = dialogue_lines[0]
        return result
    result = [""] * scene_count
    for idx, line in enumerate(dialogue_lines):
        if idx < scene_count:
            result[idx] = line
    return result


def _feedback_targets_start_state(feedback: str) -> bool:
    normalized = feedback.strip().casefold()
    if not normalized:
        return False
    keywords = (
        "门不应该开着",
        "开场不要",
        "不要先",
        "不应该已经",
        "不要拿着",
        "opening should not",
        "should not already",
        "door should not be open",
        "at the start",
    )
    return any(keyword in normalized for keyword in keywords)


def _extract_character_candidates(prompt: str) -> list[dict[str, str]]:
    capitalized = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", prompt)
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    ignored = {"a", "an", "the"}
    for name in capitalized:
        normalized = name.strip()
        if len(normalized) <= 1 or normalized.casefold() in ignored:
            continue
        if normalized.casefold() in seen:
            continue
        seen.add(normalized.casefold())
        candidates.append(
            {
                "display_name": normalized,
                "story_role": "major character",
                "visual_description": "Recurring protagonist with stable period or cinematic styling drawn from the project prompt.",
            }
        )
    lowered = prompt.lower()
    if not candidates:
        if any(token in lowered for token in ("woman", "heroine", "girl", "她", "女人", "少女")):
            candidates.append(
                {
                    "display_name": "Lead Woman",
                    "story_role": "protagonist",
                    "visual_description": "Recurring female lead with stable wardrobe, hairstyle, and carried props derived from the prompt.",
                }
            )
        elif any(token in lowered for token in ("man", "hero", "boy", "他", "男人", "少年")):
            candidates.append(
                {
                    "display_name": "Lead Man",
                    "story_role": "protagonist",
                    "visual_description": "Recurring male lead with stable wardrobe, hairstyle, and silhouette derived from the prompt.",
                }
            )
    return candidates[:3]
