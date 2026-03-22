from __future__ import annotations

import json
from typing import Any


CHARACTER_ANCHOR_TEMPLATE_VERSION = "character_anchor.v1"
SCENE_CHARACTER_CAST_TEMPLATE_VERSION = "scene_character_cast.v1"
PROMPT_OPTIMIZE_TEMPLATE_VERSION = "prompt_optimize.v1"
STORY_PLAN_TEMPLATE_VERSION = "story_plan.v1"
SCENE_PLAN_TEMPLATE_VERSION = "scene_plan.v1"
DIALOGUE_ALLOCATE_TEMPLATE_VERSION = "dialogue_allocate.v1"
FIRST_FRAME_ANALYZE_TEMPLATE_VERSION = "first_frame_analyze.v1"
SCENE_PROMPT_RENDER_TEMPLATE_VERSION = "scene_prompt_render.v1"


def build_character_anchor_messages(input_payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "You extract major recurring character anchors for short-video workflows. "
        "Return only valid JSON. "
        "Identify at most three major characters who need stable visual identity across scenes. "
        "If the prompt does not clearly contain recurring people, return an empty character list. "
        "Use project_guidance only as correction context for language and opening-truth hints. "
        "Do not confuse a scene opening still with a reusable character anchor. "
        "When scene1_first_frame_source is upload and an opening image exists, you may treat it as a hint for the first character anchor, but you must still output a reusable character identity card rather than scene composition notes."
    )
    user_prompt = (
        "Create structured character-anchor candidates for the following project input.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "characters": [\n'
        "    {\n"
        '      "character_id": string,\n'
        '      "display_name": string,\n'
        '      "story_role": string,\n'
        '      "visual_description": string,\n'
        '      "reference_prompt": string\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Return at most three characters.\n"
        "- Favor recurring protagonists, companions, and antagonists over unnamed background extras.\n"
        "- Keep visual_description focused on stable identity traits, wardrobe direction, age, hair, posture, and notable carried items.\n"
        "- Keep reference_prompt suitable for generating a clean portrait-style character reference image.\n"
        "- Preserve the project's detected language for names and descriptive phrasing when appropriate.\n\n"
        "Project input:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_scene_character_cast_messages(input_payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "You assign project-level character anchors to scene-level participation. "
        "Return only valid JSON. "
        "Do not create new characters. "
        "Use only the anchored character_ids provided in character_cards. "
        "A scene may legitimately contain none of the anchored characters. "
        "Only include a character when the scene text clearly implies that the character appears in that local beat. "
        "Use project_guidance only as global correction context for language and story alignment. "
        "Do not treat project-level character anchors as mandatory participants in every scene."
    )
    user_prompt = (
        "Create a structured scene-character participation result for the following project input.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "scenes": [\n'
        "    {\n"
        '      "scene_id": string,\n'
        '      "participating_character_ids": string[],\n'
        '      "primary_character_id": string | null,\n'
        '      "character_presence_notes": string\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- The input includes expected_scene_count and expected_scene_ids. Treat them as hard output contracts.\n"
        "- Return exactly one participation object per input scene.\n"
        "- scenes length must equal expected_scene_count.\n"
        "- Use each expected scene_id exactly once, in the exact order from expected_scene_ids.\n"
        "- All participating characters for the same scene must stay inside one scene object.\n"
        "- Preserve scene order.\n"
        "- Use only character_ids that already exist in character_cards.\n"
        "- If no anchored character clearly appears in a scene, return an empty participating_character_ids list and null primary_character_id.\n"
        "- character_presence_notes should briefly explain local participation, not rewrite the whole scene.\n\n"
        "Project input:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_prompt_optimize_messages(input_payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "You are a workflow planning model for short-video production. "
        "Return only valid JSON. "
        "Preserve the user's core story, but make the prompt more production-ready. "
        "Extract dialogue lines explicitly. "
        "If project_guidance declares input/dialogue/audio language, preserve those language choices and do not translate dialogue lines. "
        "Avoid planning that repeats the same full spoken line across adjacent scenes unless repetition is intentional. "
        "Use project_guidance only as global correction context. "
        "Do not copy project_guidance verbatim into the optimized prompt. "
        "When scene1_first_frame_analysis is provided, treat those image facts as the fixed opening truth for scene 1 and for protagonist identity, wardrobe, props, setting, and lighting continuity."
    )
    user_prompt = (
        "Create a structured prompt optimization result for the following project input.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "optimized_prompt": string,\n'
        '  "creative_intent": string,\n'
        '  "style_guardrails": string[],\n'
        '  "dialogue_lines": string[],\n'
        '  "planning_notes": string\n'
        "}\n\n"
        "Project input:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_story_plan_messages(input_payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "You are a global narrative planner for short-form video workflows. "
        "Return only valid JSON. "
        "Plan the overall story arc before scene-level visual planning happens. "
        "If project_guidance declares dialogue or audio language, preserve those languages and never translate spoken material into a different language. "
        "Use total duration, scene count, dialogue material, and opening truth to decide what each scene is for. "
        "Treat approximate scene durations as narrative capacity, not just bookkeeping. "
        "Do not emit final camera prompt text. "
        "Do not copy project_guidance verbatim into the output. "
        "When scene1_first_frame_analysis is provided, use it as the opening truth and protagonist anchor, but do not let it rigidly determine later story development."
    )
    user_prompt = (
        "Create a structured story plan for the following project input.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "overall_story_arc": string,\n'
        '  "dialogue_strategy": string,\n'
        '  "scene_roles": [\n'
        "    {\n"
        '      "scene_id": string,\n'
        '      "role_label": string,\n'
        '      "narrative_purpose": string,\n'
        '      "story_advance_goal": string,\n'
        '      "pacing_intent": string,\n'
        '      "information_load": string,\n'
        '      "speech_expectation": string\n'
        "    }\n"
        "  ],\n"
        '  "planning_notes": string\n'
        "}\n\n"
        "Rules:\n"
        "- Each scene must have a meaningful story role, not just a continuity filler shot.\n"
        "- Dialogue may stay in one scene if appropriate, but remaining scenes must still carry clear narrative purpose.\n"
        "- Use speech_expectation to describe whether the scene should be silent, partially spoken, or carry the main spoken reveal.\n"
        "- Match scene_id order to scene-01, scene-02, and so on.\n"
        "- Keep the output at the level of story logic and pacing, not final shot wording.\n\n"
        "Project input:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_scene_plan_messages(input_payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "You are a dialogue-aware scene planner for short-form video generation. "
        "Return only valid JSON. "
        "Produce exactly the requested number of scenes. "
        "If project_guidance declares dialogue or audio language, preserve those languages as global guardrails. "
        "Plan visual progression, continuity, and narrative beat progression. "
        "Use any provided story_plan roles as the authoritative reason each scene exists. "
        "Write concrete cinematic scene descriptions, not audience-facing copy. "
        "Do not mention viewers, engagement, comments, virality, platform strategy, or marketing goals. "
        "Do not include runtime bookkeeping or timecode ranges in narrative, visual_goal, or continuity_notes. "
        "Keep visual_goal focused on framing, camera movement, composition, lighting, expression, and action. "
        "Do not decide final spoken_text or speech_mode in this step. "
        "Use project_guidance only to keep the plan aligned with the global task intent. "
        "Do not dump project_guidance into the scene text verbatim. "
        "When scene1_first_frame_analysis is provided, use those first-frame facts as ground truth for the opening state. "
        "Do not plan a conflicting opening pose, prop state, framing, or setting for scene 1."
    )
    user_prompt = (
        "Create a structured scene plan for the following project input.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "scenes": [\n'
        "    {\n"
        '      "title": string,\n'
        '      "narrative": string,\n'
        '      "visual_goal": string,\n'
        '      "continuity_notes": string\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Field guidance:\n"
        "- The input includes expected_scene_count and expected_scene_ids. Treat them as hard output contracts.\n"
        "- Return exactly one scene-plan object per planned scene.\n"
        "- scenes length must equal expected_scene_count.\n"
        "- Scene objects must stay in the exact order implied by expected_scene_ids.\n"
        "- Do not split one planned scene into multiple scene objects.\n"
        '- narrative: what happens on screen in concrete cinematic language, without audience psychology or platform strategy.\n'
        '- visual_goal: camera/framing/motion/lighting/expression guidance only.\n'
        '- continuity_notes: only carry-over constraints such as character identity, wardrobe, props, lighting, camera direction, or where the shot should end.\n'
        '- Do not include spoken_text, speech_mode, delivery_notes, or dialogue allocation decisions in this step.\n\n'
        "Project input:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_dialogue_allocate_messages(input_payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "You are a dialogue allocation planner for short-form video scenes. "
        "Return only valid JSON. "
        "Allocate dialogue against the existing scene beats, durations, and continuity constraints. "
        "Preserve the original dialogue language exactly. Do not translate spoken_text into another language. "
        "Use any provided story roles and speech expectations as the primary story-level guidance. "
        "Not every scene needs spoken dialogue. "
        "Prefer silence when a visual setup beat is stronger without speech. "
        "Do not assign spoken content independently of what the scene is visually doing. "
        "Use project_guidance only as global correction context for reveal pacing and repetition control. "
        "Do not repeat the same full spoken line across adjacent scenes unless repetition is explicitly necessary."
    )
    user_prompt = (
        "Create a structured dialogue allocation plan for the following scene plan.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "allocations": [\n'
        "    {\n"
        '      "scene_id": string,\n'
        '      "spoken_text": string,\n'
        '      "speech_mode": "none" | "once" | "split",\n'
        '      "delivery_notes": string\n'
        "    }\n"
        "  ],\n"
        '  "planning_notes": string\n'
        "}\n\n"
        "Rules:\n"
        "- The input includes expected_scene_count and expected_scene_ids. Treat them as hard output contracts.\n"
        "- Return exactly one allocation object per input scene.\n"
        "- allocations length must equal expected_scene_count.\n"
        "- Use each expected scene_id exactly once, in the exact order from expected_scene_ids.\n"
        "- If one scene contains multiple short sounds or utterances, merge them into a single spoken_text string in playback order and explain timing in delivery_notes.\n"
        "- Do not split one scene into multiple allocation objects.\n"
        "- Preserve scene order.\n"
        "- Not every scene must speak.\n"
        "- Use speech_mode=none for silent scenes.\n"
        "- Use speech_mode=once when a full line should be spoken once in that scene.\n"
        "- Use speech_mode=split only when a longer line is intentionally divided across multiple scenes.\n"
        "- Keep spoken_text exact to the selected line or line segment, without inventing extra dialogue.\n"
        "- Keep delivery_notes tied to the scene beat, emotion, pacing, and camera action.\n\n"
        "Scene plan input:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt


def build_first_frame_analyze_system_prompt() -> str:
    return (
        "You analyze a first-frame still for short-form video continuation prompts. "
        "Return only valid JSON. "
        "Describe what is visibly true in the provided image, not what the narrative might imply. "
        "Focus on subject presence, pose, prop state, framing, setting, lighting, wardrobe, and continuation constraints. "
        "Do not invent motion that is not visible in the image."
    )


def build_first_frame_analyze_user_text(input_payload: dict[str, Any]) -> str:
    return (
        "Analyze the provided first-frame image and return JSON with this shape:\n"
        "{\n"
        '  "subject_presence": string,\n'
        '  "subject_pose": string,\n'
        '  "hand_prop_state": string,\n'
        '  "prop_description": string,\n'
        '  "framing": string,\n'
        '  "setting": string,\n'
        '  "lighting": string,\n'
        '  "wardrobe": string,\n'
        '  "continuation_constraints": string,\n'
        '  "analysis_notes": string\n'
        "}\n\n"
        "Rules:\n"
        "- Report image facts only.\n"
        "- If the subject is already on screen, say so clearly.\n"
        "- If an object is already in hand, say so clearly.\n"
        "- Keep continuation_constraints focused on what the follow-up motion prompt must preserve.\n\n"
        "Scene context:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}"
    )


def build_scene_prompt_render_messages(input_payload: dict[str, Any]) -> tuple[str, str]:
    system_prompt = (
        "You compile structured scene planning artifacts into final video-generation prompts. "
        "Return only valid JSON. "
        "Do not re-plan the scene. Upstream planning is already complete. "
        "Write direct cinematic generation instructions, not planning commentary or workflow explanation. "
        "If input_language is provided, write the descriptive prompt text in that language by default. "
        "If project_guidance or scene_guidance declares dialogue/audio language, preserve that language and make spoken delivery explicit when needed. "
        "When input_language is zh, the visible rendered_prompt should read naturally in Chinese, while spoken_text must remain exact. "
        "When input_language is en, the visible rendered_prompt should read naturally in English. "
        "Do not mention viewers, engagement, comments, virality, hooks, subversion, expectation management, or platform strategy. "
        "Do not mention timecode ranges, runtime bookkeeping, or approximate duration accounting. "
        "Keep the prompt visually concrete: subject, action, framing, camera movement, lighting, composition, expression, props, continuity, and dialogue constraint only. "
        "If first_frame_source is upload, continuity, or auto_generate and first_frame_analysis is provided, treat those first-frame facts as ground truth for the opening state. "
        "Do not invent a different opening pose, prop arrangement, framing, or setting than the analyzed first frame. "
        "In first-frame-driven scenes, write a continuation prompt that starts from the analyzed still instead of restaging the beginning. "
        "Use project_guidance and scene_guidance only as correction context. "
        "Use first_frame_analysis as grounding context, not as a checklist to dump verbatim into the final prompt. "
        "Keep only the highest-signal opening facts that prevent conflicts with the still. "
        "Use continuity only as concise carry-over guidance, not as a checklist. "
        "Do not emit meta lead-ins such as 'Scene intent', 'Visual direction', 'Continuity constraints', "
        "'Full continuity from prior scene', 'Preserve all details', or repeated 'same ... same ...' lists. "
        "Do not enumerate wardrobe, accessories, or background details unless they are necessary to avoid visual conflict. "
        "Do not explicitly mention uploaded, provided, generated, or analyzed first frames in the final prompt. "
        "Do not write phrases such as 'matches the first frame', 'preserve original first frame details', or similar meta instructions."
    )
    user_prompt = (
        "Create a final scene-generation prompt for the following structured scene plan.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "rendered_prompt": string\n'
        "}\n\n"
        "Rules:\n"
        "- Keep it concise and model-facing.\n"
        "- Preserve the exact spoken_text when provided.\n"
        "- Keep the descriptive prompt wording in input_language unless a human working_prompt clearly overrides that choice.\n"
        "- Preserve the declared dialogue/audio language. Do not translate spoken lines.\n"
        "- If speech_mode is none, explicitly forbid spoken dialogue.\n"
        "- If speech_mode is once, require the full line to be spoken once.\n"
        "- If speech_mode is split, require only that exact segment.\n"
        "- Use delivery_notes only when they help performance timing or emotional delivery.\n"
        "- Keep continuity constraints only when they affect the generated shot.\n"
        "- When first_frame_analysis exists, preserve those image facts as the opening frame truth and only describe what continues from that state.\n\n"
        "- If working_prompt is present, treat it as a human draft to refine, not as final text to copy blindly.\n"
        "- Keep the final prompt medium-length: neither too terse nor a full image-analysis report.\n\n"
        "- Treat scene narrative and visual goal as the main planning inputs to adapt into model-facing wording.\n"
        "- Fold continuity and first-frame grounding into natural cinematic language instead of emitting explicit preservation instructions.\n"
        "- Prefer one or two high-signal carry-over anchors over a long inventory of repeated details.\n"
        "- Do not mention uploaded/provided/generated first frames explicitly in the final prompt.\n"
        "Structured scene input:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2)}"
    )
    return system_prompt, user_prompt
