# Video Workflow Service Architecture

## 1. Positioning
- Final project identity:
  `video_workflow_service`
- Current state:
  The repository contains a phase-0 provider-backed spike that proves the workflow can run end-to-end.
- Boundary:
  The spike is a stage delivery.
  It is not the final project structure.

## 2. Architectural Goal
- Build a workflow-first short-video generation backend.
- Keep provider integration real and deterministic.
- Avoid agent-oriented architecture.
- Make the workflow state, scene assets, and delivery assets explicit.

## 3. Layered Design
- `api`
  HTTP transport, request parsing, response serialization, artifact serving.
- `application`
  Use-case orchestration for create-project, run-workflow, upload-storyboard, generate-scenes, compose, deliver.
- `domain`
  Core entities and state transitions: project, scene, assets, job status, workflow events.
- `workflow`
  Step definitions and contracts.
  Each step has a stable input/output schema and no provider-specific HTTP logic.
- `providers`
  External model adapters.
  First implementation: Doubao/Seedance.
- `media`
  FFmpeg composition, frame extraction, continuity asset handling.
- `storage`
  Repository layer for project state and artifact indexing.
- `infrastructure`
  Env loading, file paths, runtime settings, external IO wrappers.

## 4. Workflow Contract
- Step 1: `prompt_optimize`
  Input: raw prompt
  Output: optimized prompt version
- Step 2: `scene_plan`
  Input: optimized prompt, target duration
  Output: exactly 3 scene definitions for MVP
- Step 3: `storyboard_upload`
  Input: scene reference images and notes
  Output: bound storyboard assets
- Step 4: `scene_video_generate`
  Input: scene prompt, duration, optional continuity frame, optional storyboard reference
  Output: scene video asset, last-frame asset, provider metadata
- Step 5: `final_compose`
  Input: ordered scene assets
  Output: final composed video asset
- Step 6: `delivery_publish`
  Input: final composed asset
  Output: downloadable delivery asset metadata

## 5. MVP Rules
- Scene count is fixed at 3 for the first MVP.
- Native provider audio is enabled by default when the selected model supports it.
- Scene 2 and Scene 3 may use the previous scene's last frame as continuity input.
- Composition must preserve audio unless there is an explicit compatibility reason not to.

## 6. Naming Policy
- External project/service name must not contain `demo`.
- Internal compatibility modules may temporarily retain spike names during refactor only.
- README, plan docs, architecture docs, and future API descriptions must use `video_workflow_service`.

## 7. Phase Model
- `Phase 0: Spike`
  Goal: prove real provider workflow can run.
  Status: achieved.
- `Phase 1: MVP Service`
  Goal: package rename, layered architecture, stable state contracts, same real workflow capability retained.
- `Phase 2: Production Hardening`
  Goal: stronger validation, retries, observability, async workers, richer planning.

## 8. Frontend Integration
- Frontend mode:
  A minimal `React + TypeScript` frontend built with `Vite` and served by the existing Python HTTP service as static assets.
- Why:
  The project already expects UI scope to grow beyond a throwaway page.
  The right trade-off is to keep static deployment while avoiding a planned rewrite from ad hoc browser scripts to a component-based frontend.
- Ownership split:
  `video_workflow_service/api/http_server.py`
  Serves JSON APIs, artifacts, and built frontend assets.
  `video_workflow_service/application/workflow_service.py`
  Owns workflow orchestration and remains independent of HTML or browser concerns.
  `frontend/`
  Owns the React app source and build output.
- Proposed minimal web asset layout:
  `frontend/package.json`
  `frontend/tsconfig.json`
  `frontend/vite.config.ts`
  `frontend/index.html`
  `frontend/src/main.tsx`
  `frontend/src/App.tsx`
  `frontend/src/api/client.ts`
  `frontend/src/state/project-store.ts`
  `frontend/src/components/*.tsx`
  `frontend/src/styles.css`
  `frontend/dist/`
- Transport strategy:
  First milestone uses short-interval polling against `/projects/<id>/workflow/status`.
  A later milestone may add `SSE` for server-to-browser progress updates without changing the React UI composition.
- UI scope for the first frontend milestone:
  Create project.
  Start workflow.
  Poll workflow status.
  Preview delivered video.

## 9. HITL Scene Review Mode
- Positioning:
  The service supports two orchestration modes:
  `auto`
  Existing one-shot workflow run that generates all scenes and composes automatically.
  `hitl`
  Scene-by-scene generation with human approval gates between scenes.
