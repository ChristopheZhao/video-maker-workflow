import type { ProviderDescriptor } from "../api/client";
import { useI18n } from "../i18n/provider";
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
  const { messages } = useI18n();
  const selectedProvider = providers.find((provider) => provider.name === form.provider);
  const supportsContinuity = Boolean(selectedProvider?.capabilities["supports_first_last_frame"]);
  const resolution = selectedProvider?.capabilities["resolution"];
  const submitLabel = validationMessage
    ? messages.projectForm.submitAdjust
    : disabled
      ? messages.projectForm.submitCreating
      : messages.projectForm.submitCreate;

  return (
    <section className="panel panel-form">
      <div className="panel-header">
        <div>
          <p className="eyebrow">{messages.projectForm.eyebrow}</p>
          <h2>{messages.projectForm.title}</h2>
        </div>
        <span className="panel-badge">{messages.projectForm.badge}</span>
      </div>

      <label className="field">
        <span>{messages.projectForm.titleLabel}</span>
        <input
          value={form.title}
          onChange={(event) => onFieldChange("title", event.target.value)}
          placeholder={messages.projectForm.titlePlaceholder}
        />
      </label>

      <label className="field">
        <span>{messages.projectForm.promptLabel}</span>
        <textarea
          rows={6}
          value={form.prompt}
          onChange={(event) => onFieldChange("prompt", event.target.value)}
          placeholder={messages.projectForm.promptPlaceholder}
        />
      </label>

      <div className="field-grid">
        <label className="field">
          <span>{messages.projectForm.targetDurationLabel}</span>
          <input
            type="number"
            min={5}
            value={form.targetDurationSeconds}
            onChange={(event) => onFieldChange("targetDurationSeconds", Number(event.target.value))}
          />
        </label>

        <label className="field">
          <span>{messages.projectForm.sceneCountLabel}</span>
          <input
            type="number"
            min={1}
            value={form.sceneCount}
            onChange={(event) => onFieldChange("sceneCount", Number(event.target.value))}
          />
        </label>
      </div>

      <label className="field">
        <span>{messages.projectForm.providerLabel}</span>
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
        <span>{messages.projectForm.workflowModeLabel}</span>
        <select
          value={form.workflowMode}
          onChange={(event) => onFieldChange("workflowMode", event.target.value)}
        >
          <option value="hitl">{messages.projectForm.workflowModeHitl}</option>
          <option value="auto">{messages.projectForm.workflowModeAuto}</option>
        </select>
      </label>

      <label className="field">
        <span>{messages.projectForm.subtitleModeLabel}</span>
        <select
          value={form.subtitleMode}
          onChange={(event) => onFieldChange("subtitleMode", event.target.value)}
        >
          <option value="disabled">{messages.projectForm.subtitleModeDisabled}</option>
          <option value="enabled">{messages.projectForm.subtitleModeEnabled}</option>
        </select>
      </label>

      <div className="field-group">
        <p className="field-group-title">{messages.projectForm.firstFrameSectionTitle}</p>
        <label className="field">
          <span>{messages.projectForm.openingFrameSourceLabel}</span>
          <select
            value={form.scene1FirstFrameSource}
            onChange={(event) => onFieldChange("scene1FirstFrameSource", event.target.value)}
          >
            <option value="auto_generate">{messages.projectForm.autoGenerateStill}</option>
            <option value="upload">{messages.projectForm.uploadStill}</option>
          </select>
        </label>

        {form.scene1FirstFrameSource === "upload" ? (
          <>
            <label className="field">
              <span>{messages.projectForm.uploadFirstFrameLabel}</span>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(event) => onScene1FirstFrameFileChange(event.target.files?.[0] ?? null)}
              />
            </label>
            <div className="provider-summary">
              <span className="eyebrow">{messages.projectForm.openingStillEyebrow}</span>
              <p>
                {form.scene1FirstFrameFileName
                  ? messages.projectForm.selectedFile(form.scene1FirstFrameFileName)
                  : messages.projectForm.uploadStillHelp}
              </p>
            </div>
            {form.scene1FirstFrameImage ? (
              <img
                className="scene-frame scene-first-frame-preview"
                src={form.scene1FirstFrameImage}
                alt={messages.projectForm.uploadedPreviewAlt}
              />
            ) : null}
          </>
        ) : (
          <div className="provider-summary">
            <span className="eyebrow">{messages.projectForm.openingStillEyebrow}</span>
            <p>{messages.projectForm.autoStillHelp}</p>
          </div>
        )}
      </div>

      <div className="provider-summary">
        <span className="eyebrow">{messages.projectForm.capabilityEyebrow}</span>
        <p>
          {selectedProvider
            ? messages.projectForm.capabilitySummary(
                typeof resolution === "string" && resolution.trim() ? resolution : null,
                supportsContinuity,
                form.workflowMode === "hitl"
              )
            : messages.projectForm.capabilityUnavailable}
        </p>
      </div>

      {form.subtitleMode !== "disabled" ? (
        <div className="provider-summary">
          <span className="eyebrow">{messages.projectForm.subtitleEyebrow}</span>
          <p>{messages.projectForm.subtitleHelp}</p>
        </div>
      ) : null}

      {validationMessage ? (
        <div className="provider-summary">
          <span className="eyebrow">{messages.projectForm.durationCheckEyebrow}</span>
          <p>{validationMessage}</p>
        </div>
      ) : null}

      <button className="primary-button" onClick={onSubmit} disabled={disabled}>
        {submitLabel}
      </button>
    </section>
  );
}
