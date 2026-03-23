import { useEffect, useMemo, useState } from "react";
import type { SceneRecord } from "../api/client";
import { formatEnumLabel, type Messages } from "../i18n/catalog";
import { useI18n } from "../i18n/provider";

interface SceneListProps {
  scenes: SceneRecord[];
  workflowMode: string;
  isPlanningBootstrap: boolean;
  planningStage: "idle" | "creating_project" | "global_planning" | "scene_planning";
  canCompose: boolean;
  isComposing: boolean;
  activeAction: {
    sceneId: string;
    action: "generate" | "approve" | "save_first_frame" | "save_prompt" | "revise_prompt";
  } | null;
  onGenerate: (sceneId: string) => void;
  onApprove: (sceneId: string) => void;
  onCompose: () => void;
  onSavePrompt: (sceneId: string, prompt: string) => void;
  onRevisePrompt: (sceneId: string, feedback: string, scope: "prompt_only" | "opening_still_and_prompt") => void;
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

interface FeedbackDraft {
  feedback: string;
  scope: "prompt_only" | "opening_still_and_prompt";
}

interface NextActionTarget {
  type: "generate" | "approve" | "compose" | "none";
  sceneId?: string;
  label: string;
  description: string;
}

function formatLabel(value: string, messages: Messages) {
  return formatEnumLabel(value, messages.enums);
}

function formatPromptStaleReasons(reasons: string[] | undefined, messages: Messages) {
  const labels = (reasons ?? []).map((reason) => {
    switch (reason) {
      case "first_frame_source_changed":
        return messages.sceneList.staleReasonFirstFrameSourceChanged;
      case "first_frame_image_changed":
        return messages.sceneList.staleReasonFirstFrameImageChanged;
      case "continuity_frame_updated":
        return messages.sceneList.staleReasonContinuityFrameUpdated;
      default:
        return formatLabel(reason, messages);
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

function createFeedbackDraft(scene: SceneRecord): FeedbackDraft {
  return {
    feedback: "",
    scope: scene.index === 1 && scene.first_frame_source === "auto_generate" ? "prompt_only" : "prompt_only"
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

function getSceneStageLabel(scene: SceneRecord, messages: Messages): string {
  const jobStatus = scene.video_job?.status;
  if (jobStatus === "queued" || scene.status === "queued") {
    return messages.sceneList.stageWaitingToStart;
  }
  if (jobStatus === "running" || scene.status === "generating") {
    return messages.sceneList.stageGenerating;
  }
  if (scene.status === "pending_review") {
    return messages.sceneList.stageReadyForReview;
  }
  return messages.sceneList.stagePreparing;
}

function computeNextActionTarget(
  scenes: SceneRecord[],
  workflowMode: string,
  canCompose: boolean,
  messages: Messages
): NextActionTarget {
  if (workflowMode !== "hitl" || scenes.length === 0) {
    return {
      type: "none",
      label: messages.sceneList.waitingForPlanningLabel,
      description: messages.sceneList.waitingForPlanningDescription
    };
  }

  const pendingReview = scenes.find((scene) => (scene.available_actions ?? []).includes("approve"));
  if (pendingReview) {
    return {
      type: "approve",
      sceneId: pendingReview.scene_id,
      label: messages.sceneList.approveSceneLabel(pendingReview.index),
      description: messages.sceneList.approveSceneDescription
    };
  }

  const nextGeneratable = scenes.find((scene) => (scene.available_actions ?? []).includes("generate"));
  if (nextGeneratable) {
    return {
      type: "generate",
      sceneId: nextGeneratable.scene_id,
      label: messages.sceneList.generateSceneLabel(nextGeneratable.index),
      description: messages.sceneList.generateSceneDescription
    };
  }

  if (canCompose) {
    return {
      type: "compose",
      label: messages.sceneList.composeLabel,
      description: messages.sceneList.composeDescription
    };
  }

  return {
    type: "none",
    label: messages.sceneList.waitingNextStepLabel,
    description: messages.sceneList.waitingNextStepDescription
  };
}

function buildTimelineSummary(scene: SceneRecord, messages: Messages): string {
  const stage = isSceneGenerating(scene)
    ? getSceneStageLabel(scene, messages)
    : formatLabel(scene.review_status || scene.status, messages);
  return messages.sceneList.timelineSummary(scene.duration_seconds, stage);
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
  onRevisePrompt,
  onSaveFirstFrame
}: SceneListProps) {
  const { messages } = useI18n();
  const [drafts, setDrafts] = useState<Record<string, FirstFrameDraft>>({});
  const [feedbackDrafts, setFeedbackDrafts] = useState<Record<string, FeedbackDraft>>({});
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

  useEffect(() => {
    setFeedbackDrafts((current) => {
      const nextDrafts: Record<string, FeedbackDraft> = {};
      for (const scene of scenes) {
        const fresh = createFeedbackDraft(scene);
        const existing = current[scene.scene_id];
        if (!existing) {
          nextDrafts[scene.scene_id] = fresh;
          continue;
        }
        const supportsOpeningScope = scene.index === 1 && scene.first_frame_source === "auto_generate";
        nextDrafts[scene.scene_id] = {
          feedback: existing.feedback,
          scope: supportsOpeningScope ? existing.scope : "prompt_only"
        };
      }
      return nextDrafts;
    });
  }, [scenes]);

  const nextAction = useMemo(
    () => computeNextActionTarget(scenes, workflowMode, canCompose, messages),
    [scenes, workflowMode, canCompose, messages]
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

  function updateFeedbackDraft(sceneId: string, patch: Partial<FeedbackDraft>) {
    setFeedbackDrafts((current) => ({
      ...current,
      [sceneId]: {
        ...(current[sceneId] ?? { feedback: "", scope: "prompt_only" }),
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
          <p className="eyebrow">{messages.sceneList.nextActionEyebrow}</p>
          <h3>{nextAction.label}</h3>
          <p className="empty-copy">{nextAction.description}</p>
        </div>
        {nextAction.type === "generate" && nextActionSceneId ? (
          <button className="primary-button" onClick={() => onGenerate(nextActionSceneId)} disabled={Boolean(activeAction)}>
            {isGenerating ? messages.sceneList.generating : nextAction.label}
          </button>
        ) : null}
        {nextAction.type === "approve" && nextActionSceneId ? (
          <button className="primary-button" onClick={() => onApprove(nextActionSceneId)} disabled={Boolean(activeAction)}>
            {isApproving ? messages.sceneList.approving : nextAction.label}
          </button>
        ) : null}
        {nextAction.type === "compose" ? (
          <button className="primary-button" onClick={onCompose} disabled={isComposing || Boolean(activeAction)}>
            {isComposing ? messages.workflowStatus.composing : nextAction.label}
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
    const isRevisingPrompt = activeAction?.sceneId === scene.scene_id && activeAction.action === "revise_prompt";
    const sceneIsGenerating = isSceneGenerating(scene);
    const isFirstFrameDirty =
      draft.source !== scene.first_frame_source || (draft.image ?? null) !== (scene.first_frame_image ?? null);
    const isPromptDirty = draft.prompt.trim() !== scene.prompt;
    const hasUnsavedChanges = isFirstFrameDirty || isPromptDirty;
    const canSaveFirstFrame = draft.source !== "upload" || Boolean(draft.image);
    const firstFramePreview = draft.source === "upload" ? draft.image : scene.first_frame_url ?? null;
    const staleReasonSummary = formatPromptStaleReasons(scene.prompt_stale_reasons, messages);
    const lastUsedPrompt = getLastUsedPrompt(scene);
    const frozenPrompt = lastUsedPrompt ?? scene.approved_prompt ?? scene.prompt;
    const isCurrentNext = nextAction.sceneId === scene.scene_id;
    const feedbackDraft = feedbackDrafts[scene.scene_id] ?? createFeedbackDraft(scene);
    const supportsOpeningStillRevision = scene.index === 1 && scene.first_frame_source === "auto_generate";
    const canRunFeedbackRevision = Boolean(feedbackDraft.feedback.trim()) && !hasUnsavedChanges;

    return (
      <article className="scene-workspace-card">
        <div className="scene-card-header">
          <div>
            <span className="scene-index">{messages.sceneList.sceneIndex(scene.index)}</span>
            <h3>{scene.title}</h3>
          </div>
          <div className="scene-status-group">
            {isCurrentNext ? <span className="timeline-chip">{messages.sceneList.nextChip}</span> : null}
            <span className={`status-pill status-${scene.status}`}>{formatLabel(scene.status, messages)}</span>
          </div>
        </div>

        <p className="scene-copy">{scene.narrative}</p>

        <div className="scene-meta">
          <span>{scene.duration_seconds}s</span>
          <span>{formatLabel(scene.generation_mode, messages)}</span>
          <span>{formatLabel(scene.first_frame_source, messages)}</span>
        </div>

        <div className="scene-meta">
          <span>{messages.sceneList.reviewStatus(formatLabel(scene.review_status, messages))}</span>
          <span>{scene.video_job?.provider_task_id ? messages.sceneList.generationStarted : messages.sceneList.notStartedYet}</span>
          <span>
            {scene.video_url
              ? messages.sceneList.videoReady
              : sceneIsGenerating
                ? getSceneStageLabel(scene, messages)
                : messages.sceneList.videoPending}
          </span>
        </div>

        {sceneIsGenerating ? (
          <div className="scene-runtime-panel">
            <div className="scene-runtime-header">
              <div>
                <p className="eyebrow">{messages.sceneList.generatingEyebrow}</p>
                <h4>{scene.title}</h4>
              </div>
              <span className={`status-pill status-${scene.video_job?.status ?? scene.status}`}>
                {getSceneStageLabel(scene, messages)}
              </span>
            </div>
            <div className="scene-runtime-body">
              {firstFramePreview ? (
                <img className="scene-frame scene-first-frame-preview" src={firstFramePreview} alt={`${scene.title} frozen first frame`} />
              ) : (
                <div className="scene-frame scene-runtime-skeleton">{messages.sceneList.preparingRequest}</div>
              )}
              <div className="scene-runtime-copy">
                <p className="scene-panel-title">{messages.sceneList.frozenPrompt}</p>
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
          <div className="scene-frame scene-frame-empty">{messages.sceneList.previewPending}</div>
        )}

        {isHitl ? (
          <>
            <div className="scene-first-frame-panel">
              <p className="scene-panel-title">{messages.sceneList.scenePromptTitle}</p>
              <label className="field">
                <span>{messages.sceneList.currentPromptLabel}</span>
                <textarea
                  rows={5}
                  value={draft.prompt}
                  onChange={(event) => updateDraft(scene.scene_id, { prompt: event.target.value })}
                  disabled={Boolean(activeAction) || scene.status === "approved"}
                />
              </label>
              {scene.prompt_stale ? (
                <div className="scene-first-frame-summary scene-first-frame-summary-warning">
                  <span>{messages.sceneList.stalePrompt(staleReasonSummary)}</span>
                </div>
              ) : null}
              {isPromptDirty ? (
                <div className="scene-first-frame-summary">
                  <span>{messages.sceneList.applyChangesBeforeGenerating}</span>
                </div>
              ) : null}
              <div className="scene-first-frame-summary">
                <span>
                  {lastUsedPrompt ? messages.sceneList.lastUsedPrompt : messages.sceneList.promptFreezeHint}
                </span>
              </div>
              {lastUsedPrompt ? <div className="scene-prompt-snapshot">{lastUsedPrompt}</div> : null}
              <button
                className="secondary-button"
                onClick={() => onSavePrompt(scene.scene_id, draft.prompt)}
                disabled={!isPromptDirty || !draft.prompt.trim() || Boolean(activeAction) || scene.status === "approved"}
              >
                {isSavingPrompt ? messages.sceneList.applying : messages.sceneList.applyChanges}
              </button>
            </div>

            <div className="scene-first-frame-panel">
              <p className="scene-panel-title">{messages.sceneList.feedbackRevisionTitle}</p>
              <label className="field">
                <span>{messages.sceneList.feedbackRevisionLabel}</span>
                <textarea
                  rows={3}
                  value={feedbackDraft.feedback}
                  placeholder={messages.sceneList.feedbackRevisionPlaceholder}
                  onChange={(event) => updateFeedbackDraft(scene.scene_id, { feedback: event.target.value })}
                  disabled={Boolean(activeAction) || scene.status === "approved"}
                />
              </label>
              {supportsOpeningStillRevision ? (
                <label className="field">
                  <span>{messages.sceneList.feedbackScopeLabel}</span>
                  <select
                    value={feedbackDraft.scope}
                    onChange={(event) =>
                      updateFeedbackDraft(scene.scene_id, {
                        scope: event.target.value as "prompt_only" | "opening_still_and_prompt"
                      })
                    }
                    disabled={Boolean(activeAction) || scene.status === "approved"}
                  >
                    <option value="prompt_only">{messages.sceneList.feedbackScopePromptOnly}</option>
                    <option value="opening_still_and_prompt">
                      {messages.sceneList.feedbackScopeOpeningStillAndPrompt}
                    </option>
                  </select>
                </label>
              ) : (
                <div className="scene-first-frame-summary">
                  <span>{messages.sceneList.feedbackScopePromptOnlyHint}</span>
                </div>
              )}
              {hasUnsavedChanges ? (
                <div className="scene-first-frame-summary">
                  <span>{messages.sceneList.applyChangesBeforeRevising}</span>
                </div>
              ) : null}
              <button
                className="secondary-button"
                onClick={() => onRevisePrompt(scene.scene_id, feedbackDraft.feedback.trim(), feedbackDraft.scope)}
                disabled={!canRunFeedbackRevision || Boolean(activeAction) || scene.status === "approved"}
              >
                {isRevisingPrompt ? messages.sceneList.revising : messages.sceneList.reviseFromFeedback}
              </button>
            </div>

            <div className="scene-first-frame-panel">
              <p className="scene-panel-title">{messages.sceneList.firstFrameTitle}</p>
              <label className="field">
                <span>{messages.sceneList.sourceLabel}</span>
                <select
                  value={draft.source}
                  onChange={(event) => handleSourceChange(scene.scene_id, event.target.value)}
                  disabled={Boolean(activeAction)}
                >
                  <option value="auto_generate">{messages.sceneList.sourceAutoGenerate}</option>
                  {scene.index > 1 ? <option value="continuity">{messages.sceneList.sourceContinuity}</option> : null}
                  <option value="upload">{messages.sceneList.sourceUpload}</option>
                </select>
              </label>

              {draft.source === "upload" ? (
                <label className="field">
                  <span>{messages.sceneList.uploadImage}</span>
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
                      ? messages.sceneList.firstFrameAutoReady
                      : messages.sceneList.firstFrameAutoPending
                    : draft.source === "continuity"
                      ? messages.sceneList.firstFrameContinuity
                      : draft.fileName
                        ? messages.projectForm.selectedFile(draft.fileName)
                        : messages.sceneList.firstFrameUploadHint}
                </span>
              </div>

              {draft.source === "auto_generate" && scene.first_frame_prompt ? (
                <div className="scene-first-frame-summary">
                  <span>{messages.sceneList.generatedStillPrompt(scene.first_frame_prompt)}</span>
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
                {isSavingFirstFrame ? messages.sceneList.saving : messages.sceneList.saveFirstFrame}
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
              {isGenerating ? messages.sceneList.generating : messages.sceneList.generateScene}
            </button>
            <button
              className="secondary-button"
              onClick={() => onApprove(scene.scene_id)}
              disabled={!availableActions.includes("approve") || Boolean(activeAction)}
            >
              {isApproving ? messages.sceneList.approving : messages.sceneList.approveScene}
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
          <p className="eyebrow">{messages.sceneList.sceneWorkspaceEyebrow}</p>
          <h2>{isHitl ? messages.sceneList.sceneReviewTitle : messages.sceneList.sceneProgressTitle}</h2>
        </div>
        <span className="panel-badge">{scenes.length}</span>
      </div>

      {!scenes.length ? (
        isPlanningBootstrap ? (
          <div className="planning-status-card planning-status-inline">
            <div className="planning-status-head">
              <div>
                <span className="meta-label">{messages.sceneList.pendingWorkspaceEyebrow}</span>
                <strong>
                  {planningStage === "creating_project"
                    ? messages.workflowStatus.bootstrapUnderstand
                    : planningStage === "global_planning"
                      ? messages.sceneList.pendingStageStory
                      : messages.sceneList.pendingStageScenes}
                </strong>
              </div>
            </div>
            <p className="empty-copy">{messages.sceneList.pendingDescription}</p>
          </div>
        ) : (
          <p className="empty-copy">{messages.sceneList.scenesAppearLater}</p>
        )
      ) : (
        <div className="scene-review-shell">
          <aside className="scene-timeline">
            <div className="scene-timeline-list">
              {scenes.map((scene) => {
                const isActive = activeScene?.scene_id === scene.scene_id;
                const isNext = nextAction.sceneId === scene.scene_id;
                const timelineStatus = isSceneGenerating(scene)
                  ? getSceneStageLabel(scene, messages)
                  : formatLabel(scene.status, messages);
                return (
                  <button
                    key={scene.scene_id}
                    type="button"
                    className={`scene-timeline-item${isActive ? " scene-timeline-item-active" : ""}`}
                    onClick={() => setActiveSceneId(scene.scene_id)}
                  >
                    <div className="scene-timeline-copy">
                      <span className="scene-index">{messages.sceneList.sceneIndex(scene.index)}</span>
                      <strong>{scene.title}</strong>
                      <p>{buildTimelineSummary(scene, messages)}</p>
                    </div>
                    <div className="scene-timeline-meta">
                      {isNext ? <span className="timeline-chip">{messages.sceneList.nextChip}</span> : null}
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
