from __future__ import annotations

import unittest

from video_workflow_service.workflow.scene_prompt_render import render_scene_generation_prompt


class ScenePromptRenderTestCase(unittest.TestCase):
    def test_render_scene_generation_prompt_filters_planning_language(self) -> None:
        prompt = render_scene_generation_prompt(
            title="Mysterious woman reveals her hidden identity",
            narrative=(
                "Shifts from the calm opening to build slow-burning intrigue, "
                "subverts the expectation that she is only an unassuming healer's wife, "
                "and leaves viewers hooked with unanswered questions about her true self."
            ),
            visual_goal=(
                "Vertical medium close-up shot, half the woman's face in soft shadow matching the golden hour lighting "
                "from scene 1, ends on a lingering 1-second close-up of her sharp, enigmatic expression after dialogue finishes."
            ),
            spoken_text="They think I'm just a healer's wife, would you believe me if I told you what I really am.",
            speech_mode="once",
            delivery_notes="Deliver the line with a calm, deliberate reveal.",
            continuity_notes=(
                "Duration 0:08-0:15 (matches required 7-second approximate runtime), "
                "dialogue finishes by 0:14 to leave 1 second of lingering final frame to boost engagement, "
                "retains warm golden hour lighting continuity from the first scene."
            ),
        )

        lowered = prompt.lower()
        self.assertNotIn("viewers", lowered)
        self.assertNotIn("engagement", lowered)
        self.assertNotIn("subvert", lowered)
        self.assertNotIn("0:08", prompt)
        self.assertIn("golden hour lighting", lowered)
        self.assertIn('She speaks: "They think I\'m just a healer\'s wife', prompt)
        self.assertIn("Deliver the line with a calm", prompt)
        self.assertNotIn("Visual direction:", prompt)
        self.assertNotIn("Scene intent:", prompt)
        self.assertNotIn("Continuity constraints:", prompt)

    def test_render_scene_generation_prompt_preserves_no_dialogue_instruction(self) -> None:
        prompt = render_scene_generation_prompt(
            title="Close-up of hand picking wild golden hour flowers",
            narrative="Quiet rural opening outside a small cottage before the reveal.",
            visual_goal="Vertical close-up, shallow depth of field, warm golden hour light on the woman's hand and flowers.",
            spoken_text="",
            speech_mode="none",
            delivery_notes="",
            continuity_notes="End with her hand closed around the stems for a clean cut into the next shot.",
        )

        self.assertIn("No spoken dialogue in this scene.", prompt)
        self.assertIn("clean cut into the next shot", prompt)

    def test_render_scene_generation_prompt_preserves_declared_chinese_dialogue_language(self) -> None:
        prompt = render_scene_generation_prompt(
            title="药房中的女人",
            narrative="女人站在昏暗药房里，缓慢抬眼看向镜头。",
            visual_goal="静态中景，暖色柔光，细微表情变化。",
            spoken_text="他们都以为我只是个医娘子。",
            speech_mode="once",
            delivery_notes="语速缓慢，声音压低，带一点克制的神秘感。",
            input_language="zh",
            dialogue_language="zh",
            audio_language="zh",
            continuity_notes="保持同一人物、药房环境和手中的草药束。",
        )

        self.assertIn("用自然中文完整说出这句台词一次", prompt)
        self.assertIn('他们都以为我只是个医娘子。', prompt)
        self.assertNotIn("natural English", prompt)
        self.assertNotIn("natural Mandarin Chinese", prompt)

    def test_render_scene_generation_prompt_uses_first_frame_ground_truth(self) -> None:
        prompt = render_scene_generation_prompt(
            title="Woman with dried flowers",
            narrative="Continue the reveal from the opening still.",
            visual_goal="Maintain the same portrait framing and subtle hand motion.",
            spoken_text="",
            speech_mode="none",
            delivery_notes="",
            continuity_notes="Keep the same room lighting and costume continuity.",
            first_frame_source="upload",
            first_frame_prompt="",
            first_frame_analysis={
                "subject_presence": "The woman is already fully visible on screen.",
                "hand_prop_state": "She is already holding a dried flower bundle in both hands.",
                "framing": "A medium close-up portrait framing is already established.",
                "setting": "An interior rustic room is already established.",
                "lighting": "Soft warm interior light is already established.",
                "continuation_constraints": "Do not restage the hand reaching for the flowers.",
            },
        )

        lowered = prompt.lower()
        self.assertIn("holding a dried flower bundle", lowered)
        self.assertNotIn("provided first frame", lowered)
        self.assertNotIn("matches the uploaded first frame", lowered)
        self.assertNotIn("Scene intent:", prompt)
        self.assertNotIn("Continuity constraints:", prompt)

    def test_render_scene_generation_prompt_avoids_continuity_checklist_meta(self) -> None:
        prompt = render_scene_generation_prompt(
            title="Close-up aftermath",
            narrative="The woman remains still after the reveal.",
            visual_goal="Slow push-in to a tight close-up.",
            spoken_text="",
            speech_mode="none",
            delivery_notes="",
            continuity_notes=(
                "Full continuity from prior scene: same wardrobe, same held herb bundle, same rustic apothecary setting, "
                "same warm low-key lighting, no abrupt cut."
            ),
        )

        lowered = prompt.lower()
        self.assertNotIn("full continuity from prior scene", lowered)
        self.assertNotIn("same wardrobe", lowered)
        self.assertNotIn("same held herb bundle", lowered)
        self.assertIn("continuous carry-over from the prior shot", lowered)


if __name__ == "__main__":
    unittest.main()
