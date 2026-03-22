import { useEffect, useMemo, useState } from "react";
import type { SceneRecord } from "../api/client";

interface SceneListProps {
  scenes: SceneRecord[];
  workflowMode: string;
  isPlanningBootstrap: boolean;
  planningStage: "idle" | "creating_project" | "global_planning" | "scene_planning";
  canCompose: boolean;
  isComposing: boolean;
  activeAction: { sceneId: string; action: "generate" | "approve" | "save_first_frame" | "save_prompt" } | null;
  onGenerate: (sceneId: string) => void;
  onApprove: (sceneId: string) => void;
  onCompose: () => void;
  onSavePrompt: (sceneId: string, prompt: string) => void;
  onSaveFirstFrame: (
    sceneId: string,
    firstFrameSource: string,
    firstFrameImage: string | null,
    storyboardNotes: string
  ) => void;
}

interface FirstFrameDraft {
  prompt: string;
  source: string;
  image: string | null;
  fileName: string | null;
}

interface NextActionTarget {
  type: "generate" | "approve" | "compose" | "none";
  sceneId?: string;
  label: string;
  description: string;
}

function formatLabel(value: string) {
  return value.replace(/_/g, " ");
}

function formatPromptStaleReasons(reasons: string[] | undefined) {
  const labels = (reasons ?? []).map((reason) => {
    switch (reason) {
      case "first_frame_source_changed":
        return "first-frame source changed";
      case "first_frame_image_changed":
        return "first-frame image changed";
      case "continuity_frame_updated":
        return "continuity frame updated";
      default:
        return formatLabel(reason);
    }
  });
  return labels.join(", ");
}

function createDraft(scene: SceneRecord): FirstFrameDraft {
  return {
    prompt: scene.prompt,
    source: scene.first_frame_source,
    image: scene.first_frame_image ?? null,
    fileName: scene.first_frame_image ? "saved-image" : null
  };
}

function getLastUsedPrompt(scene: SceneRecord): string | null {
  const metadata = scene.video_job?.metadata;
  if (typeof metadata?.provider_prompt_snapshot === "string") {
    return metadata.provider_prompt_snapshot;
  }
  if (typeof metadata?.approved_prompt_snapshot === "string") {
    return metadata.approved_prompt_snapshot;
  }
  if (typeof metadata?.prompt_snapshot === "string") {
    return metadata.prompt_snapshot;
  }
  if (typeof scene.approved_prompt === "string" && scene.approved_prompt.trim()) {
    return scene.approved_prompt;
  }
  return null;
}

function isSceneGenerating(scene: SceneRecord): boolean {
  const jobStatus = scene.video_job?.status;
  return scene.status === "queued" || scene.status === "generating" || jobStatus === "queued" || jobStatus === "running";
}

function getSceneStageLabel(scene: SceneRecord): string {
  const jobStatus = scene.video_job?.status;
  if (jobStatus === "queued" || scene.status === "queued") {
    return "Waiting to start generation";
  }
  if (jobStatus === "running" || scene.status === "generating") {
    return "Generating scene";
  }
  if (scene.status === "pending_review") {
    return "Ready for review";
  }
  return "Preparing this scene";
}

function computeNextActionTarget(scenes: SceneRecord[], workflowMode: string, canCompose: boolean): NextActionTarget {
  if (workflowMode !== "hitl" || scenes.length === 0) {
    return {
      type: "none",
      label: "Waiting for scene planning",
      description: "Create and plan scenes before the guided review flow can continue."
    };
  }

  const pendingReview = scenes.find((scene) => (scene.available_actions ?? []).includes("approve"));
  if (pendingReview) {
    return {
      type: "approve",
      sceneId: pendingReview.scene_id,
      label: `Approve Scene ${pendingReview.index}`,
      description: "Review the generated scene and approve it to unlock the next beat."
    };
  }

  const nextGeneratable = scenes.find((scene) => (scene.available_actions ?? []).includes("generate"));
  if (nextGeneratable) {
    return {
      type: "generate",
      sceneId: nextGeneratable.scene_id,
      label: `Generate Scene ${nextGeneratable.index}`,
      description: "This is the next scene in sequence. Freeze the current setup and start generation."
    };
  }

  if (canCompose) {
    return {
      type: "compose",
      label: "Compose Final Video",
      description: "All required scenes are approved. Assemble the final cut now."
    };
  }

  return {
    type: "none",
    label: "Waiting for the next step",
    description: "Review completed scenes or wait for the next available action."
  };
}

