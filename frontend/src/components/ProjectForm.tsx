import type { ProviderDescriptor } from "../api/client";
import type { ProjectFormState } from "../state/project-store";

interface ProjectFormProps {
  form: ProjectFormState;
  providers: ProviderDescriptor[];
  providersStatus: "idle" | "loading" | "ready" | "error";
  disabled: boolean;
  validationMessage?: string | null;
  onFieldChange: (field: keyof ProjectFormState, value: string | number | null) => void;
  onScene1FirstFrameFileChange: (file: File | null) => void;
  onSubmit: () => void;
}

export function ProjectForm({
  form,
  providers,
  providersStatus,
  disabled,
  validationMessage,
  onFieldChange,
  onScene1FirstFrameFileChange,
  onSubmit
}: ProjectFormProps) {
  const selectedProvider = providers.find((provider) => provider.name === form.provider);
  const supportsContinuity = Boolean(selectedProvider?.capabilities["supports_first_last_frame"]);
  const resolution = selectedProvider?.capabilities["resolution"];
  const submitLabel = validationMessage
    ? "Adjust Duration or Scene Count"
    : disabled
      ? "Creating..."
      : "Create Project";

  return (
    <section className="panel panel-form">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Project Setup</p>
          <h2>Create Project</h2>
        </div>
        <span className="panel-badge">Start Here</span>
      </div>

      <label className="field">
        <span>Title</span>
        <input
          value={form.title}
          onChange={(event) => onFieldChange("title", event.target.value)}
          placeholder="Campaign title"
        />
      </label>

      <label className="field">
        <span>Prompt</span>
        <textarea
          rows={6}
          value={form.prompt}
          onChange={(event) => onFieldChange("prompt", event.target.value)}
          placeholder="Describe the short video goal, tone, and product story."
        />
      </label>

      <div className="field-grid">
        <label className="field">
          <span>Target Duration</span>
          <input
            type="number"
            min={5}
            value={form.targetDurationSeconds}
            onChange={(event) => onFieldChange("targetDurationSeconds", Number(event.target.value))}
          />
        </label>

        <label className="field">
          <span>Scene Count</span>
          <input
            type="number"
            min={1}
            value={form.sceneCount}
            onChange={(event) => onFieldChange("sceneCount", Number(event.target.value))}
          />
        </label>
      </div>

      <label className="field">
        <span>Provider</span>
        <select
          value={form.provider}
          onChange={(event) => onFieldChange("provider", event.target.value)}
          disabled={providersStatus === "loading"}
        >
          {providers.map((provider) => (
            <option key={provider.name} value={provider.name}>
              {provider.name}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Workflow Mode</span>
        <select
          value={form.workflowMode}
          onChange={(event) => onFieldChange("workflowMode", event.target.value)}
        >
          <option value="hitl">HITL scene review</option>
          <option value="auto">Auto workflow</option>
        </select>
      </label>

      <div className="field-group">
        <p className="field-group-title">Scene 1 First Frame</p>
        <label className="field">
          <span>Opening Frame Source</span>
          <select
            value={form.scene1FirstFrameSource}
            onChange={(event) => onFieldChange("scene1FirstFrameSource", event.target.value)}
          >
            <option value="auto_generate">Auto generate still</option>
            <option value="upload">Upload still</option>
          </select>
        </label>

        {form.scene1FirstFrameSource === "upload" ? (
          <>
            <label className="field">
              <span>Upload First Frame</span>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(event) => onScene1FirstFrameFileChange(event.target.files?.[0] ?? null)}
              />
            </label>
            <div className="provider-summary">
              <span className="eyebrow">Opening Still</span>
              <p>
                {form.scene1FirstFrameFileName
                  ? `Selected file: ${form.scene1FirstFrameFileName}`
                  : "Upload the still that scene 1 should open from."}
              </p>
            </div>
            {form.scene1FirstFrameImage ? (
              <img
                className="scene-frame scene-first-frame-preview"
                src={form.scene1FirstFrameImage}
                alt="Scene 1 uploaded first-frame preview"
              />
            ) : null}
          </>
        ) : (
          <div className="provider-summary">
            <span className="eyebrow">Opening Still</span>
            <p>
              The workflow will derive and generate the opening still for scene 1 after planning. You only need
              to choose whether scene 1 starts from an uploaded still or an auto-generated still.
            </p>
          </div>
        )}
      </div>

      <div className="provider-summary">
        <span className="eyebrow">What This Setup Supports</span>
        <p>
          {selectedProvider
            ? `Resolution ${String(resolution ?? "n/a")} with ${
                supportsContinuity ? "frame continuity" : "basic scene generation"
              }. ${form.workflowMode === "hitl" ? "This project will pause for scene approval." : "This project will run end-to-end automatically."}`
            : "Available settings will appear after loading."}
        </p>
      </div>

      {validationMessage ? (
        <div className="provider-summary">
          <span className="eyebrow">Duration Check</span>
          <p>{validationMessage}</p>
        </div>
      ) : null}

      <button className="primary-button" onClick={onSubmit} disabled={disabled}>
        {submitLabel}
      </button>
    </section>
  );
}