- First-frame source model:
  `auto_generate`
  No user-supplied image is required for the scene start reference.
  `upload`
  User uploads or binds an explicit first-frame image.
  `continuity`
  The scene uses the previous scene's ending frame as the preferred start reference.
- Scene review model:
  A generated scene may enter `pending_review`.
  User approval promotes the scene to `approved`.
  Final composition in HITL mode is allowed only after all scenes are approved.
- API direction:
  Keep existing project-level auto workflow endpoints intact.
  Add scene-level generate and approve endpoints for HITL control.
- Transport strategy:
  Polling remains acceptable for the first HITL milestone.
  `SSE` is the preferred upgrade path once the review state machine is stable.

## 10. Provider Content Model
- Design rule:
  Workflow and domain layers express business intent such as `reference_image`, `first_frame_source`, `first_frame_image`, and `continuity`.
  Provider adapters translate that intent into provider-native `content` items.
- Abstraction direction:
  The provider layer should converge on a normalized internal content model:
  `text`
  `image`
  `first_frame`
  `last_frame`
  Additional content types may be added later without changing workflow contracts.
- Role policy:
  `content.role` is not a universal business primitive.
  It is a provider protocol detail and must only be emitted when the target provider contract explicitly allows it for that content shape.
- Current Doubao rule:
  A business-level `first_frame` input is serialized as an `image_url` item with `role=first_frame`.
  A business-level reference image remains a plain `image_url` item without `role`.
  A true first/last-frame pair is serialized with explicit `first_frame` and `last_frame` roles.
- Mapping policy:
  Business-layer first-frame semantics remain readable and provider-agnostic.
  Provider adapters own the final decision about whether a business reference becomes a plain image item, a role-tagged frame item, or another provider-specific payload form.
- Response policy:
  Provider adapters must normalize task status and asset URLs from multiple valid provider response shapes before results enter application state.

## 11. HITL Scene Prompt Revision
- Current prompt model:
  `Scene.prompt` is the editable working prompt for the next generation attempt.
- Traceability rule:
  Each scene generation attempt should snapshot the prompt text actually sent to the provider.
  The first implementation may store this in `SceneVideoJob.metadata` before introducing a dedicated generation-history model.
- Editing rule:
  HITL users may edit scene prompts before generation and while a scene is under review.
  Prompt edits must be rejected while the scene has an in-flight generation job.
- Approval rule:
  Approved scenes default to read-only prompt state.
  If later re-editing is needed, it should be introduced as an explicit reopen action instead of silent prompt mutation.

## 12. LLM Workflow Node
- Positioning:
  The service may introduce LLM-backed workflow nodes, but they remain deterministic workflow steps rather than agent capabilities.
- Boundary:
  LLM transport belongs in a dedicated `llm` runtime layer.
  Workflow steps own prompt templates, structured output contracts, and validation.
- First provider direction:
  The first LLM provider implementation should use Doubao Ark Chat so the project can reuse the existing Doubao credentials.
- Current implementation:
  `video_workflow_service/llm/doubao_ark.py`
  `video_workflow_service/llm/model_registry.py`
  `video_workflow_service/workflow/llm_node.py`
  `video_workflow_service/workflow/trace_logger.py`
- First target steps:
  `prompt_optimize`
  `story_plan`
  `scene_plan`
  `dialogue_allocate`
  `first_frame_analyze`
  `scene_prompt_render`
- Model routing rule:
  LLM provider selection and model selection are different concerns.
  The provider may remain `doubao`, while each workflow node resolves its own model name through a node-level model registry.
- Current defaults:
  `VIDEO_WORKFLOW_LLM_PROVIDER=doubao`
  `VIDEO_WORKFLOW_LLM_DEFAULT_MODEL=doubao-seed-2-0-lite-260215`
  Optional node overrides:
  `VIDEO_WORKFLOW_LLM_PROMPT_OPTIMIZE_MODEL`
  `VIDEO_WORKFLOW_LLM_SCENE_PLAN_MODEL`
  `VIDEO_WORKFLOW_LLM_DIALOGUE_ALLOCATE_MODEL`
  `VIDEO_WORKFLOW_LLM_FIRST_FRAME_ANALYZE_MODEL`
  `VIDEO_WORKFLOW_LLM_SCENE_PROMPT_RENDER_MODEL`
  `VIDEO_WORKFLOW_LLM_DIALOGUE_SPLIT_MODEL`
