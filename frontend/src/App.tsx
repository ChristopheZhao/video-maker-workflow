import { useEffect, useReducer } from "react";
import {
  approveCharacterReference,
  approveScene,
  composeProject,
  createProject,
  exportSubtitledVideo,
  generateCharacterReference,
  generateScene,
  getWorkflowStatus,
  listProviders,
  optimizePrompt,
  planScenes,
  reviseScenePrompt,
  startWorkflow,
  uploadCharacterReference,
  updateScenePrompt
} from "./api/client";
import { uploadStoryboards } from "./api/client";
import { CharacterLookdevPanel } from "./components/CharacterLookdevPanel";
import { FinalVideoPanel } from "./components/FinalVideoPanel";
import { ProjectForm } from "./components/ProjectForm";
import { SceneList } from "./components/SceneList";
import { WorkflowStatusCard } from "./components/WorkflowStatusCard";
import { useI18n } from "./i18n/provider";
import {
  createInitialState,
  shouldPollProject,
  reducer,
  type ProjectFormState
} from "./state/project-store";

const POLL_INTERVAL_MS = 2500;

function distributeDuration(totalDurationSeconds: number, sceneCount: number): number[] {
  const normalizedSceneCount = Math.max(1, sceneCount);
  const base = Math.floor(totalDurationSeconds / normalizedSceneCount);
  const remainder = totalDurationSeconds % normalizedSceneCount;
  return Array.from({ length: normalizedSceneCount }, (_, index) => base + (index < remainder ? 1 : 0));
}

