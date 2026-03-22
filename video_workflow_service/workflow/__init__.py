"""Workflow step definitions."""

from video_workflow_service.workflow.contracts import (
    DialogueAllocation,
    DialogueAllocationInput,
    DialogueAllocationOutput,
    DialogueAllocationSceneInput,
    FinalCompositionInput,
    FinalCompositionOutput,
    PromptOptimizationInput,
    PromptOptimizationOutput,
    SceneCharacterCastInput,
    SceneCharacterCastOutput,
    SceneCharacterCastSceneInput,
    SceneCharacterParticipation,
    SceneGenerationInput,
    SceneGenerationOutput,
    ScenePlanningInput,
    ScenePlanningOutput,
    ScenePromptRenderInput,
    ScenePromptRenderOutput,
    StoryboardBinding,
    StoryboardUploadInput,
    StoryboardUploadOutput,
)
from video_workflow_service.workflow.dialogue_allocate import allocate_dialogue_step
from video_workflow_service.workflow.prompt_optimization import optimize_prompt_step
from video_workflow_service.workflow.scene_character_cast import scene_character_cast_step
from video_workflow_service.workflow.scene_planning import plan_scenes_step
from video_workflow_service.workflow.scene_prompt_render import render_scene_prompt_step

__all__ = [
    "DialogueAllocation",
    "DialogueAllocationInput",
    "DialogueAllocationOutput",
    "DialogueAllocationSceneInput",
    "FinalCompositionInput",
    "FinalCompositionOutput",
    "PromptOptimizationInput",
    "PromptOptimizationOutput",
    "SceneCharacterCastInput",
    "SceneCharacterCastOutput",
    "SceneCharacterCastSceneInput",
    "SceneCharacterParticipation",
    "SceneGenerationInput",
    "SceneGenerationOutput",
    "ScenePlanningInput",
    "ScenePlanningOutput",
    "ScenePromptRenderInput",
    "ScenePromptRenderOutput",
    "StoryboardBinding",
    "StoryboardUploadInput",
    "StoryboardUploadOutput",
    "allocate_dialogue_step",
    "optimize_prompt_step",
    "scene_character_cast_step",
    "plan_scenes_step",
    "render_scene_prompt_step",
]