- Output rule:
  LLM-generated intermediate artifacts must be persisted as structured workflow outputs, not just ephemeral prompt strings.
- Trace rule:
  LLM inputs, outputs, validation results, and user HITL edits should be written to an append-only workflow trace in addition to the project snapshot.
- Runtime trace path:
  `runtime_data/logs/<project_id>/workflow_trace.jsonl`
- Dialogue rule:
  A dedicated global narrative-planning step should exist ahead of `scene_plan`.
  `story_plan` decides the overall story arc, per-scene narrative roles, and pacing intent using total duration, scene count, dialogue material, and opening truth.
- Dialogue rule:
  Dialogue allocation should be its own workflow boundary.
  Not every scene requires spoken dialogue.
  The allocation step should decide whether a scene is silent, fully spoken, or partially spoken using scene role, scene beat, duration, and continuity context from `story_plan` and `scene_plan`.
- Prompt rendering rule:
  Scene plan output and final video-generation prompt should be separate workflow boundaries.
  `scene_prompt_render` should merge visual scene planning plus dialogue allocation into model-facing cinematic instructions and strip audience-growth or runtime-bookkeeping language before provider video generation.
- Planning-chain rule:
  The preferred high-level chain is:
  `prompt_optimize -> story_plan -> scene_plan -> dialogue_allocate -> scene_prompt_render`
  `story_plan` owns why each scene exists.
  `scene_plan` owns how each scene is visually staged.
- Supplier diversification rule:
  Doubao remains the stable supplier for multimodal first-frame analysis and provider-backed video/image generation.
  A second text-only supplier may be introduced for structured workflow nodes when official API support is stronger for JSON output.
- Current DeepSeek structured-node boundary:
  The current DeepSeek-backed structured planning surface is:
  `prompt_optimize`
  `story_plan`
  `scene_plan`
  `dialogue_allocate`
  `scene_character_cast`
  Doubao remains the active supplier for `first_frame_analyze`, `scene_prompt_render`, and provider-backed asset/video generation.
- Structure boundary:
  The project should not add JSON structure just to fit a supplier.
  Only nodes whose outputs are already necessary machine-readable workflow artifacts should be considered for DeepSeek migration.
- Scene-list contract rule:
  For structured nodes that emit one object per planned scene, `scene_count` and ordered `scene_id` values are hard output contracts, not soft context hints. Prompt wording, validation, and any repair retry should all preserve one-scene-one-object semantics.

## 13. First Frame Orchestration
- Positioning:
  First-frame handling is a workflow capability, not a late storyboard tweak.
- Workflow rule:
  Scene 1 must choose exactly one initial first-frame mode before scene video generation starts:
  `upload`
  `auto_generate`
- Later-scene rule:
  Scene 2..N default to `continuity`, but users may explicitly override with `upload` or `auto_generate`.
- Node design:
  `first_frame_prepare`
  Resolves the effective first-frame source and produces a still asset.
  `first_frame_analyze`
  Uses the first-frame still as multimodal input and extracts structured visual facts for downstream prompt compilation.
- Ordering rule:
  For `scene-01`, concrete first-frame preparation and analysis must happen before `prompt_optimize` and `scene_plan` so the opening still can anchor protagonist identity, prop state, framing, setting, and lighting in downstream planning.
  For later scenes, first-frame preparation and analysis may still happen at scene time because the effective first frame often depends on the previous scene tail frame.
- Prompt rule:
  In `upload` and `continuity` modes, `scene_prompt_render` must not invent opening-frame details such as subject pose, framing, prop state, or setting when those should be defined by the supplied still.
  It should write a continuation-oriented prompt that starts from first-frame facts.
- Legacy-path rule:
  `scene_plan` must not directly mint the final provider-facing prompt.
  Any early prompt text is only a working draft; the final provider prompt is always compiled from the latest scene state plus first-frame facts.
- Generated-still rule:
  If the still was auto-generated, the workflow must persist and expose the `first_frame_prompt` used to create it so the user can inspect, regenerate, or replace it.
- Provider rule:
  Existing Doubao multimodal LLM support is sufficient for first-frame analysis in the first implementation.
  A dedicated second visual provider is not required initially.
  First-frame auto-generation should use the official Doubao image generation API with model `doubao-seedream-5-0-lite-260128`.

## 14. Node Guidance Context and Prompt Artifact Semantics
- Context rule:
  Workflow nodes do not share one monolithic mutable context object.
  Each node keeps its own primary input contract and may additionally receive a compact guidance layer that provides global correction signals.
