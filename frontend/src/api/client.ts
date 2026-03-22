export interface ProviderDescriptor {
  name: string;
  capabilities: Record<string, unknown>;
}

export interface WorkflowRunJob {
  job_id: string;
  status: string;
  attempt_count: number;
  queued_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  failed_at?: string | null;
  error_message?: string | null;
  current_step?: string | null;
  last_completed_step?: string | null;
  completed_steps: string[];
  metadata: Record<string, unknown>;
}

export interface SceneVideoJob {
  job_id: string;
  status: string;
  attempt_count: number;
  generation_mode?: string | null;
  continuity_source_scene_id?: string | null;
  provider_task_id?: string | null;
  error_message?: string | null;
  metadata: Record<string, unknown>;
}

export interface CharacterCardRecord {
  character_id: string;
  display_name: string;
  story_role?: string;
  visual_description?: string;
  reference_image?: string | null;
  reference_image_url?: string | null;
  reference_prompt?: string;
  approval_status?: string;
  source?: string;
}

export interface SceneRecord {
  scene_id: string;
  index: number;
  title: string;
  duration_seconds: number;
  prompt: string;
  approved_prompt?: string;
  prompt_stale?: boolean;
  prompt_stale_reasons?: string[];
  narrative: string;
  status: string;
  review_status: string;
  generation_mode: string;
  first_frame_source: string;
  first_frame_image?: string | null;
  first_frame_url?: string | null;
  first_frame_prompt?: string;
  first_frame_origin?: string | null;
  first_frame_status?: string;
  first_frame_analysis?: Record<string, unknown>;
  reference_image?: string | null;
  storyboard_notes?: string;
  video_rel_path?: string | null;
  final_frame_rel_path?: string | null;
  video_url?: string | null;
  final_frame_url?: string | null;
  available_actions?: string[];
  video_job?: SceneVideoJob | null;
}

export interface HitlProjectState {
  workflow_mode: string;
  approved_scene_count: number;
  pending_review_count: number;
  next_scene_id?: string | null;
  can_compose: boolean;
}

export interface ProjectRecord {
  project_id: string;
  title: string;
  raw_prompt: string;
  optimized_prompt?: string | null;
  target_duration_seconds: number;
  aspect_ratio: string;
  provider: string;
  workflow_mode: string;
  scene_count?: number | null;
  scene1_first_frame_source: string;
  scene1_first_frame_image?: string | null;
  scene1_first_frame_prompt?: string;
  detected_input_language?: string;
  dialogue_language?: string;
  audio_language?: string;
  character_cards?: CharacterCardRecord[];
  status: string;
  final_video_rel_path?: string | null;
  final_video_url?: string | null;
  hitl?: HitlProjectState;
  scenes: SceneRecord[];
  workflow_run_job?: WorkflowRunJob | null;
}

export interface WorkflowStatusResponse {
  project_id: string;
  project_status: string;
  workflow_run_job: WorkflowRunJob | null;
  project?: ProjectRecord;
}

export interface CreateProjectPayload {
  title: string;
  prompt: string;
  target_duration_seconds: number;
  provider: string;
  scene_count: number;
  workflow_mode: string;
  scene1_first_frame_source: string;
  scene1_first_frame_image?: string | null;
  scene1_first_frame_prompt?: string;
}

export interface StoryboardScenePayload {
  scene_id?: string;
  scene_index?: number;
  first_frame_source?: string;
  first_frame_image?: string | null;
  reference_image?: string | null;
  storyboard_notes?: string;
}

export interface ScenePromptUpdatePayload {
  prompt: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    if (isJson && payload && typeof payload === "object" && "error" in payload) {
      throw new Error(String(payload.error));
    }
    throw new Error(typeof payload === "string" ? payload : `Request failed: ${response.status}`);
  }

  return payload as T;
}

export function listProviders(): Promise<ProviderDescriptor[]> {
  return request<ProviderDescriptor[]>("/providers", { method: "GET" });
}

export function createProject(payload: CreateProjectPayload): Promise<ProjectRecord> {
  return request<ProjectRecord>("/projects", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function optimizePrompt(projectId: string): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/optimize-prompt`, {
    method: "POST",
    body: "{}"
  });
}

export function planScenes(projectId: string): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/plan-scenes`, {
    method: "POST",
    body: "{}"
  });
}

export function uploadStoryboards(projectId: string, scenes: StoryboardScenePayload[]): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/storyboards/upload`, {
    method: "POST",
    body: JSON.stringify({ scenes })
  });
}

export function generateScene(projectId: string, sceneId: string): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/scenes/${sceneId}/generate`, {
    method: "POST",
    body: "{}"
  });
}

export function approveScene(projectId: string, sceneId: string): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/scenes/${sceneId}/approve`, {
    method: "POST",
    body: "{}"
  });
}

export function updateScenePrompt(
  projectId: string,
  sceneId: string,
  payload: ScenePromptUpdatePayload
): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/scenes/${sceneId}/prompt`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function generateCharacterReference(projectId: string, characterId: string): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/characters/${characterId}/generate-reference`, {
    method: "POST",
    body: "{}"
  });
}

export function uploadCharacterReference(
  projectId: string,
  characterId: string,
  referenceImage: string
): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/characters/${characterId}/upload-reference`, {
    method: "POST",
    body: JSON.stringify({ reference_image: referenceImage })
  });
}

export function approveCharacterReference(projectId: string, characterId: string): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/characters/${characterId}/approve`, {
    method: "POST",
    body: "{}"
  });
}

export function composeProject(projectId: string): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/compose`, {
    method: "POST",
    body: "{}"
  });
}

export function startWorkflow(projectId: string): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/projects/${projectId}/workflow/start`, {
    method: "POST",
    body: "{}"
  });
}

export function getWorkflowStatus(projectId: string): Promise<WorkflowStatusResponse> {
  return request<WorkflowStatusResponse>(`/projects/${projectId}/workflow/status`, {
    method: "GET"
  });
}
