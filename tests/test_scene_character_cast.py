from __future__ import annotations

from tempfile import TemporaryDirectory
import unittest

from video_workflow_service import load_settings
from video_workflow_service.workflow.contracts import (
    SceneCharacterCastInput,
    SceneCharacterCastSceneInput,
)
from video_workflow_service.workflow.scene_character_cast import scene_character_cast_step
from video_workflow_service.workflow.trace_logger import WorkflowTraceLogger


class SceneCharacterCastTestCase(unittest.TestCase):
    def test_scene_character_cast_assigns_only_matching_anchored_characters(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            output = scene_character_cast_step(
                SceneCharacterCastInput(
                    raw_prompt="Han Li studies a map; Granny Liu waits by the doorway.",
                    optimized_prompt="Han Li studies a map; Granny Liu waits by the doorway.",
                    input_language="en",
                    dialogue_language="en",
                    audio_language="en",
                    overall_story_arc="Two related beats with different local character focus.",
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
                    scenes=[
                        SceneCharacterCastSceneInput(
                            scene_id="scene-01",
                            scene_index=1,
                            title="Scene 1",
                            narrative="Han Li studies a hand-drawn map in silence.",
                            visual_goal="Static medium shot on Han Li at the worktable.",
                            continuity_notes="Keep the room and map consistent.",
                            duration_seconds=6,
                        ),
                        SceneCharacterCastSceneInput(
                            scene_id="scene-02",
                            scene_index=2,
                            title="Scene 2",
                            narrative="An empty doorway holds for a quiet beat with no one entering yet.",
                            visual_goal="Static doorway framing with no visible character.",
                            continuity_notes="Keep the same hallway setting.",
                            duration_seconds=6,
                        ),
                    ],
                ),
                settings=settings,
                trace_logger=WorkflowTraceLogger(settings),
                project_id="prj_test",
            )

            self.assertEqual(len(output.scenes), 2)
            self.assertEqual(output.scenes[0].participating_character_ids, ["char-01"])
            self.assertEqual(output.scenes[0].primary_character_id, "char-01")
            self.assertEqual(output.scenes[1].participating_character_ids, [])
            self.assertIsNone(output.scenes[1].primary_character_id)


if __name__ == "__main__":
    unittest.main()