- Guidance-layer rule:
  Guidance context exists to prevent drift from the global task goal.
  It must not invade node semantics by replacing the node's primary decision space with checklist-style injected facts.
- Recommended structure:
  `ProjectGuidanceContext`
  carries project-level correction signals such as creative intent, style guardrails, total duration, scene count, and scene-01 opening truth summary.
  `SceneGuidanceContext`
  carries current-scene correction signals such as scene beat, dialogue allocation summary, first-frame anchor summary, continuity anchor summary, and optional user working prompt.
- Assembly rule:
  Use a lightweight context-assembly layer, not a heavyweight global context manager.
  Node-specific policies should decide which correction signals are visible to each workflow step.
- Prompt artifact rule:
  `scene.narrative`
  planning-only artifact produced by `scene_plan`
  `scene.prompt`
  user-editable working draft used as render input
  `provider prompt snapshot`
  immutable compiled prompt used for a specific generation attempt
- Authority rule:
  `scene_prompt_render` is the only authority that compiles the final provider-facing video prompt.
  `scene_video_generate` must consume a compiled prompt snapshot and must not reinterpret planning semantics.

## 15. Scene Prompt Gate and Generate Semantics
- Interaction rule:
  HITL users should edit a single visible `Scene Prompt`.
  The system must not require a separate visible `Approve Prompt` action.
- Gate rule:
  `Generate Scene` acts as the implicit approval point for the current scene setup.
  Architecturally this is a `scene_setup_gate`, even if the UI does not expose it as a separate step.
- Artifact rule:
  `candidate_prompt`
  current user-visible editable prompt
  `approved_prompt`
  prompt frozen when the user clicks `Generate Scene`
  `provider prompt snapshot`
  immutable provider-facing prompt used for the specific generation attempt
- Freeze rule:
  Once a user-edited prompt has been approved through `Generate Scene`, backend generation must not re-run prompt render or silently mutate that prompt for the same attempt.
- Staleness rule:
  If first-frame, dialogue allocation, or continuity inputs change after a user edit or after a prior generation, the candidate prompt may be marked stale.
  The system must not silently overwrite a user-owned prompt.
- UI wording rule:
  Prefer `Scene Prompt` and `Last Used Prompt`.
  Avoid exposing internal artifact names or using `Approve Prompt` as a user-facing action.

## 16. Scene Prompt Render Narrowing
- Positioning rule:
  `scene_prompt_render` is a scene-plan-to-video-prompt compiler, not a second scene planner.
- Responsibility rule:
  It should convert scene narrative intent, visual goal, dialogue allocation, and grounding constraints into natural cinematic prompt wording for the video model.
- Non-responsibility rule:
  It must not redefine story payload, pacing ownership, or dialogue strategy that already belong to `story_plan`, `scene_plan`, and `dialogue_allocate`.
- First-frame rule:
  Concrete first-frame facts should act as opening-state grounding.
  They should prevent contradictions, but they should not be dumped into the final prompt as an analysis report or explicit checklist.
- Continuity rule:
  Continuity should appear in final prompts only as concise cinematic carry-over when needed.
  Avoid internal phrasing such as `full continuity from prior scene`, `preserve all details`, or repeated `same ... same ...` checklists.
- Output-style rule:
  Final scene prompts should read like medium-length natural video-generation instructions:
  subject
  opening state
  action or performance progression
  camera/framing/light
  spoken-line constraints
  minimal high-signal continuity anchors only

## 17. HITL Next Action UI
- Layout rule:
  The HITL frontend should present scenes as an ordered review sequence, not an unordered gallery.
- Preferred structure:
  `scene timeline + active scene workspace + sticky next action area`
- Interaction rule:
  The UI should always surface the next actionable step:
  generate the next scene
  approve the current scene
  compose the final video
  rather than forcing the user to search manually.
- Generating-state rule:
  Scene generation should show a strong workspace-level in-progress state, not just a loading button label.
  Use stage-based visual feedback when exact progress is unavailable.
- Canvas rule:
  Do not adopt infinite-canvas or waterfall/masonry layouts as the primary HITL workflow shell for the current sequential review path.
- Navigation rule:
  Completed scenes should remain reviewable, but the active scene and next action must dominate visual focus.

## 18. Language and Character Consistency Preflight
- Positioning rule:
  Language consistency and character consistency should be modeled as an upstream preflight layer, not as ad-hoc fixes inside later planning or provider nodes.
