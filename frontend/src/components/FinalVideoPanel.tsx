import { useEffect, useRef, useState } from "react";

import type { ProjectRecord } from "../api/client";
import { formatEnumLabel } from "../i18n/catalog";
import { useI18n } from "../i18n/provider";

interface FinalVideoPanelProps {
  project: ProjectRecord | null;
  onExportSubtitledVideo: () => void;
}

function syncSubtitleTrackMode(video: HTMLVideoElement | null, enabled: boolean) {
  if (!video) {
    return;
  }
  for (let index = 0; index < video.textTracks.length; index += 1) {
    video.textTracks[index].mode = enabled ? "showing" : "disabled";
  }
}

export function FinalVideoPanel({ project, onExportSubtitledVideo }: FinalVideoPanelProps) {
  const { messages } = useI18n();
  const finalVideoUrl = project?.final_video_url;
  const finalVideoDownloadUrl = finalVideoUrl ? `${finalVideoUrl}${finalVideoUrl.includes("?") ? "&" : "?"}download=1` : null;
  const subtitle = project?.subtitle;
  const subtitleStatus = subtitle?.status ?? "disabled";
  const subtitleReady = Boolean(subtitle?.srt_url || subtitle?.vtt_url);
  const subtitlePending = subtitleStatus === "queued" || subtitleStatus === "running" || subtitleStatus === "pending";
  const subtitleVttUrl = subtitle?.vtt_url ?? null;
  const packageUrl = subtitle?.package_url ?? null;
  const burnedVideoUrl = subtitle?.burned_video_url ?? null;
  const burnedVideoDownloadUrl = burnedVideoUrl ? `${burnedVideoUrl}${burnedVideoUrl.includes("?") ? "&" : "?"}download=1` : null;
  const burnStatus = subtitle?.burn_status ?? "idle";
  const burnRunning = burnStatus === "queued" || burnStatus === "running";
  const burnReady = Boolean(burnedVideoUrl) && burnStatus === "completed";
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [showSubtitles, setShowSubtitles] = useState(Boolean(subtitleVttUrl));

  useEffect(() => {
    if (subtitleVttUrl) {
      setShowSubtitles(true);
    }
  }, [subtitleVttUrl, project?.project_id]);

  useEffect(() => {
    syncSubtitleTrackMode(videoRef.current, showSubtitles);
  }, [showSubtitles, subtitleVttUrl, finalVideoUrl]);

  return (
    <section className="panel final-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">{messages.finalVideo.eyebrow}</p>
          <h2>{messages.finalVideo.title}</h2>
        </div>
        <span className="panel-badge">{formatEnumLabel(project?.status ?? "idle", messages.enums)}</span>
      </div>

      {!project ? (
        <p className="empty-copy">{messages.finalVideo.noProject}</p>
      ) : !finalVideoUrl ? (
        <p className="empty-copy">{messages.finalVideo.notReady}</p>
      ) : (
        <>
          <video
            ref={videoRef}
            className="final-video"
            controls
            playsInline
            onLoadedMetadata={() => syncSubtitleTrackMode(videoRef.current, showSubtitles)}
          >
            <source src={finalVideoUrl} type="video/mp4" />
            {subtitleVttUrl ? (
              <track
                key={subtitleVttUrl}
                kind="subtitles"
                src={subtitleVttUrl}
                srcLang={subtitle?.language || "und"}
                label={messages.finalVideo.subtitleTrackLabel}
                default
              />
            ) : null}
          </video>
          <div className="delivery-actions">
            <a className="secondary-button button-link" href={finalVideoUrl} target="_blank" rel="noreferrer">
              {messages.finalVideo.openFinalVideo}
            </a>
            {subtitle?.enabled && subtitleReady && packageUrl ? (
              <>
                <a className="primary-button button-link" href={packageUrl}>
                  {messages.finalVideo.downloadDeliveryPackage}
                </a>
                {burnReady && burnedVideoDownloadUrl ? (
                  <a className="primary-button button-link" href={burnedVideoDownloadUrl} download>
                    {messages.finalVideo.downloadSubtitledVideo}
                  </a>
                ) : (
                  <button className="primary-button" onClick={onExportSubtitledVideo} disabled={burnRunning}>
                    {burnRunning ? messages.finalVideo.exportingSubtitledVideo : messages.finalVideo.exportSubtitledVideo}
                  </button>
                )}
              </>
            ) : (
              <a className="primary-button button-link" href={finalVideoDownloadUrl ?? finalVideoUrl} download>
                {messages.finalVideo.downloadMp4}
              </a>
            )}
            {subtitle?.enabled && subtitleVttUrl ? (
              <button className="secondary-button" onClick={() => setShowSubtitles((current) => !current)}>
                {showSubtitles ? messages.finalVideo.hideSubtitles : messages.finalVideo.showSubtitles}
              </button>
            ) : null}
          </div>
          {subtitle?.enabled ? (
            <div className="delivery-status-stack">
              <p className="scene-meta">
                {subtitleReady
                  ? messages.finalVideo.subtitleReady
                  : subtitlePending
                    ? messages.finalVideo.subtitlePreparing
                    : subtitleStatus === "failed"
                      ? messages.finalVideo.subtitleFailed
                      : subtitleStatus === "skipped" || subtitleStatus === "not_applicable"
                        ? messages.finalVideo.subtitleSkipped
                        : messages.finalVideo.subtitlePlanned}
              </p>
              {subtitleReady ? (
                <p className="scene-meta">
                  {burnReady
                    ? messages.finalVideo.subtitledVideoReady
                    : burnRunning
                      ? messages.finalVideo.subtitledVideoPreparing
                      : burnStatus === "failed"
                        ? messages.finalVideo.subtitledVideoFailed
                        : messages.finalVideo.subtitledVideoNotExported}
                </p>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
