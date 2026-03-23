import { useState } from "react";
import type { CharacterCardRecord } from "../api/client";
import { formatEnumLabel } from "../i18n/catalog";
import { useI18n } from "../i18n/provider";

interface CharacterLookdevPanelProps {
  characterCards: CharacterCardRecord[];
  activeAction: {
    characterId: string;
    action: "generate_reference" | "approve_reference" | "upload_reference";
  } | null;
  onGenerateReference: (characterId: string) => void;
  onApproveReference: (characterId: string) => void;
  onUploadReference: (characterId: string, referenceImage: string) => void;
}

export function CharacterLookdevPanel({
  characterCards,
  activeAction,
  onGenerateReference,
  onApproveReference,
  onUploadReference
}: CharacterLookdevPanelProps) {
  const { messages } = useI18n();
  const [pendingUploads, setPendingUploads] = useState<Record<string, { image: string; fileName: string }>>({});
  const formatStatus = (value: string | undefined) => formatEnumLabel(value, messages.enums);

  if (!characterCards.length) {
    return null;
  }

  function handleFileChange(characterId: string, file: File | null) {
    if (!file) {
      setPendingUploads((current) => {
        const next = { ...current };
        delete next[characterId];
        return next;
      });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const imageData = reader.result;
      if (typeof imageData !== "string") {
        return;
      }
      setPendingUploads((current) => ({
        ...current,
        [characterId]: {
          image: imageData,
          fileName: file.name
        }
      }));
    };
    reader.readAsDataURL(file);
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">{messages.characterLookdev.eyebrow}</p>
          <h2>{messages.characterLookdev.title}</h2>
        </div>
        <span className="panel-badge">{characterCards.length}</span>
      </div>

      <p className="empty-copy">{messages.characterLookdev.description}</p>

      <div className="character-lookdev-grid">
        {characterCards.map((card) => {
          const uploadDraft = pendingUploads[card.character_id];
          const previewUrl = uploadDraft?.image ?? card.reference_image_url ?? card.reference_image ?? null;
          const isGenerating =
            activeAction?.characterId === card.character_id && activeAction.action === "generate_reference";
          const isUploading =
            activeAction?.characterId === card.character_id && activeAction.action === "upload_reference";
          const isApproving =
            activeAction?.characterId === card.character_id && activeAction.action === "approve_reference";

          return (
            <article key={card.character_id} className="character-lookdev-card">
              <div className="scene-card-header">
                <div>
                  <span className="scene-index">{card.display_name}</span>
                  <h3>{card.story_role || messages.characterLookdev.profileFallback}</h3>
                </div>
                <span className={`status-pill status-${card.approval_status || "pending"}`}>
                  {formatStatus(card.approval_status)}
                </span>
              </div>

              <p className="scene-copy">
                {card.visual_description || card.reference_prompt || messages.characterLookdev.noSummary}
              </p>

              {previewUrl ? (
                <img
                  className="scene-frame scene-first-frame-preview"
                  src={previewUrl}
                  alt={messages.characterLookdev.lookdevAlt(card.display_name)}
                />
              ) : (
                <div className="scene-frame scene-frame-empty">{messages.characterLookdev.noReferenceImage}</div>
              )}

              <div className="scene-first-frame-summary">
                <span>
                  {previewUrl
                    ? messages.characterLookdev.currentImage(
                        formatEnumLabel(card.source || "generated", messages.enums)
                      )
                    : messages.characterLookdev.textOnlyGuide}
                </span>
              </div>

              <label className="field">
                <span>{messages.characterLookdev.replaceImageLabel}</span>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(event) => handleFileChange(card.character_id, event.target.files?.[0] ?? null)}
                  disabled={Boolean(activeAction)}
                />
              </label>

              {uploadDraft?.fileName ? (
                <div className="scene-first-frame-summary">
                  <span>{messages.projectForm.selectedFile(uploadDraft.fileName)}</span>
                </div>
              ) : null}

              <div className="character-lookdev-actions">
                <button
                  className="secondary-button"
                  onClick={() => onGenerateReference(card.character_id)}
                  disabled={Boolean(activeAction)}
                >
                  {isGenerating ? messages.characterLookdev.generatingImage : messages.characterLookdev.generateImage}
                </button>
                <button
                  className="secondary-button"
                  onClick={() => uploadDraft && onUploadReference(card.character_id, uploadDraft.image)}
                  disabled={!uploadDraft || Boolean(activeAction)}
                >
                  {isUploading ? messages.characterLookdev.uploadingImage : messages.characterLookdev.replaceImage}
                </button>
                <button
                  className="primary-button"
                  onClick={() => onApproveReference(card.character_id)}
                  disabled={Boolean(activeAction) || card.approval_status === "approved"}
                >
                  {isApproving ? messages.characterLookdev.approvingReference : messages.characterLookdev.approveReference}
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