function buildTimelineSummary(scene: SceneRecord): string {
  const stage = isSceneGenerating(scene) ? getSceneStageLabel(scene) : formatLabel(scene.review_status || scene.status);
  return `${scene.duration_seconds}s • ${stage}`;
}

export function SceneList({
  scenes,
  workflowMode,
  isPlanningBootstrap,
  planningStage,
  canCompose,
  isComposing,
  activeAction,
  onGenerate,
  onApprove,
  onCompose,
  onSavePrompt,
  onSaveFirstFrame
}: SceneListProps) {
  const [drafts, setDrafts] = useState<Record<string, FirstFrameDraft>>({});
  const [activeSceneId, setActiveSceneId] = useState<string | null>(null);
  const isHitl = workflowMode === "hitl";

  useEffect(() => {
    setDrafts((current) => {
      const nextDrafts: Record<string, FirstFrameDraft> = {};
      for (const scene of scenes) {
        const fresh = createDraft(scene);
        const existing = current[scene.scene_id];
        if (!existing) {
          nextDrafts[scene.scene_id] = fresh;
          continue;
        }
        const promptDirty = existing.prompt.trim() !== scene.prompt;
        const firstFrameDirty =
          existing.source !== scene.first_frame_source || (existing.image ?? null) !== (scene.first_frame_image ?? null);
        nextDrafts[scene.scene_id] = {
          prompt: promptDirty ? existing.prompt : fresh.prompt,
          source: firstFrameDirty ? existing.source : fresh.source,
          image: firstFrameDirty ? existing.image : fresh.image,
          fileName: firstFrameDirty ? existing.fileName : fresh.fileName
        };
      }
      return nextDrafts;
    });
  }, [scenes]);

  const nextAction = useMemo(
    () => computeNextActionTarget(scenes, workflowMode, canCompose),
    [scenes, workflowMode, canCompose]
  );

  useEffect(() => {
    const preferredSceneId =
      nextAction.sceneId ??
      scenes.find((scene) => isSceneGenerating(scene))?.scene_id ??
      scenes[0]?.scene_id ??
      null;

    setActiveSceneId((current) => {
      if (!preferredSceneId) {
        return null;
      }
      if (!current) {
        return preferredSceneId;
      }
      if (!scenes.some((scene) => scene.scene_id === current)) {
        return preferredSceneId;
      }
      if (nextAction.sceneId && current !== nextAction.sceneId) {
        return nextAction.sceneId;
      }
      return current;
    });
  }, [nextAction.sceneId, scenes]);

  function updateDraft(sceneId: string, patch: Partial<FirstFrameDraft>) {
    setDrafts((current) => ({
      ...current,
      [sceneId]: {
        ...(current[sceneId] ?? { prompt: "", source: "auto_generate", image: null, fileName: null }),
        ...patch
      }
    }));
  }

  function handleSourceChange(sceneId: string, source: string) {
    updateDraft(sceneId, {
      source,
      image: source === "upload" ? drafts[sceneId]?.image ?? null : null,
      fileName: source === "upload" ? drafts[sceneId]?.fileName ?? null : null
    });
  }

  function handleFileChange(sceneId: string, file: File | null) {
    if (!file) {
      updateDraft(sceneId, { image: null, fileName: null });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      updateDraft(sceneId, {
        source: "upload",
        image: typeof reader.result === "string" ? reader.result : null,
        fileName: file.name
      });
    };
    reader.readAsDataURL(file);
  }

  const activeScene = scenes.find((scene) => scene.scene_id === activeSceneId) ?? scenes[0] ?? null;

  function renderNextActionRail() {
    if (!isHitl || !scenes.length) {
      return null;
    }
    const nextActionSceneId = nextAction.sceneId ?? null;
    const isGenerating = nextAction.type === "generate" && activeAction?.action === "generate" && activeAction.sceneId === nextAction.sceneId;
    const isApproving = nextAction.type === "approve" && activeAction?.action === "approve" && activeAction.sceneId === nextAction.sceneId;

    return (
      <section className="next-action-rail">
        <div>
          <p className="eyebrow">Next Action</p>
          <h3>{nextAction.label}</h3>
          <p className="empty-copy">{nextAction.description}</p>
        </div>
        {nextAction.type === "generate" && nextActionSceneId ? (
          <button className="primary-button" onClick={() => onGenerate(nextActionSceneId)} disabled={Boolean(activeAction)}>
            {isGenerating ? "Generating..." : nextAction.label}
          </button>
        ) : null}
        {nextAction.type === "approve" && nextActionSceneId ? (
          <button className="primary-button" onClick={() => onApprove(nextActionSceneId)} disabled={Boolean(activeAction)}>
            {isApproving ? "Approving..." : nextAction.label}
          </button>
        ) : null}
        {nextAction.type === "compose" ? (
          <button className="primary-button" onClick={onCompose} disabled={isComposing || Boolean(activeAction)}>
            {isComposing ? "Composing..." : nextAction.label}
          </button>
        ) : null}
      </section>
    );
  }

  function renderSceneWorkspace(scene: SceneRecord) {
    const availableActions = scene.available_actions ?? [];
    const draft = drafts[scene.scene_id] ?? createDraft(scene);
    const isGenerating = activeAction?.sceneId === scene.scene_id && activeAction.action === "generate";
    const isApproving = activeAction?.sceneId === scene.scene_id && activeAction.action === "approve";
    const isSavingFirstFrame = activeAction?.sceneId === scene.scene_id && activeAction.action === "save_first_frame";
    const isSavingPrompt = activeAction?.sceneId === scene.scene_id && activeAction.action === "save_prompt";
    const sceneIsGenerating = isSceneGenerating(scene);
    const isFirstFrameDirty =
      draft.source !== scene.first_frame_source || (draft.image ?? null) !== (scene.first_frame_image ?? null);
    const isPromptDirty = draft.prompt.trim() !== scene.prompt;
    const hasUnsavedChanges = isFirstFrameDirty || isPromptDirty;
    const canSaveFirstFrame = draft.source !== "upload" || Boolean(draft.image);
    const firstFramePreview = draft.source === "upload" ? draft.image : scene.first_frame_url ?? null;
    const staleReasonSummary = formatPromptStaleReasons(scene.prompt_stale_reasons);
    const lastUsedPrompt = getLastUsedPrompt(scene);
    const frozenPrompt = lastUsedPrompt ?? scene.approved_prompt ?? scene.prompt;
    const isCurrentNext = nextAction.sceneId === scene.scene_id;

    return (
      <article className="scene-workspace-card">
        <div className="scene-card-header">
          <div>
            <span className="scene-index">Scene {scene.index}</span>
            <h3>{scene.title}</h3>
          </div>
          <div className="scene-status-group">
            {isCurrentNext ? <span className="timeline-chip">Next</span> : null}
            <span className={`status-pill status-${scene.status}`}>{formatLabel(scene.status)}</span>
          </div>
        </div>

        <p className="scene-copy">{scene.narrative}</p>

        <div className="scene-meta">
          <span>{scene.duration_seconds}s</span>
          <span>{formatLabel(scene.generation_mode)}</span>
          <span>{formatLabel(scene.first_frame_source)}</span>
        </div>

        <div className="scene-meta">
          <span>Review {formatLabel(scene.review_status)}</span>
          <span>{scene.video_job?.provider_task_id ? "generation started" : "not started yet"}</span>
          <span>{scene.video_url ? "video ready" : sceneIsGenerating ? getSceneStageLabel(scene) : "video pending"}</span>
        </div>

        {sceneIsGenerating ? (
          <div className="scene-runtime-panel">
            <div className="scene-runtime-header">
              <div>
                <p className="eyebrow">Generating</p>
                <h4>{scene.title}</h4>
              </div>
              <span className={`status-pill status-${scene.video_job?.status ?? scene.status}`}>{getSceneStageLabel(scene)}</span>
            </div>
            <div className="scene-runtime-body">
              {firstFramePreview ? (
                <img className="scene-frame scene-first-frame-preview" src={firstFramePreview} alt={`${scene.title} frozen first frame`} />
              ) : (
                <div className="scene-frame scene-runtime-skeleton">Preparing the opening frame and generation request…</div>
              )}
              <div className="scene-runtime-copy">
                <p className="scene-panel-title">Frozen Prompt</p>
                <div className="scene-prompt-snapshot">{frozenPrompt}</div>
                <div className="scene-runtime-track">
                  <div className="scene-runtime-bar" />
                </div>
              </div>
            </div>
          </div>
        ) : scene.video_url ? (
          <video className="scene-video" src={scene.video_url} controls preload="metadata" />
        ) : scene.final_frame_url ? (
          <img className="scene-frame" src={scene.final_frame_url} alt={`${scene.title} final frame`} />
        ) : (
          <div className="scene-frame scene-frame-empty">Scene preview will appear after generation.</div>
        )}

        {isHitl ? (
          <>
            <div className="scene-first-frame-panel">
              <p className="scene-panel-title">Scene Prompt</p>
              <label className="field">
                <span>Current prompt for the next generation</span>
                <textarea
                  rows={5}
                  value={draft.prompt}
                  onChange={(event) => updateDraft(scene.scene_id, { prompt: event.target.value })}
                  disabled={Boolean(activeAction) || scene.status === "approved"}
                />
              </label>
              {scene.prompt_stale ? (
                <div className="scene-first-frame-summary scene-first-frame-summary-warning">
                  <span>
                    Scene setup changed after this prompt was saved.
                    {staleReasonSummary ? ` Review it before generating again: ${staleReasonSummary}.` : ""}
                  </span>
                </div>
              ) : null}
              {isPromptDirty ? (
                <div className="scene-first-frame-summary">
                  <span>Apply changes before generating this scene.</span>
                </div>
              ) : null}
              <div className="scene-first-frame-summary">
                <span>
                  {lastUsedPrompt
                    ? "Last Used Prompt"
                    : "This prompt will be frozen and used when you click Generate Scene."}
                </span>
              </div>
              {lastUsedPrompt ? <div className="scene-prompt-snapshot">{lastUsedPrompt}</div> : null}
              <button
                className="secondary-button"
                onClick={() => onSavePrompt(scene.scene_id, draft.prompt)}
                disabled={!isPromptDirty || !draft.prompt.trim() || Boolean(activeAction) || scene.status === "approved"}
              >
                {isSavingPrompt ? "Applying..." : "Apply Changes"}
              </button>
            </div>

            <div className="scene-first-frame-panel">
              <p className="scene-panel-title">First Frame Setup</p>
              <label className="field">
                <span>Source</span>
                <select
                  value={draft.source}
                  onChange={(event) => handleSourceChange(scene.scene_id, event.target.value)}
                  disabled={Boolean(activeAction)}
                >
                  <option value="auto_generate">Auto generate</option>
                  {scene.index > 1 ? <option value="continuity">Previous scene continuity</option> : null}
                  <option value="upload">Upload first frame</option>
                </select>
              </label>

              {draft.source === "upload" ? (
                <label className="field">
                  <span>Upload Image</span>
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    onChange={(event) => handleFileChange(scene.scene_id, event.target.files?.[0] ?? null)}
                    disabled={Boolean(activeAction)}
                  />
                </label>
              ) : null}

              <div className="scene-first-frame-summary">
                <span>
                  {draft.source === "auto_generate"
                    ? scene.first_frame_url
                      ? "A generated first frame is ready and will be used as the opening still."
                      : "No generated still yet. The workflow will prepare one before generation."
                    : draft.source === "continuity"
                      ? "Use the previous scene final frame as the scene start reference."
                      : draft.fileName
                        ? `Selected file: ${draft.fileName}`
                        : "Upload an image to lock the opening frame."}
                </span>
              </div>

              {draft.source === "auto_generate" && scene.first_frame_prompt ? (
                <div className="scene-first-frame-summary">
                  <span>Generated still prompt: {scene.first_frame_prompt}</span>
                </div>
              ) : null}

              {firstFramePreview ? (
                <img className="scene-frame scene-first-frame-preview" src={firstFramePreview} alt={`${scene.title} first frame draft`} />
              ) : null}

              <button
                className="secondary-button"
                onClick={() =>
                  onSaveFirstFrame(
                    scene.scene_id,
                    draft.source,
                    draft.source === "upload" ? draft.image : null,
                    scene.storyboard_notes ?? ""
                  )
                }
                disabled={!isFirstFrameDirty || !canSaveFirstFrame || Boolean(activeAction)}
              >
                {isSavingFirstFrame ? "Saving..." : "Save First Frame"}
              </button>
            </div>
          </>
        ) : null}

        {isHitl ? (
          <div className="scene-actions">
            <button
              className="primary-button"
              onClick={() => onGenerate(scene.scene_id)}
              disabled={!availableActions.includes("generate") || Boolean(activeAction) || hasUnsavedChanges}
            >
              {isGenerating ? "Generating..." : "Generate Scene"}
            </button>
            <button
              className="secondary-button"
              onClick={() => onApprove(scene.scene_id)}
              disabled={!availableActions.includes("approve") || Boolean(activeAction)}
            >
              {isApproving ? "Approving..." : "Approve Scene"}
            </button>
          </div>
        ) : null}
      </article>
    );
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Scene Workspace</p>
          <h2>{isHitl ? "Scene Review" : "Scene Progress"}</h2>
        </div>
        <span className="panel-badge">{scenes.length}</span>
      </div>

      {!scenes.length ? (
        isPlanningBootstrap ? (
          <div className="planning-status-card planning-status-inline">
            <div className="planning-status-head">
              <div>
                <span className="meta-label">Scene Workspace Pending</span>
                <strong>
                  {planningStage === "creating_project"
                    ? "Understanding brief"
                    : planningStage === "global_planning"
                      ? "Planning story flow"
                      : "Building scene flow"}
                </strong>
              </div>
            </div>
            <p className="empty-copy">
              Scene 1 and the review workspace will appear after planning finishes. This step can take a while while
              the system understands your brief and builds the first round of scene plans.
            </p>
          </div>
        ) : (
          <p className="empty-copy">Scenes will appear after planning finishes.</p>
        )
      ) : (
        <div className="scene-review-shell">
          <aside className="scene-timeline">
            <div className="scene-timeline-list">
              {scenes.map((scene) => {
                const isActive = activeScene?.scene_id === scene.scene_id;
                const isNext = nextAction.sceneId === scene.scene_id;
                const timelineStatus = isSceneGenerating(scene) ? getSceneStageLabel(scene) : formatLabel(scene.status);
                return (
                  <button
                    key={scene.scene_id}
                    type="button"
                    className={`scene-timeline-item${isActive ? " scene-timeline-item-active" : ""}`}
                    onClick={() => setActiveSceneId(scene.scene_id)}
                  >
                    <div className="scene-timeline-copy">
                      <span className="scene-index">Scene {scene.index}</span>
                      <strong>{scene.title}</strong>
                      <p>{buildTimelineSummary(scene)}</p>
                    </div>
                    <div className="scene-timeline-meta">
                      {isNext ? <span className="timeline-chip">Next</span> : null}
                      <span className={`status-pill status-${scene.status}`}>{timelineStatus}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>

          <div className="scene-workspace">
            {renderNextActionRail()}
            {activeScene ? renderSceneWorkspace(activeScene) : null}
          </div>
        </div>
      )}
    </section>
  );
}
