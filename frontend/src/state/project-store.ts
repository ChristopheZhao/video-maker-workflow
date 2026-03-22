import type {
  ProjectRecord,
  ProviderDescriptor,
  WorkflowStatusResponse
} from "../api/client";

export interface ProjectFormState {
  title: string;
  prompt: string;
  targetDurationSeconds: number;
  provider: string;
  sceneCount: number;
  workflowMode: string;
  scene1FirstFrameSource: string;
  scene1FirstFrameImage: string | null;
  scene1FirstFramePrompt: string;
  scene1FirstFrameFileName: string | null;
}

export interface AppState {
  providers: ProviderDescriptor[];
  providersStatus: "idle" | "loading" | "ready" | "error";
  form: ProjectFormState;
  project: ProjectRecord | null;
  workflowStatus: WorkflowStatusResponse | null;
  isCreatingProject: boolean;
  projectBootstrapStage: "idle" | "creating_project" | "global_planning" | "scene_planning";
  isStartingWorkflow: boolean;
  isComposing: boolean;
  activeSceneAction: { sceneId: string; action: "generate" | "approve" | "save_first_frame" | "save_prompt" } | null;
  activeCharacterAction: {
    characterId: string;
    action: "generate_reference" | "approve_reference" | "upload_reference";
  } | null;
  errorMessage: string | null;
  notice: string | null;
}

type Action =
  | { type: "providers/load-start" }
  | { type: "providers/load-success"; providers: ProviderDescriptor[] }
  | { type: "providers/load-failure"; message: string }
  | {
      type: "form/update";
      field: keyof ProjectFormState;
      value: string | number | null;
    }
  | { type: "project/create-start" }
  | {
      type: "project/create-progress";
      project: ProjectRecord;
      stage: "creating_project" | "global_planning" | "scene_planning";
      message: string;
    }
  | { type: "project/create-success"; project: ProjectRecord }
  | { type: "workflow/start-start" }
  | { type: "workflow/start-success"; project: ProjectRecord }
  | { type: "scene/action-start"; sceneId: string; action: "generate" | "approve" | "save_first_frame" | "save_prompt" }
  | { type: "scene/action-success"; project: ProjectRecord; message: string }
  | {
      type: "character/action-start";
      characterId: string;
      action: "generate_reference" | "approve_reference" | "upload_reference";
    }
  | { type: "character/action-success"; project: ProjectRecord; message: string }
  | { type: "compose/start" }
  | { type: "compose/success"; project: ProjectRecord; message: string }
  | { type: "workflow/status-update"; status: WorkflowStatusResponse }
  | { type: "ui/error"; message: string }
  | { type: "ui/notice"; message: string | null }
  | { type: "ui/clear-error" };

const DEFAULT_FORM: ProjectFormState = {
  title: "Video Workflow Service",
  prompt: "A cinematic three-scene short about a product launch that turns a night city into a stage.",
  targetDurationSeconds: 15,
  provider: "doubao",
  sceneCount: 3,
  workflowMode: "hitl",
  scene1FirstFrameSource: "auto_generate",
  scene1FirstFrameImage: null,
  scene1FirstFramePrompt: "",
  scene1FirstFrameFileName: null
};

