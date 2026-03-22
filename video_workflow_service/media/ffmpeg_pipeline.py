from __future__ import annotations

from pathlib import Path
import subprocess


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


def compose_clips(
    *,
    ffmpeg_bin: str,
    clip_paths: list[Path],
    concat_list_path: Path,
    output_path: Path,
) -> None:
    concat_list_path.write_text(
        "\n".join(f"file '{clip.resolve()}'" for clip in clip_paths),
        encoding="utf-8",
    )
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
