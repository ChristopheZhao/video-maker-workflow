import type { ProjectRecord, WorkflowStatusResponse } from "../api/client";

interface WorkflowStatusCardProps {
  project: ProjectRecord | null;
  workflowStatus: WorkflowStatusResponse | null;
  isCreatingProject: boolean;
  projectBootstrapStage: "idle" | "creating_project" | "global_planning" | "scene_planning";
  isStarting: boolean;
  isComposing: boolean;
  onStart: () => void;
  onCompose: () => void;
}

const TOTAL_WORKFLOW_STEPS = 4;

function formatLabel(value: string | null | undefined): string {
  return (value ?? "idle").replace(/_/g, " ");
}

export function WorkflowStatusCard({
  project,
  workflowStatus,
  isCreatingProject,
  projectBootstrapStage,
  isStarting,
  isComposing,
  onStart,
  onCompose
}: WorkflowStatusCardProps) {
  const workflowRun = workflowStatus?.workflow_run_job ?? project?.workflow_run_job ?? null;
  const completedSteps = workflowRun?.completed_steps ?? [];
  const progress = Math.min(100, Math.round((completedSteps.length / TOTAL_WORKFLOW_STEPS) * 100));
  const canStart = Boolean(project) && workflowRun?.status !== "queued" && workflowRun?.status !== "running";
  const isHitl = project?.workflow_mode === "hitl";
  const hitl = project?.hitl;
  const approvedProgress = project?.scenes.length
    ? Math.round(((hitl?.approved_scene_count ?? 0) / project.scenes.length) * 100)
    : 0;
  const bootstrapSteps = [
    { key: "creating_project", label: "Understand brief" },
    { key: "global_planning", label: "Plan overall story" },
    { key: "scene_planning", label: "Plan each scene" }
  ] as const;
  const bootstrapStepIndex = bootstrapSteps.findIndex((step) => step.key === projectBootstrapStage);
  const bootstrapDescription =
    projectBootstrapStage === "creating_project"
      ? "Understanding your request, checking the opening setup, and preparing the planning context."
      : projectBootstrapStage === "global_planning"
        ? "Working out the overall story direction, key beats, and language alignment."
        : projectBootstrapStage === "scene_planning"
          ? "Turning the story plan into scene beats, dialogue placement, and scene prompts. The scene workspace appears after this finishes."
          : "";
  const isBootstrapActive = isCreatingProject && projectBootstrapStage !== "idle";

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Execution Status</p>
          <h2>Runtime Overview</h2>
        </div>
        <span className={`status-pill status-${workflowStatus?.project_status ?? project?.status ?? "draft"}`}>
          {formatLabel(workflowStatus?.project_status ?? project?.status)}
        </span>
      </div>

      {!project ? (
        isBootstrapActive ? (
          <div className="planning-status-card">
            <div className="planning-status-head">
              <div>
                <span className="meta-label">Planning In Progress</span>
                <strong>{bootstrapSteps[Math.max(bootstrapStepIndex, 0)]?.label ?? "Understand brief"}</strong>
              </div>
              <span>In progress</span>
            </div>
            <p className="empty-copy">{bootstrapDescription}</p>
            <div className="progress-track progress-track-indeterminate" aria-hidden="true">
              <div className="progress-fill progress-fill-indeterminate" />
            </div>
            <div className="planning-step-list">
              {bootstrapSteps.map((step, index) => {
                const state =
                  index < bootstrapStepIndex ? "done" : index === bootstrapStepIndex ? "active" : "pending";
                return (
                  <div key={step.key} className={`planning-step planning-step-${state}`}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <strong>{step.label}</strong>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
        <div className="status-empty">
          <p className="empty-copy">
            Create a project to unlock planning, scene execution, and final delivery tracking.
          </p>
          <div className="status-empty-grid">
            <article className="status-empty-card">
              <span className="meta-label">01 Input</span>
              <strong>Define the opening frame and project brief.</strong>
              <p>Choose scene count, target duration, provider, and how scene 1 should start.</p>
            </article>
            <article className="status-empty-card">
              <span className="meta-label">02 Plan</span>
              <strong>Plan the story and scene flow.</strong>
              <p>Shape the story arc, split it into scenes, place dialogue, and prepare scene prompts.</p>
            </article>
            <article className="status-empty-card">
              <span className="meta-label">03 Execute</span>
              <strong>Generate, review, approve, and compose.</strong>
              <p>HITL mode pauses per scene. Auto mode runs straight through to final composition.</p>
            </article>
          </div>
        </div>
        )
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card">
              <span>Project ID</span>
              <strong>{project.project_id}</strong>
            </div>
            <div className="stat-card">
              <span>Provider</span>
              <strong>{project.provider}</strong>
            </div>
            <div className="stat-card">
              <span>Scenes</span>
              <strong>{project.scene_count ?? project.scenes.length}</strong>
            </div>
            <div className="stat-card">
              <span>{isHitl ? "Workflow Mode" : "Current Step"}</span>
              <strong>{isHitl ? formatLabel(project.workflow_mode) : formatLabel(workflowRun?.current_step)}</strong>
            </div>
          </div>

          {isBootstrapActive ? (
            <div className="planning-status-card planning-status-inline">
              <div className="planning-status-head">
                <div>
                  <span className="meta-label">Planning In Progress</span>
                  <strong>{bootstrapSteps[Math.max(bootstrapStepIndex, 0)]?.label ?? "Understand brief"}</strong>
                </div>
                <span>In progress</span>
              </div>
              <p className="empty-copy">{bootstrapDescription}</p>
              <div className="progress-track progress-track-indeterminate" aria-hidden="true">
                <div className="progress-fill progress-fill-indeterminate" />
              </div>
              <div className="planning-step-list">
                {bootstrapSteps.map((step, index) => {
                  const state =
                    index < bootstrapStepIndex ? "done" : index === bootstrapStepIndex ? "active" : "pending";
                  return (
                    <div key={step.key} className={`planning-step planning-step-${state}`}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <strong>{step.label}</strong>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {isHitl ? (
            <>
              <div className="progress-block">
                <div className="progress-copy">
                  <span>{hitl?.approved_scene_count ?? 0} / {project.scenes.length} scenes approved</span>
                  <span>{approvedProgress}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${approvedProgress}%` }} />
                </div>
              </div>

              <div className="meta-block">
                <div>
                  <span className="meta-label">Next Scene</span>
                  <p>{hitl?.next_scene_id ?? "All scenes approved."}</p>
                </div>
                <div>
                  <span className="meta-label">Pending Review</span>
                  <p>{hitl?.pending_review_count ?? 0}</p>
                </div>
              </div>

              <button className="primary-button" onClick={onCompose} disabled={!hitl?.can_compose || isComposing}>
                {isComposing ? "Composing..." : "Compose Final Video"}
              </button>
              <p className="panel-footnote">
                Generate and approve scenes from the scene panel below. Composition unlocks after every scene reaches
                approved status.
              </p>
            </>
          ) : (
            <>
              <div className="progress-block">
                <div className="progress-copy">
                  <span>{completedSteps.length} / {TOTAL_WORKFLOW_STEPS} workflow steps complete</span>
                  <span>{progress}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
              </div>

              <div className="meta-block">
                <div>
                  <span className="meta-label">Completed Steps</span>
                  <p>{completedSteps.length ? completedSteps.map(formatLabel).join(" -> ") : "Waiting to start."}</p>
                </div>
                <div>
                  <span className="meta-label">Errors</span>
                  <p>{workflowRun?.error_message ?? "None"}</p>
                </div>
              </div>

              <button className="primary-button" onClick={onStart} disabled={!canStart || isStarting}>
                {isStarting ? "Queueing..." : workflowRun ? "Run Workflow" : "Start Workflow"}
              </button>
            </>
          )}
        </>
      )}
    </section>
  );
}