export function createInitialState(): AppState {
  return {
    providers: [],
    providersStatus: "idle",
    form: DEFAULT_FORM,
    project: null,
    workflowStatus: null,
    isCreatingProject: false,
    projectBootstrapStage: "idle",
    isStartingWorkflow: false,
    isComposing: false,
    activeSceneAction: null,
    activeCharacterAction: null,
    errorMessage: null,
    notice: null
  };
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "providers/load-start":
      return { ...state, providersStatus: "loading", errorMessage: null };
    case "providers/load-success": {
      const fallbackProvider = action.providers[0]?.name ?? state.form.provider;
      const selectedProvider = action.providers.some((item) => item.name === state.form.provider)
        ? state.form.provider
        : fallbackProvider;
      return {
        ...state,
        providers: action.providers,
        providersStatus: "ready",
        form: {
          ...state.form,
          provider: selectedProvider
        }
      };
    }
    case "providers/load-failure":
      return {
        ...state,
        providersStatus: "error",
        errorMessage: action.message
      };
    case "form/update":
      return {
        ...state,
        form: {
          ...state.form,
          [action.field]: action.value
        } as ProjectFormState
      };
    case "project/create-start":
      return {
        ...state,
        isCreatingProject: true,
        projectBootstrapStage: "creating_project",
        activeSceneAction: null,
        activeCharacterAction: null,
        errorMessage: null,
        notice: null
      };
    case "project/create-progress":
      return {
        ...state,
        project: action.project,
        workflowStatus: action.project.workflow_run_job
          ? {
              project_id: action.project.project_id,
              project_status: action.project.status,
              workflow_run_job: action.project.workflow_run_job,
              project: action.project
            }
          : null,
        isCreatingProject: true,
        projectBootstrapStage: action.stage,
        errorMessage: null,
        notice: action.message
      };
    case "project/create-success":
      return {
        ...state,
        project: action.project,
        workflowStatus: action.project.workflow_run_job
          ? {
              project_id: action.project.project_id,
              project_status: action.project.status,
              workflow_run_job: action.project.workflow_run_job,
              project: action.project
            }
          : null,
        isCreatingProject: false,
        projectBootstrapStage: "idle",
        isComposing: false,
        activeSceneAction: null,
        activeCharacterAction: null,
        errorMessage: null,
        notice: `Project ${action.project.project_id} created.`
      };
    case "workflow/start-start":
      return {
        ...state,
        isStartingWorkflow: true,
        activeSceneAction: null,
        activeCharacterAction: null,
        errorMessage: null,
        notice: null
      };
    case "workflow/start-success":
      return {
        ...state,
        project: action.project,
        workflowStatus: {
          project_id: action.project.project_id,
          project_status: action.project.status,
          workflow_run_job: action.project.workflow_run_job ?? null,
          project: action.project
        },
        isStartingWorkflow: false,
        isComposing: false,
        activeSceneAction: null,
        activeCharacterAction: null,
        errorMessage: null,
        notice: `Workflow queued for ${action.project.project_id}.`
      };
    case "scene/action-start":
      return {
        ...state,
        activeSceneAction: { sceneId: action.sceneId, action: action.action },
        errorMessage: null,
        notice: null
      };
    case "scene/action-success":
      return {
        ...state,
        project: action.project,
        workflowStatus: {
          project_id: action.project.project_id,
          project_status: action.project.status,
          workflow_run_job: action.project.workflow_run_job ?? null,
          project: action.project
        },
        activeSceneAction: null,
        activeCharacterAction: null,
        errorMessage: null,
        notice: action.message
      };
    case "character/action-start":
      return {
        ...state,
        activeCharacterAction: { characterId: action.characterId, action: action.action },
        errorMessage: null,
        notice: null
      };
    case "character/action-success":
      return {
        ...state,
        project: action.project,
        workflowStatus: {
          project_id: action.project.project_id,
          project_status: action.project.status,
          workflow_run_job: action.project.workflow_run_job ?? null,
          project: action.project
        },
        activeCharacterAction: null,
        errorMessage: null,
        notice: action.message
      };
    case "compose/start":
      return {
        ...state,
        isComposing: true,
        errorMessage: null,
        notice: null
      };
    case "compose/success":
      return {
        ...state,
        project: action.project,
        workflowStatus: {
          project_id: action.project.project_id,
          project_status: action.project.status,
          workflow_run_job: action.project.workflow_run_job ?? null,
          project: action.project
        },
        isComposing: false,
        errorMessage: null,
        notice: action.message
      };
    case "workflow/status-update":
      return {
        ...state,
        workflowStatus: action.status,
        project: action.status.project ?? state.project,
        isStartingWorkflow: false
      };
    case "ui/error":
      return {
        ...state,
        errorMessage: action.message,
        isCreatingProject: false,
        projectBootstrapStage: "idle",
        isStartingWorkflow: false,
        isComposing: false,
        activeSceneAction: null,
        activeCharacterAction: null
      };
    case "ui/notice":
      return {
        ...state,
        notice: action.message
      };
    case "ui/clear-error":
      return {
        ...state,
        errorMessage: null
      };
    default:
      return state;
  }
}

export function isWorkflowActive(status: WorkflowStatusResponse | null): boolean {
  if (!status?.workflow_run_job) {
    return false;
  }
  return status.workflow_run_job.status === "queued" || status.workflow_run_job.status === "running";
}

export function shouldPollProject(
  project: ProjectRecord | null,
  status: WorkflowStatusResponse | null
): boolean {
  if (isWorkflowActive(status)) {
    return true;
  }
  if (!project) {
    return false;
  }
  return project.scenes.some((scene) => {
    const jobStatus = scene.video_job?.status;
    return scene.status === "queued" || scene.status === "generating" || jobStatus === "queued" || jobStatus === "running";
  });
}