- Language rule:
  Add a dedicated `language_detect` node before prompt optimization.
  In the first slice it should classify `zh` vs `en`, derive dialogue/audio language, and propagate that result as compact guidance to downstream workflow steps.
- Character rule:
  Add a dedicated `character_anchor` capability before scene-level planning becomes authoritative.
  It should extract up to three major recurring characters and persist text-first character cards.
  Optional reference-image lookdev should happen only through explicit HITL actions before those visual assets are treated as project truth.
- Boundary rule:
  `character_anchor` is a project-level identity asset.
  `first_frame` is a scene-level opening-state asset.
  These two concepts must not be collapsed into the same field or treated as interchangeable prompt metadata.
- Integration rule:
  Approved character anchors should influence:
  scene-01 opening-still generation
  story and scene planning guidance
  scene prompt rendering
  but should not automatically force mixed first-frame-plus-reference-image provider requests until that provider mode is formalized.
- Workflow rule:
  A preferred extended chain is:
  `language_detect -> character_anchor -> scene1_first_frame_prepare/analyze -> prompt_optimize -> story_plan -> scene_plan -> dialogue_allocate -> scene_prompt_render`
  while preserving the current downstream generation and HITL review semantics.

## 19. Scene Character Participation
- Layering rule:
  `character_anchor` stays project-level and must not behave like a global hard constraint for every scene.
- Scene rule:
  introduce a dedicated `scene_character_cast` layer that maps project-level character anchors onto individual scenes.
- Participation rule:
  each scene should explicitly declare:
  `participating_character_ids`
  `primary_character_id`
  `character_presence_notes`
- Context rule:
  only the participating characters for the current scene may enter scene-level prompt/render guidance.
  scenes with no matching participating characters should receive no character-anchor injection.
- Workflow rule:
  a preferred refined chain is:
  `language_detect -> character_anchor -> scene1_first_frame_prepare/analyze -> prompt_optimize -> story_plan -> scene_plan -> scene_character_cast -> dialogue_allocate -> scene_prompt_render`
- Safety rule:
  do not inject all project characters into scene planning or prompt rendering by default.
  filtered scene-level cast data is required before character anchors may influence scene-level prompts or still generation.

## 20. Character Lookdev Assets
- Positioning rule:
  Character visual look development is a project-level asset workflow, not a replacement for scene-level first-frame orchestration.
- Current-card rule:
  `character_anchor` should stay text-first by default.
  Character reference images are optional lookdev assets generated or uploaded only through explicit HITL actions.
- Provider rule:
  The current stable `scene_video_generate` path remains first-frame-oriented.
  Character lookdev assets must not automatically alter that request shape or be mixed into the same provider request as a default companion to `first_frame`.
- Integration rule:
  approved character lookdev assets may influence:
  scene-filtered opening-still generation
  project and scene guidance context
  future provider modes that explicitly support character-reference video generation
  but they must not change the current first-frame video path.
- Workflow rule:
  the preferred boundary is:
  `character_anchor(text cards) -> character_lookdev_hitl(on demand) -> scene_character_cast -> opening_still_generate(scene-filtered) -> scene_video_generate(first-frame mode)`

## 21. Feedback-Driven Scene Revision
- Positioning rule:
  Feedback-driven revision is an assistive HITL editing path, not a replacement for direct prompt editing and not an auto-generate trigger.
- Scene-01 rule:
  `scene-01` may support two revision scopes:
  `prompt_only`
  `opening_still_and_prompt`
  because its opening still is a dedicated opening-state asset.
- Later-scene rule:
  `scene-02..N` should default to `prompt_only` feedback revision.
  They must not silently rewrite inherited continuity start-state truth through the prompt-revision path.
- Safety rule:
  If a later-scene feedback is actually changing continuity opening truth, the system should reject or redirect that request rather than mutating the prompt and leaving it inconsistent with the inherited start state.
- Generate rule:
  Revised prompts remain editable drafts.
  `Generate Scene` continues to be the only approval/freeze point for downstream generation.

## 22. Final Video Download UX
- Delivery-action rule:
  final preview/open and final download must be treated as separate UX intents.
- Preview rule:
  standard artifact URLs should remain inline/playable so the workflow page can embed and preview final video assets.
- Download rule:
  explicit download actions should use an attachment-style response so the browser downloads the file instead of replacing the workflow UI with a raw media page.
- Safety rule:
  this is a delivery-layer interaction fix only and must not change compose timing, workflow state, or artifact storage shape.

