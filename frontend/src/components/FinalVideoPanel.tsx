import type { ProjectRecord } from "../api/client";

interface FinalVideoPanelProps {
  project: ProjectRecord | null;
}

export function FinalVideoPanel({ project }: FinalVideoPanelProps) {
  const finalVideoUrl = project?.final_video_url;

  return (
    <section className="panel final-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Delivery</p>
          <h2>Final Preview</h2>
        </div>
        <span className="panel-badge">{project?.status ?? "idle"}</span>
      </div>

      {!project ? (
        <p className="empty-copy">Create and run a project to see the delivered video here.</p>
      ) : !finalVideoUrl ? (
        <p className="empty-copy">The final video is not ready yet. Keep the workflow running until composition finishes.</p>
      ) : (
        <>
          <video className="final-video" src={finalVideoUrl} controls playsInline />
          <div className="delivery-actions">
            <a className="primary-button button-link" href={finalVideoUrl} target="_blank" rel="noreferrer">
              Open Final Video
            </a>
            <a className="secondary-link" href={finalVideoUrl} download>
              Download MP4
            </a>
          </div>
        </>
      )}
    </section>
  );
}
