import type { ProjectRecord, WorkflowStatusResponse } from "../api/client";
import { formatEnumLabel } from "../i18n/catalog";
import { useI18n } from "../i18n/provider";

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
  const { messages } = useI18n();
  const formatLabel = (value: string | null | undefined) => formatEnumLabel(value, messages.enums);
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
    { key: "creating_project", label: messages.workflowStatus.bootstrapUnderstand },
    { key: "global_planning", label: messages.workflowStatus.bootstrapStory },
    { key: "scene_planning", label: messages.workflowStatus.bootstrapScenes }
  ] as const;
  const bootstrapStepIndex = bootstrapSteps.findIndex((step) => step.key === projectBootstrapStage);
  const bootstrapDescription =
    projectBootstrapStage === "creating_project"
      ? messages.workflowStatus.bootstrapCreatingDescription
      : projectBootstrapStage === "global_planning"
        ? messages.workflowStatus.bootstrapGlobalDescription
        : projectBootstrapStage === "scene_planning"
          ? messages.workflowStatus.bootstrapSceneDescription
          : "";
  const isBootstrapActive = isCreatingProject && projectBootstrapStage !== "idle";

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">{messages.workflowStatus.eyebrow}</p>
          <h2>{messages.workflowStatus.title}</h2>
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
                <span className="meta-label">{messages.workflowStatus.planningEyebrow}</span>
                <strong>
                  {bootstrapSteps[Math.max(bootstrapStepIndex, 0)]?.label ?? messages.workflowStatus.bootstrapUnderstand}
                </strong>
              </div>
              <span>{messages.workflowStatus.planningState}</span>
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
          <p className="empty-copy">{messages.workflowStatus.emptyCopy}</p>
          <div className="status-empty-grid">
            <article className="status-empty-card">
              <span className="meta-label">{messages.workflowStatus.emptyInputStep}</span>
              <strong>{messages.workflowStatus.emptyInputTitle}</strong>
              <p>{messages.workflowStatus.emptyInputDescription}</p>
            </article>
            <article className="status-empty-card">
              <span className="meta-label">{messages.workflowStatus.emptyPlanStep}</span>
              <strong>{messages.workflowStatus.emptyPlanTitle}</strong>
              <p>{messages.workflowStatus.emptyPlanDescription}</p>
            </article>
            <article className="status-empty-card">
              <span className="meta-label">{messages.workflowStatus.emptyExecuteStep}</span>
              <strong>{messages.workflowStatus.emptyExecuteTitle}</strong>
              <p>{messages.workflowStatus.emptyExecuteDescription}</p>
            </article>
          </div>
        </div>
        )
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat-card">
              <span>{messages.workflowStatus.projectId}</span>
              <strong>{project.project_id}</strong>
            </div>
            <div className="stat-card">
              <span>{messages.workflowStatus.provider}</span>
              <strong>{project.provider}</strong>
            </div>
            <div className="stat-card">
              <span>{messages.workflowStatus.scenes}</span>
              <strong>{project.scene_count ?? project.scenes.length}</strong>
            </div>
            <div className="stat-card">
              <span>{isHitl ? messages.workflowStatus.workflowMode : messages.workflowStatus.currentStep}</span>
              <strong>{isHitl ? formatLabel(project.workflow_mode) : formatLabel(workflowRun?.current_step)}</strong>
            </div>
          </div>

          {isBootstrapActive ? (
            <div className="planning-status-card planning-status-inline">
              <div className="planning-status-head">
                <div>
                  <span className="meta-label">{messages.workflowStatus.planningEyebrow}</span>
                  <strong>
                    {bootstrapSteps[Math.max(bootstrapStepIndex, 0)]?.label ?? messages.workflowStatus.bootstrapUnderstand}
                  </strong>
                </div>
                <span>{messages.workflowStatus.planningState}</span>
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
                  <span>{messages.workflowStatus.approvedProgress(hitl?.approved_scene_count ?? 0, project.scenes.length)}</span>
                  <span>{approvedProgress}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${approvedProgress}%` }} />
                </div>
              </div>

              <div className="meta-block">
                <div>
                  <span className="meta-label">{messages.workflowStatus.nextScene}</span>
                  <p>{hitl?.next_scene_id ?? messages.workflowStatus.allScenesApproved}</p>
                </div>
                <div>
                  <span className="meta-label">{messages.workflowStatus.pendingReview}</span>
                  <p>{hitl?.pending_review_count ?? 0}</p>
                </div>
              </div>

              <button className="primary-button" onClick={onCompose} disabled={!hitl?.can_compose || isComposing}>
                {isComposing ? messages.workflowStatus.composing : messages.workflowStatus.compose}
              </button>
              <p className="panel-footnote">{messages.workflowStatus.composeFootnote}</p>
            </>
          ) : (
            <>
              <div className="progress-block">
                <div className="progress-copy">
                  <span>{messages.workflowStatus.workflowProgress(completedSteps.length, TOTAL_WORKFLOW_STEPS)}</span>
                  <span>{progress}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
              </div>

              <div className="meta-block">
                <div>
                  <span className="meta-label">{messages.workflowStatus.completedSteps}</span>
                  <p>{completedSteps.length ? completedSteps.map(formatLabel).join(" -> ") : messages.workflowStatus.waitingToStart}</p>
                </div>
                <div>
                  <span className="meta-label">{messages.workflowStatus.errors}</span>
                  <p>{workflowRun?.error_message ?? messages.workflowStatus.none}</p>
                </div>
              </div>

              <button className="primary-button" onClick={onStart} disabled={!canStart || isStarting}>
                {isStarting
                  ? messages.workflowStatus.queueing
                  : workflowRun
                    ? messages.workflowStatus.runWorkflow
                    : messages.workflowStatus.startWorkflow}
              </button>
            </>
          )}
        </>
      )}
    </section>
  );
}
