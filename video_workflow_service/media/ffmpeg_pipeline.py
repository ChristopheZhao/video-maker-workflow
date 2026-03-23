from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

DEFAULT_SUBTITLE_FONT_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NotoSansSC-Regular.otf"
)
DEFAULT_SUBTITLE_FONT_NAME = "Noto Sans SC"


def resolution_for_ratio(ratio: str, default_resolution: str) -> str:
    mapping = {
        "16:9": "1280x720",
        "9:16": "720x1280",
        "1:1": "1024x1024",
    }
    return mapping.get(ratio, default_resolution)


def run_ffmpeg(cmd: list[str]) -> None:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffmpeg failed")


@dataclass(slots=True)
class ClipProbe:
    duration_seconds: float
    has_video: bool
    has_audio: bool


def render_color_clip(
    *,
    ffmpeg_bin: str,
    color: str,
    output_path: Path,
    duration_seconds: int,
    size: str,
) -> None:
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={size}:d={duration_seconds}",
        "-r",
        "24",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    run_ffmpeg(cmd)


def render_image_clip(
    *,
    ffmpeg_bin: str,
    image_path: Path,
    output_path: Path,
    duration_seconds: int,
    size: str,
) -> None:
    width, height = size.split("x", maxsplit=1)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-t",
        str(duration_seconds),
        "-vf",
        vf,
        "-r",
        "24",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    run_ffmpeg(cmd)


def extract_final_frame(*, ffmpeg_bin: str, video_path: Path, output_path: Path) -> None:
    cmd = [
        ffmpeg_bin,
        "-y",
        "-sseof",
        "-0.05",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(output_path),
    ]
    run_ffmpeg(cmd)


def extract_audio_track(*, ffmpeg_bin: str, video_path: Path, output_path: Path) -> None:
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    run_ffmpeg(cmd)


def _escape_subtitle_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")


def _build_burned_subtitle_filter(
    *,
    subtitle_path: Path,
    font_path: Path,
    font_name: str,
) -> str:
    subtitle_filter_path = _escape_subtitle_filter_path(subtitle_path)
    font_dir = _escape_subtitle_filter_path(font_path.parent)
    safe_font_name = font_name.replace("'", r"\'")
    return (
        f"subtitles='{subtitle_filter_path}':"
        f"fontsdir='{font_dir}':"
        f"force_style='Fontname={safe_font_name},Fontsize=20,Outline=1.2,Shadow=0,MarginV=28'"
    )


