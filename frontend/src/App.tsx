import { useEffect, useReducer } from "react";
import {
  approveCharacterReference,
  approveScene,
  composeProject,
  createProject,
  generateCharacterReference,
  generateScene,
  getWorkflowStatus,
  listProviders,
  optimizePrompt,
  planScenes,
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
            message: error instanceof Error ? error.message : "Failed to load providers."
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
              message: error instanceof Error ? error.message : "Failed to refresh workflow status."
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
    return `This provider cannot split ${targetDurationSeconds}s across ${sceneCount} scenes. The current split would be ${durations.join(
      "/"
    )}s, but supported per-scene durations are ${minDuration}-${maxDuration}s.`;
  })();

  async function handleCreateProject() {
    if (state.form.scene1FirstFrameSource === "upload" && !state.form.scene1FirstFrameImage) {
      dispatch({
        type: "ui/error",
        message: "Upload a scene 1 first frame before creating the project."
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
        message: `Project ${project.project_id} created. Building the global plan now.`
      });
      if (project.workflow_mode === "hitl") {
        project = await optimizePrompt(project.project_id);
        dispatch({
          type: "project/create-progress",
          project,
          stage: "scene_planning",
          message: `Global planning complete for ${project.project_id}. Building scene flow now.`
        });
        project = await planScenes(project.project_id);
      }
      dispatch({ type: "project/create-success", project });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Project creation failed."
      });
    }
  }

  async function handleStartWorkflow() {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: "Create a project before starting the workflow." });
      return;
    }
    dispatch({ type: "workflow/start-start" });
    try {
      const project = await startWorkflow(currentProject.project_id);
      dispatch({ type: "workflow/start-success", project });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Workflow start failed."
      });
    }
  }

  async function handleGenerateScene(sceneId: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: "Create a project before generating scenes." });
      return;
    }
    dispatch({ type: "scene/action-start", sceneId, action: "generate" });
    try {
      const project = await generateScene(currentProject.project_id, sceneId);
      dispatch({
        type: "scene/action-success",
        project,
        message: `Scene ${sceneId} queued for generation.`
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Scene generation failed."
      });
    }
  }

  async function handleApproveScene(sceneId: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: "Create a project before approving scenes." });
      return;
    }
    dispatch({ type: "scene/action-start", sceneId, action: "approve" });
    try {
      const project = await approveScene(currentProject.project_id, sceneId);
      dispatch({
        type: "scene/action-success",
        project,
        message: `Scene ${sceneId} approved.`
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Scene approval failed."
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
      dispatch({ type: "ui/error", message: "Create a project before saving first-frame settings." });
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
        message: `First-frame settings saved for ${sceneId}.`
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Saving first-frame settings failed."
      });
    }
  }

  async function handleSaveScenePrompt(sceneId: string, prompt: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: "Create a project before saving scene prompts." });
      return;
    }
    dispatch({ type: "scene/action-start", sceneId, action: "save_prompt" });
    try {
      const project = await updateScenePrompt(currentProject.project_id, sceneId, { prompt });
      dispatch({
        type: "scene/action-success",
        project,
        message: `Prompt changes applied for ${sceneId}.`
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Saving scene prompt failed."
      });
    }
  }

  async function handleComposeProject() {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: "Create a project before composing the final cut." });
      return;
    }
    dispatch({ type: "compose/start" });
    try {
      const project = await composeProject(currentProject.project_id);
      dispatch({
        type: "compose/success",
        project,
        message: `Final video composed for ${project.project_id}.`
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Final composition failed."
      });
    }
  }

  async function handleGenerateCharacterReference(characterId: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: "Create a project before generating character references." });
      return;
    }
    dispatch({ type: "character/action-start", characterId, action: "generate_reference" });
    try {
      const project = await generateCharacterReference(currentProject.project_id, characterId);
      dispatch({
        type: "character/action-success",
        project,
        message: `Character reference generated for ${characterId}.`
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Character reference generation failed."
      });
    }
  }

  async function handleUploadCharacterReference(characterId: string, referenceImage: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: "Create a project before uploading character references." });
      return;
    }
    dispatch({ type: "character/action-start", characterId, action: "upload_reference" });
    try {
      const project = await uploadCharacterReference(currentProject.project_id, characterId, referenceImage);
      dispatch({
        type: "character/action-success",
        project,
        message: `Character reference uploaded for ${characterId}.`
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Character reference upload failed."
      });
    }
  }

  async function handleApproveCharacterReference(characterId: string) {
    if (!currentProject?.project_id) {
      dispatch({ type: "ui/error", message: "Create a project before approving character references." });
      return;
    }
    dispatch({ type: "character/action-start", characterId, action: "approve_reference" });
    try {
      const project = await approveCharacterReference(currentProject.project_id, characterId);
      dispatch({
        type: "character/action-success",
        project,
        message: `Character reference approved for ${characterId}.`
      });
    } catch (error) {
      dispatch({
        type: "ui/error",
        message: error instanceof Error ? error.message : "Character reference approval failed."
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
          <p className="eyebrow">Video Workflow Service</p>
          <h1>Short video workflow studio.</h1>
          <p>
            Build a project brief, establish the opening frame, generate scenes, review each result, and compose the
            final cut in one workspace.
          </p>
        </div>
        <aside className="hero-visual" aria-hidden="true">
          <div className="hero-diagram">
            <article className="hero-node hero-node-primary">
              <span className="hero-node-index">01</span>
              <strong>Opening Frame</strong>
              <p>Upload a still or let the system generate one for scene 1.</p>
            </article>
            <article className="hero-node">
              <span className="hero-node-index">02</span>
              <strong>Story &amp; Scenes</strong>
              <p>Optimize prompt, plan scenes, assign dialogue, and compile scene prompts.</p>
            </article>
            <article className="hero-node">
              <span className="hero-node-index">03</span>
              <strong>Scene Review</strong>
              <p>Generate each scene, inspect the result, revise inputs when needed, and approve.</p>
            </article>
            <article className="hero-node hero-node-accent">
              <span className="hero-node-index">04</span>
              <strong>Final Compose</strong>
              <p>Assemble approved scenes into the delivered MP4 once the review flow is complete.</p>
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
          onSaveFirstFrame={handleSaveFirstFrame}
        />
      <FinalVideoPanel project={currentProject} />
    </main>
  );
}
