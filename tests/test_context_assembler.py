from __future__ import annotations

import unittest

from video_workflow_service.workflow.context_assembler import (
    build_project_guidance_context,
    build_scene_guidance_context,
)


class ContextAssemblerTestCase(unittest.TestCase):
    def test_project_guidance_is_shaped_per_node(self) -> None:
        guidance = build_project_guidance_context(
            step_name="scene_plan",
            target_duration_seconds=15,
            scene_count=2,
            creative_intent="A restrained reveal with strong continuity.",
            style_guardrails=["Keep protagonist identity stable.", "Avoid redundant dialogue."],
            planning_notes="Let the reveal land only once.",
            dialogue_lines=["They think I'm just a healer's wife."],
            scene1_first_frame_source="upload",
            scene1_first_frame_analysis={
                "subject_presence": "The woman is already on screen.",
                "hand_prop_state": "She is already holding a dried herb bundle.",
                "wardrobe": "A cream blouse with a purple pendant.",
            },
        )

        self.assertEqual(guidance["scene_count"], 2)
        self.assertEqual(guidance["scene1_first_frame_source"], "upload")
        self.assertIn("already holding a dried herb bundle", guidance["opening_truth_summary"].lower())
        self.assertIn("Primary dialogue line", guidance["global_dialogue_intent"])
        self.assertNotIn("wardrobe", guidance["opening_truth_summary"].lower())

    def test_scene_guidance_compacts_first_frame_and_dialogue_signals(self) -> None:
        guidance = build_scene_guidance_context(
            step_name="scene_prompt_render",
            working_prompt="Tighten the expression shift and keep the herb bundle steady.",
            spoken_text="They think I'm just a healer's wife.",
            speech_mode="once",
            delivery_notes="Deliver it softly while maintaining eye contact.",
            first_frame_source="upload",
            first_frame_analysis={
                "subject_pose": "She faces camera in a stable waist-up pose.",
                "hand_prop_state": "She already holds the herb bundle in both hands.",
                "setting": "A rustic indoor apothecary is already established.",
                "lighting": "Warm soft front light is already established.",
            },
            continuity_notes="Maintain the same wardrobe and warm lighting continuity into the close-up.",
        )

        self.assertIn("stable waist-up pose", guidance["first_frame_anchor_summary"].lower())
        self.assertIn("deliver the allocated line once", guidance["dialogue_guidance"].lower())
        self.assertIn("warm lighting continuity", guidance["continuity_anchor_summary"].lower())
        self.assertEqual(guidance["working_prompt"], "Tighten the expression shift and keep the herb bundle steady.")

    def test_scene_guidance_only_summarizes_participating_characters(self) -> None:
        guidance = build_scene_guidance_context(
            step_name="scene_prompt_render",
            character_cards=[
                {
                    "character_id": "char-01",
                    "display_name": "Han Li",
                    "story_role": "protagonist",
                },
                {
                    "character_id": "char-02",
                    "display_name": "Granny Liu",
                    "story_role": "guide",
                },
            ],
            participating_character_ids=["char-02"],
            primary_character_id="char-02",
            character_presence_notes="She is the only figure in this beat.",
        )

        summary = guidance["character_presence_summary"]
        self.assertIn("Granny Liu", summary)
        self.assertNotIn("Han Li", summary)
        self.assertIn("only figure", summary)


if __name__ == "__main__":
    unittest.main()