## 23. Deferred Staged Scene Execution Idea
- Positioning rule:
  staged scene execution is a deferred internal execution strategy, not part of the current default workflow and not an added HITL layer.
- Motivation rule:
  it is intended for cases where the scene opening frame should establish environment first, while consistent character appearance is needed only after the opening moment.
- Shape rule:
  a possible future strategy is:
  `Shot A (opening environment) -> extract A final frame -> optional bridge still using A tail frame plus approved character lookdev -> Shot B (character entrance) -> internal stitch`
- UX rule:
  if implemented later, users should still see one scene, one review surface, and one approval action.
  `Shot A` and `Shot B` should remain internal execution details.
- Continuity rule:
  this approach is not a no-cut continuity guarantee.
  if a bridge still is regenerated, it should be treated as a hidden internal cut that trades some continuity risk for better character stability.
- Status rule:
  record this as a future advanced mode only.
  do not change the current first-frame-based scene generation path or introduce sub-shot workflow complexity yet.

## 24. Composer Boundary Smoothing
- Boundary rule:
  the existing scene continuity design remains valid.
  using the previous scene tail frame as the next scene first-frame hint should remain the default generation strategy.
- Responsibility rule:
  scene generation is responsible for making adjacent scenes connect semantically.
  composer is responsible for making adjacent scene boundaries feel smooth in the final assembled delivery.
- Compose rule:
  final composition should not remain a plain hard concat when adjacent clips visibly jump at their boundaries.
  conservative boundary trim and very short video/audio smoothing should be preferred before any heavier workflow redesign.
- Safety rule:
  this smoothing should live only in the final compose layer.
  it must not change scene planning, scene review semantics, continuity inheritance, or the provider request shape for scene generation.

## 25. Delivery Sidecar Subtitles
- Positioning rule:
  subtitle generation should be treated as a delivery-side enhancement path, not as part of the main scene-generation gate.
- Product option rule:
  subtitle work should be controlled by an explicit project-level option selected at task creation time.
  that creation-time option should stay simple, such as `disabled | enabled`.
  users should not be forced to choose between file delivery and burned delivery up front.
- Workflow rule:
  the preferred shape is:
  `final_compose -> subtitle_align -> subtitle_publish`
  with subtitle work running only when the project contains actual spoken dialogue.
- Asset rule:
  the first slice should publish sidecar subtitle assets such as `SRT` or `VTT`.
  hard-burned subtitles should remain a later optional delivery mode, not the default.
- Provider rule:
  because this workflow already stores approved dialogue text, text-based subtitle timing is the preferred primary alignment strategy.
  speech-recognition-based fallback should remain available when generated speech diverges from the planned text or timing alignment fails.
- Safety rule:
  subtitle generation failure must not block final video delivery.
  the final video remains the primary artifact, and subtitles are an additive best-effort asset.
- Current implementation rule:
  project creation now carries an explicit subtitle-mode switch.
  current implementation still stores the sidecar-first slice internally, but the intended product semantics are a simpler `disabled | enabled` subtitle toggle.
  after `final_compose`, the service may queue a separate subtitle job without changing the delivered status of the final video.
- Primary execution rule:
  the current primary path extracts audio from `final.mp4`, concatenates approved scene dialogue text in scene order, and sends that audio-plus-text pair to a dedicated Volcengine speech subtitle client for `自动字幕打轴`.
  subtitle service wiring stays separate from the LLM provider layer.
- Fallback execution rule:
  the current fallback uses `录音文件极速版` against the extracted final-delivery audio.
  because this path can upload audio data directly, the service does not require a publicly reachable artifact base URL for fallback execution.
  its purpose is to recover real `utterances[start_time,end_time,text]` from delivered speech when ATA alignment is unavailable or unreliable.
- Publishing rule:
  successful subtitle alignment currently publishes `final.srt` and `final.vtt` beside the delivered MP4 and reuses the existing artifact route for download.
  the current user-facing delivery shape is:
  - in-player subtitle loading
  - a one-click delivery package containing the original MP4 plus subtitle files
  - an on-demand burned-subtitle export that produces a separate `final_burned.mp4`
  without replacing the original final video.
  burned-subtitle export should not depend on host-installed CJK fonts; it should use a bundled repo font and explicit FFmpeg subtitle font settings so Chinese text remains stable across environments.
- Deferred work rule:
  the remaining subtitle hardening work is now concentrated in real-service verification and optional refinement of fallback heuristics.