function parseSceneDurationBounds(capabilities: Record<string, unknown> | undefined): [number, number] | null {
  const minDuration = capabilities?.["min_scene_duration_seconds"];
  const maxDuration = capabilities?.["max_scene_duration_seconds"];
  if (typeof minDuration !== "number" || typeof maxDuration !== "number") {
    return null;
  }
  const normalizedMin = Math.trunc(minDuration);
  const normalizedMax = Math.trunc(maxDuration);
  if (normalizedMin <= 0 || normalizedMax < normalizedMin) {
    return null;
  }
  return [normalizedMin, normalizedMax];
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, undefined, createInitialState);
  const { locale, setLocale, messages } = useI18n();

  useEffect(() => {
    let cancelled = false;

    async function loadProviders() {
      dispatch({ type: "providers/load-start" });
      try {
        const providers = await listProviders();
        if (!cancelled) {
          dispatch({ type: "providers/load-success", providers });
        }
      } catch (error) {
        if (!cancelled) {
          dispatch({
            type: "providers/load-failure",
            message: error instanceof Error ? error.message : messages.app.providerLoadFailed
          });
        }
      }
    }

    void loadProviders();
    return () => {
      cancelled = true;
    };
  }, []);

  const currentProject = state.workflowStatus?.project ?? state.project;
  const shouldPoll = shouldPollProject(currentProject, state.workflowStatus);

  useEffect(() => {
    if (!shouldPoll || !currentProject?.project_id) {
      return undefined;
    }

    let cancelled = false;
    const syncWorkflowStatus = () => {
      void getWorkflowStatus(currentProject.project_id)
        .then((status) => {
          if (!cancelled) {
            dispatch({ type: "workflow/status-update", status });
          }
        })
        .catch((error) => {
          if (!cancelled) {
            dispatch({
              type: "ui/error",
              message: error instanceof Error ? error.message : messages.app.workflowRefreshFailed
            });
          }
        });
    };

    syncWorkflowStatus();
    const intervalId = window.setInterval(syncWorkflowStatus, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [currentProject?.project_id, shouldPoll]);

  const selectedProvider = state.providers.find((provider) => provider.name === state.form.provider) ?? null;
  const projectDurationValidationMessage = (() => {
    const bounds = parseSceneDurationBounds(selectedProvider?.capabilities);
    if (!bounds) {
      return null;
    }
    const [minDuration, maxDuration] = bounds;
    const targetDurationSeconds = Math.max(5, Number(state.form.targetDurationSeconds));
    const sceneCount = Math.max(1, Number(state.form.sceneCount));
    const durations = distributeDuration(targetDurationSeconds, sceneCount);
    if (durations.every((duration) => duration >= minDuration && duration <= maxDuration)) {
      return null;
    }
    return messages.app.durationValidation({
      targetDurationSeconds,
      sceneCount,
      durations,
      minDuration,
      maxDuration
    });
  })();

  async function handleCreateProject() {
    if (state.form.scene1FirstFrameSource === "upload" && !state.form.scene1FirstFrameImage) {
      dispatch({
        type: "ui/error",
        message: messages.app.uploadScene1FirstFrameBeforeCreate
      });
      return;
    }
    if (projectDurationValidationMessage) {
      dispatch({
        type: "ui/error",
        message: projectDurationValidationMessage
      });
      return;
    }
    dispatch({ type: "project/create-start" });
    try {
        let project = await createProject({
        title: state.form.title,
        prompt: state.form.prompt,
        target_duration_seconds: Math.max(5, Number(state.form.targetDurationSeconds)),
        provider: state.form.provider,
        scene_count: Math.max(1, Number(state.form.sceneCount)),
        workflow_mode: state.form.workflowMode,
        subtitle_mode: state.form.subtitleMode,
        scene1_first_frame_source: state.form.scene1FirstFrameSource,
        scene1_first_frame_image:
          state.form.scene1FirstFrameSource === "upload" ? state.form.scene1FirstFrameImage : null,
        scene1_first_frame_prompt:
          state.form.scene1FirstFrameSource === "auto_generate"
            ? state.form.scene1FirstFramePrompt.trim() || undefined
            : ""
      });
      dispatch({
        type: "project/create-progress",
        project,
        stage: "global_planning",
        message: messages.app.projectCreateProgressGlobal(project.project_id)
      });
      if (project.workflow_mode === "hitl") {
        project = await optimizePrompt(project.project_id);
        dispatch({
          type: "project/create-progress",
          project,
          stage: "scene_planning",
          message: messages.app.projectCreateProgressScenes(project.project_id)
        });
        project = await planScenes(project.project_id);
      }
      dispatch({ type: "project/create-success", project, message: messages.app.projectCreated(project.project_id) });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.projectCreationFailed
      });
    }
  }

  async function handleStartWorkflow() {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeStartingWorkflow });
      return;
    }
    dispatch({ type: "workflow/start-start" });
    try {
      const project = await startWorkflow(currentProject.project_id);
      dispatch({ type: "workflow/start-success", project, message: messages.app.workflowQueued(project.project_id) });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.workflowStartFailed
      });
    }
  }

  async function handleGenerateScene(sceneId: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeGeneratingScenes });
      return;
    }
    dispatch({ type: "scene/action-start", sceneId, action: "generate" });
    try {
      const project = await generateScene(currentProject.project_id, sceneId);
      dispatch({
        type: "scene/action-success",
        project,
        message: messages.app.sceneQueued(sceneId)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.sceneGenerationFailed
      });
    }
  }

  async function handleApproveScene(sceneId: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeApprovingScenes });
      return;
    }
    dispatch({ type: "scene/action-start", sceneId, action: "approve" });
    try {
      const project = await approveScene(currentProject.project_id, sceneId);
      dispatch({
        type: "scene/action-success",
        project,
        message: messages.app.sceneApproved(sceneId)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.sceneApprovalFailed
      });
    }
  }

  async function handleSaveFirstFrame(
    sceneId: string,
    firstFrameSource: string,
    firstFrameImage: string | null,
    storyboardNotes: string
  ) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeSavingFirstFrame });
      return;
    }
    dispatch({ type: "scene/action-start", sceneId, action: "save_first_frame" });
    try {
      const project = await uploadStoryboards(currentProject.project_id, [
        {
          scene_id: sceneId,
          first_frame_source: firstFrameSource,
          first_frame_image: firstFrameSource === "upload" ? firstFrameImage : null,
          storyboard_notes: storyboardNotes
        }
      ]);
      dispatch({
        type: "scene/action-success",
        project,
        message: messages.app.firstFrameSaved(sceneId)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.saveFirstFrameFailed
      });
    }
  }

  async function handleSaveScenePrompt(sceneId: string, prompt: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeSavingScenePrompt });
      return;
    }
    dispatch({ type: "scene/action-start", sceneId, action: "save_prompt" });
    try {
      const project = await updateScenePrompt(currentProject.project_id, sceneId, { prompt });
      dispatch({
        type: "scene/action-success",
        project,
        message: messages.app.promptChangesApplied(sceneId)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.saveScenePromptFailed
      });
    }
  }

  async function handleReviseScenePrompt(
    sceneId: string,
    feedback: string,
    scope: "prompt_only" | "opening_still_and_prompt"
  ) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeRevisingScenePrompt });
      return;
    }
    dispatch({ type: "scene/action-start", sceneId, action: "revise_prompt" });
    try {
      const project = await reviseScenePrompt(currentProject.project_id, sceneId, { feedback, scope });
      dispatch({
        type: "scene/action-success",
        project,
        message: messages.app.promptFeedbackApplied(sceneId)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.reviseScenePromptFailed
      });
    }
  }

  async function handleComposeProject() {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeCompose });
      return;
    }
    dispatch({ type: "compose/start" });
    try {
      const project = await composeProject(currentProject.project_id);
      dispatch({
        type: "compose/success",
        project,
        message: messages.app.finalVideoComposed(project.project_id)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.finalCompositionFailed
      });
    }
  }

  async function handleExportSubtitledVideo() {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeCompose });
      return;
    }
    try {
      const project = await exportSubtitledVideo(currentProject.project_id);
      dispatch({
        type: "ui/notice",
        message: messages.app.subtitledVideoExportQueued(project.project_id)
      });
      dispatch({
        type: "workflow/status-update",
        status: {
          project_id: project.project_id,
          project_status: project.status,
          workflow_run_job: project.workflow_run_job ?? null,
          project
        }
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.subtitledVideoExportFailed
      });
    }
  }

  async function handleGenerateCharacterReference(characterId: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeGeneratingCharacterReferences });
      return;
    }
    dispatch({ type: "character/action-start", characterId, action: "generate_reference" });
    try {
      const project = await generateCharacterReference(currentProject.project_id, characterId);
      dispatch({
        type: "character/action-success",
        project,
        message: messages.app.characterReferenceGenerated(characterId)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.characterReferenceGenerationFailed
      });
    }
  }

  async function handleUploadCharacterReference(characterId: string, referenceImage: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeUploadingCharacterReferences });
      return;
    }
    dispatch({ type: "character/action-start", characterId, action: "upload_reference" });
    try {
      const project = await uploadCharacterReference(currentProject.project_id, characterId, referenceImage);
      dispatch({
        type: "character/action-success",
        project,
        message: messages.app.characterReferenceUploaded(characterId)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.characterReferenceUploadFailed
      });
    }
  }

  async function handleApproveCharacterReference(characterId: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: messages.app.createBeforeApprovingCharacterReferences });
      return;
    }
    dispatch({ type: "character/action-start", characterId, action: "approve_reference" });
    try {
      const project = await approveCharacterReference(currentProject.project_id, characterId);
      dispatch({
        type: "character/action-success",
        project,
        message: messages.app.characterReferenceApproved(characterId)
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : messages.app.characterReferenceApprovalFailed
      });
    }
  }

  function handleFormChange(field: keyof ProjectFormState, value: string | number | null) {
    if (field === "scene1FirstFrameSource") {
      const nextSource = String(value ?? "auto_generate");
      dispatch({ type: "form/update", field, value: nextSource });
      dispatch({ type: "form/update", field: "scene1FirstFramePrompt", value: "" });
      if (nextSource !== "upload") {
        dispatch({ type: "form/update", field: "scene1FirstFrameImage", value: null });
        dispatch({ type: "form/update", field: "scene1FirstFrameFileName", value: null });
      }
      return;
    }
    dispatch({ type: "form/update", field, value });
  }

  function handleScene1FirstFrameFileChange(file: File | null) {
    if (!file) {
      dispatch({ type: "form/update", field: "scene1FirstFrameImage", value: null });
      dispatch({ type: "form/update", field: "scene1FirstFrameFileName", value: null });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      dispatch({
        type: "form/update",
        field: "scene1FirstFrameSource",
        value: "upload"
      });
      dispatch({
        type: "form/update",
        field: "scene1FirstFrameImage",
        value: typeof reader.result === "string" ? reader.result : null
      });
      dispatch({
        type: "form/update",
        field: "scene1FirstFrameFileName",
        value: file.name
      });
    };
    reader.readAsDataURL(file);
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <div className="hero-copy">
          <div className="hero-copy-top">
            <p className="eyebrow">{messages.hero.eyebrow}</p>
            <div className="locale-switcher" role="group" aria-label={messages.locale.label}>
              <button
                type="button"
                className={`locale-button${locale === "zh-CN" ? " locale-button-active" : ""}`}
                onClick={() => setLocale("zh-CN")}
              >
                {messages.locale.chinese}
              </button>
              <button
                type="button"
                className={`locale-button${locale === "en" ? " locale-button-active" : ""}`}
                onClick={() => setLocale("en")}
              >
                {messages.locale.english}
              </button>
            </div>
          </div>
          <h1>{messages.hero.title}</h1>
          <p>{messages.hero.description}</p>
        </div>
        <aside className="hero-visual" aria-hidden="true">
          <div className="hero-diagram">
            <article className="hero-node hero-node-primary">
              <span className="hero-node-index">01</span>
              <strong>{messages.hero.step1Title}</strong>
              <p>{messages.hero.step1Description}</p>
            </article>
            <article className="hero-node">
              <span className="hero-node-index">02</span>
              <strong>{messages.hero.step2Title}</strong>
              <p>{messages.hero.step2Description}</p>
            </article>
            <article className="hero-node">
              <span className="hero-node-index">03</span>
              <strong>{messages.hero.step3Title}</strong>
              <p>{messages.hero.step3Description}</p>
            </article>
            <article className="hero-node hero-node-accent">
              <span className="hero-node-index">04</span>
              <strong>{messages.hero.step4Title}</strong>
              <p>{messages.hero.step4Description}</p>
            </article>
          </div>
        </aside>
      </section>

      {state.errorMessage ? <div className="banner banner-error">{state.errorMessage}</div> : null}
      {state.notice ? <div className="banner banner-note">{state.notice}</div> : null}

      <section className="dashboard-grid">
        <ProjectForm
          form={state.form}
          providers={state.providers}
          providersStatus={state.providersStatus}
          disabled={
            state.isCreatingProject || state.providersStatus === "loading" || Boolean(projectDurationValidationMessage)
          }
          validationMessage={projectDurationValidationMessage}
          onFieldChange={handleFormChange}
          onScene1FirstFrameFileChange={handleScene1FirstFrameFileChange}
          onSubmit={handleCreateProject}
        />
        <WorkflowStatusCard
          project={currentProject}
          workflowStatus={state.workflowStatus}
          isCreatingProject={state.isCreatingProject}
          projectBootstrapStage={state.projectBootstrapStage}
          isStarting={state.isStartingWorkflow}
          isComposing={state.isComposing}
          onStart={handleStartWorkflow}
          onCompose={handleComposeProject}
        />
      </section>

      <CharacterLookdevPanel
        characterCards={currentProject?.character_cards ?? []}
        activeAction={state.activeCharacterAction}
        onGenerateReference={handleGenerateCharacterReference}
        onApproveReference={handleApproveCharacterReference}
        onUploadReference={handleUploadCharacterReference}
      />

        <SceneList
          scenes={currentProject?.scenes ?? []}
          workflowMode={currentProject?.workflow_mode ?? state.form.workflowMode}
          isPlanningBootstrap={state.isCreatingProject}
          planningStage={state.projectBootstrapStage}
          canCompose={Boolean(currentProject?.hitl?.can_compose)}
          isComposing={state.isComposing}
          activeAction={state.activeSceneAction}
          onGenerate={handleGenerateScene}
          onApprove={handleApproveScene}
          onCompose={handleComposeProject}
          onSavePrompt={handleSaveScenePrompt}
          onRevisePrompt={handleReviseScenePrompt}
          onSaveFirstFrame={handleSaveFirstFrame}
        />
      <FinalVideoPanel project={currentProject} onExportSubtitledVideo={handleExportSubtitledVideo} />
    </main>
  );
}