def burn_subtitles_into_video(
    *,
    ffmpeg_bin: str,
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    font_path: Path | None = None,
    font_name: str = DEFAULT_SUBTITLE_FONT_NAME,
) -> None:
    resolved_font_path = (font_path or DEFAULT_SUBTITLE_FONT_PATH).resolve()
    if not resolved_font_path.exists():
        raise RuntimeError(
            "Subtitled video export requires a bundled CJK subtitle font, but none was found at "
            f"{resolved_font_path}"
        )
    filter_expr = _build_burned_subtitle_filter(
        subtitle_path=subtitle_path,
        font_path=resolved_font_path,
        font_name=font_name,
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        filter_expr,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_ffmpeg(cmd)


def probe_clip(*, ffprobe_bin: str, clip_path: Path) -> ClipProbe:
    proc = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration:stream=codec_type",
            str(clip_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffprobe failed")

    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") or []
    format_payload = payload.get("format") or {}
    duration_seconds = float(format_payload.get("duration") or 0.0)
    has_video = any(str(stream.get("codec_type", "")).lower() == "video" for stream in streams)
    has_audio = any(str(stream.get("codec_type", "")).lower() == "audio" for stream in streams)
    return ClipProbe(
        duration_seconds=duration_seconds,
        has_video=has_video,
        has_audio=has_audio,
    )


def _write_concat_list(*, concat_list_path: Path, clip_paths: list[Path]) -> None:
    concat_list_path.write_text(
        "\n".join(f"file '{clip.resolve()}'" for clip in clip_paths),
        encoding="utf-8",
    )


def _compose_clips_with_concat(
    *,
    ffmpeg_bin: str,
    clip_paths: list[Path],
    concat_list_path: Path,
    output_path: Path,
) -> dict[str, object]:
    _write_concat_list(concat_list_path=concat_list_path, clip_paths=clip_paths)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    run_ffmpeg(cmd)
    return {"mode": "concat", "clip_count": len(clip_paths)}


def _trim_window_for_clip(
    *,
    index: int,
    clip_count: int,
    duration_seconds: float,
    boundary_trim_seconds: float,
) -> tuple[float, float, float]:
    head_trim = boundary_trim_seconds if index > 0 else 0.0
    tail_trim = boundary_trim_seconds if index < clip_count - 1 else 0.0
    trimmed_duration = duration_seconds - head_trim - tail_trim
    return head_trim, tail_trim, trimmed_duration


def _can_apply_smoothed_compose(
    *,
    probes: list[ClipProbe],
    boundary_trim_seconds: float,
    video_crossfade_seconds: float,
    audio_crossfade_seconds: float,
) -> tuple[bool, str]:
    if len(probes) < 2:
        return False, "single_clip"
    if video_crossfade_seconds <= 0:
        return False, "video_crossfade_disabled"
    if any(not probe.has_video or probe.duration_seconds <= 0 for probe in probes):
        return False, "missing_video_or_duration"

    has_any_audio = any(probe.has_audio for probe in probes)
    if has_any_audio and not all(probe.has_audio for probe in probes):
        return False, "mixed_audio_presence"

    overlap_requirement = max(video_crossfade_seconds, audio_crossfade_seconds if has_any_audio else 0.0)
    for index, probe in enumerate(probes):
        _, _, trimmed_duration = _trim_window_for_clip(
            index=index,
            clip_count=len(probes),
            duration_seconds=probe.duration_seconds,
            boundary_trim_seconds=boundary_trim_seconds,
        )
        required_overlap_count = 2 if 0 < index < len(probes) - 1 else 1
        minimum_safe_duration = max(0.1, required_overlap_count * overlap_requirement + 0.02)
        if trimmed_duration <= minimum_safe_duration:
            return False, f"clip_too_short:{index + 1}"

    return True, "ok"


def _compose_clips_with_smoothing(
    *,
    ffmpeg_bin: str,
    clip_paths: list[Path],
    output_path: Path,
    probes: list[ClipProbe],
    boundary_trim_seconds: float,
    video_crossfade_seconds: float,
    audio_crossfade_seconds: float,
) -> dict[str, object]:
    filter_parts: list[str] = []
    trimmed_durations: list[float] = []
    audio_enabled = all(probe.has_audio for probe in probes)

    for index, probe in enumerate(probes):
        head_trim, tail_trim, trimmed_duration = _trim_window_for_clip(
            index=index,
            clip_count=len(probes),
            duration_seconds=probe.duration_seconds,
            boundary_trim_seconds=boundary_trim_seconds,
        )
        end_time = head_trim + trimmed_duration
        trimmed_durations.append(trimmed_duration)
        filter_parts.append(
            f"[{index}:v]trim=start={head_trim:.6f}:end={end_time:.6f},"
            f"setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
        )
        if audio_enabled:
            filter_parts.append(
                f"[{index}:a]atrim=start={head_trim:.6f}:end={end_time:.6f},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )

    current_video_label = "v0"
    current_video_duration = trimmed_durations[0]
    for index in range(1, len(clip_paths)):
        output_label = f"vx{index}"
        offset_seconds = max(0.0, current_video_duration - video_crossfade_seconds)
        filter_parts.append(
            f"[{current_video_label}][v{index}]"
            f"xfade=transition=fade:duration={video_crossfade_seconds:.6f}:offset={offset_seconds:.6f}"
            f"[{output_label}]"
        )
        current_video_label = output_label
        current_video_duration = current_video_duration + trimmed_durations[index] - video_crossfade_seconds

    current_audio_label: str | None = "a0" if audio_enabled else None
    if audio_enabled:
        for index in range(1, len(clip_paths)):
            output_label = f"ax{index}"
            filter_parts.append(
                f"[{current_audio_label}][a{index}]"
                f"acrossfade=d={audio_crossfade_seconds:.6f}:c1=tri:c2=tri"
                f"[{output_label}]"
            )
            current_audio_label = output_label

    cmd = [ffmpeg_bin, "-y"]
    for clip_path in clip_paths:
        cmd.extend(["-i", str(clip_path)])
    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            f"[{current_video_label}]",
        ]
    )
    if current_audio_label is not None:
        cmd.extend(["-map", f"[{current_audio_label}]"])
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if current_audio_label is not None:
        cmd.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        )
    cmd.extend(
        [
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run_ffmpeg(cmd)
    return {
        "mode": "smoothed",
        "clip_count": len(clip_paths),
        "boundary_trim_seconds": boundary_trim_seconds,
        "video_crossfade_seconds": video_crossfade_seconds,
        "audio_crossfade_seconds": audio_crossfade_seconds if current_audio_label is not None else 0.0,
        "audio_crossfade_applied": current_audio_label is not None,
    }


def compose_clips(
    *,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    clip_paths: list[Path],
    concat_list_path: Path,
    output_path: Path,
    boundary_trim_seconds: float = 0.08,
    video_crossfade_seconds: float = 0.18,
    audio_crossfade_seconds: float = 0.15,
) -> dict[str, object]:
    probes = [probe_clip(ffprobe_bin=ffprobe_bin, clip_path=clip_path) for clip_path in clip_paths]
    can_smooth, reason = _can_apply_smoothed_compose(
        probes=probes,
        boundary_trim_seconds=boundary_trim_seconds,
        video_crossfade_seconds=video_crossfade_seconds,
        audio_crossfade_seconds=audio_crossfade_seconds,
    )
    if not can_smooth:
        metadata = _compose_clips_with_concat(
            ffmpeg_bin=ffmpeg_bin,
            clip_paths=clip_paths,
            concat_list_path=concat_list_path,
            output_path=output_path,
        )
        metadata["fallback_reason"] = reason
        return metadata

    try:
        return _compose_clips_with_smoothing(
            ffmpeg_bin=ffmpeg_bin,
            clip_paths=clip_paths,
            output_path=output_path,
            probes=probes,
            boundary_trim_seconds=boundary_trim_seconds,
            video_crossfade_seconds=video_crossfade_seconds,
            audio_crossfade_seconds=audio_crossfade_seconds,
        )
    except RuntimeError as exc:
        metadata = _compose_clips_with_concat(
            ffmpeg_bin=ffmpeg_bin,
            clip_paths=clip_paths,
            concat_list_path=concat_list_path,
            output_path=output_path,
        )
        metadata["fallback_reason"] = "smoothing_failed"
        metadata["smoothing_error"] = str(exc)
        return metadata
