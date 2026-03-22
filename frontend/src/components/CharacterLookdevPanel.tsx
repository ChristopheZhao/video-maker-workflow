import { useState } from "react";
import type { CharacterCardRecord } from "../api/client";

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

function formatStatus(value: string | undefined) {
  return (value || "pending").replace(/_/g, " ");
}

export function CharacterLookdevPanel({
  characterCards,
  activeAction,
  onGenerateReference,
  onApproveReference,
  onUploadReference
}: CharacterLookdevPanelProps) {
  const [pendingUploads, setPendingUploads] = useState<Record<string, { image: string; fileName: string }>>({});

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
          <p className="eyebrow">Character References</p>
          <h2>Visual Character Guides</h2>
        </div>
        <span className="panel-badge">{characterCards.length}</span>
      </div>

      <p className="empty-copy">
        Use these optional references to keep important characters visually consistent across planning and generated
        opening stills.
      </p>

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
                  <h3>{card.story_role || "Character profile"}</h3>
                </div>
                <span className={`status-pill status-${card.approval_status || "pending"}`}>
                  {formatStatus(card.approval_status)}
                </span>
              </div>

              <p className="scene-copy">{card.visual_description || card.reference_prompt || "No visual summary yet."}</p>

              {previewUrl ? (
                <img className="scene-frame scene-first-frame-preview" src={previewUrl} alt={`${card.display_name} lookdev`} />
              ) : (
                <div className="scene-frame scene-frame-empty">No reference image yet. Generate one or upload a replacement.</div>
              )}

              <div className="scene-first-frame-summary">
                <span>
                  {previewUrl
                    ? `Current image: ${card.source || "generated"}`
                    : "This character currently uses text only. Generate or upload an image if you want a visual guide."}
                </span>
              </div>

              <label className="field">
                <span>Replace Image</span>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(event) => handleFileChange(card.character_id, event.target.files?.[0] ?? null)}
                  disabled={Boolean(activeAction)}
                />
              </label>

              {uploadDraft?.fileName ? (
                <div className="scene-first-frame-summary">
                  <span>Selected file: {uploadDraft.fileName}</span>
                </div>
              ) : null}

              <div className="character-lookdev-actions">
                <button
                  className="secondary-button"
                  onClick={() => onGenerateReference(card.character_id)}
                  disabled={Boolean(activeAction)}
                >
                  {isGenerating ? "Generating..." : "Generate Image"}
                </button>
                <button
                  className="secondary-button"
                  onClick={() => uploadDraft && onUploadReference(card.character_id, uploadDraft.image)}
                  disabled={!uploadDraft || Boolean(activeAction)}
                >
                  {isUploading ? "Uploading..." : "Replace Image"}
                </button>
                <button
                  className="primary-button"
                  onClick={() => onApproveReference(card.character_id)}
                  disabled={Boolean(activeAction) || card.approval_status === "approved"}
                >
                  {isApproving ? "Approving..." : "Approve Reference"}
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
