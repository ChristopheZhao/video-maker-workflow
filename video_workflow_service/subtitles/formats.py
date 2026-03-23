from __future__ import annotations

from video_workflow_service.subtitles.service import SubtitleCue


def render_srt(cues: list[SubtitleCue]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_format_timestamp(cue.start_time_ms, separator=',')} --> {_format_timestamp(cue.end_time_ms, separator=',')}",
                    cue.text.strip(),
                ]
            ).strip()
        )
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def render_vtt(cues: list[SubtitleCue]) -> str:
    blocks = ["WEBVTT"]
    for cue in cues:
        blocks.append(
            "\n".join(
                [
                    f"{_format_timestamp(cue.start_time_ms, separator='.')} --> {_format_timestamp(cue.end_time_ms, separator='.')}",
                    cue.text.strip(),
                ]
            ).strip()
        )
    return "\n\n".join(blocks).strip() + "\n"


def _format_timestamp(total_ms: int, *, separator: str) -> str:
    clamped = max(0, int(total_ms))
    hours, remainder = divmod(clamped, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{milliseconds:03d}"
