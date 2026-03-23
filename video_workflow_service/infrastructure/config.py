from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Mapping


def _load_env_file(
    path: Path,
    *,
    environment: dict[str, str],
    protected_keys: set[str],
) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or not value:
            continue
        if key in protected_keys:
            continue
        environment[key] = value


def _build_environment(root_dir: Path) -> dict[str, str]:
    environment = dict(os.environ)
    protected_keys = set(os.environ)
    _load_env_file(
        root_dir / ".env",
        environment=environment,
        protected_keys=protected_keys,
    )
    _load_env_file(
        root_dir / ".env.local",
        environment=environment,
        protected_keys=protected_keys,
    )
    return environment


@dataclass(slots=True)
class ServiceSettings:
    root_dir: Path
    data_dir: Path
    project_dir: Path
    artifact_dir: Path
    log_dir: Path
    frontend_dir: Path
    frontend_dist_dir: Path
    ffmpeg_bin: str
    ffprobe_bin: str
    host: str
    port: int
    log_level: str
    default_provider: str
    default_scene_duration: int
    default_resolution: str
    default_aspect_ratio: str
    default_scene_count: int
    workflow_max_workers: int
    composer_boundary_trim_seconds: float
    composer_video_crossfade_seconds: float
    composer_audio_crossfade_seconds: float
    subtitle_service_name: str
    subtitle_request_timeout_seconds: int
    doubao_api_key: str
    doubao_base_url: str
    doubao_create_path: str
    doubao_query_path: str
    doubao_default_model: str
    doubao_min_scene_duration_seconds: int
    doubao_max_scene_duration_seconds: int
    doubao_image_generate_path: str
    image_default_model: str
    image_character_model: str
    llm_provider: str
    llm_default_model: str
    deepseek_default_model: str
    llm_character_anchor_provider: str | None
    llm_scene_character_cast_provider: str | None
    llm_prompt_optimize_provider: str | None
    llm_story_plan_provider: str | None
    llm_scene_plan_provider: str | None
    llm_dialogue_allocate_provider: str | None
    llm_first_frame_analyze_provider: str | None
    llm_scene_prompt_render_provider: str | None
    llm_scene_prompt_revise_provider: str | None
    llm_dialogue_split_provider: str | None
    llm_character_anchor_model: str | None
    llm_scene_character_cast_model: str | None
    llm_prompt_optimize_model: str | None
    llm_story_plan_model: str | None
    llm_scene_plan_model: str | None
    llm_dialogue_allocate_model: str | None
    llm_first_frame_analyze_model: str | None
    llm_scene_prompt_render_model: str | None
    llm_scene_prompt_revise_model: str | None
    llm_dialogue_split_model: str | None
    llm_timeout_seconds: int
    doubao_llm_api_key: str
    doubao_llm_base_url: str
    doubao_llm_chat_path: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_chat_path: str
    volcengine_speech_app_id: str
    volcengine_speech_access_token: str
    volcengine_speech_base_url: str
    volcengine_speech_ata_submit_path: str
    volcengine_speech_ata_query_path: str
    volcengine_speech_ata_punctuation_mode: int
    volcengine_speech_asr_submit_path: str
    volcengine_speech_asr_resource_id: str
    volcengine_speech_asr_model_name: str

    @classmethod
    def for_root(
        cls,
        root_dir: Path,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> "ServiceSettings":
        env = environment or os.environ
        data_dir = root_dir / "runtime_data"
        project_dir = data_dir / "projects"
        artifact_dir = data_dir / "artifacts"
        log_dir = data_dir / "logs"
        frontend_dir = root_dir / "frontend"
        frontend_dist_dir = frontend_dir / "dist"
        doubao_api_key = env.get("DOUBAO_API_KEY", "")
        doubao_base_url = env.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com")
        return cls(
            root_dir=root_dir,
            data_dir=data_dir,
            project_dir=project_dir,
            artifact_dir=artifact_dir,
            log_dir=log_dir,
            frontend_dir=frontend_dir,
            frontend_dist_dir=frontend_dist_dir,
            ffmpeg_bin=env.get("FFMPEG_BIN", "ffmpeg"),
            ffprobe_bin=env.get("FFPROBE_BIN", "ffprobe"),
            host=env.get("VIDEO_WORKFLOW_HOST", "127.0.0.1"),
            port=int(env.get("VIDEO_WORKFLOW_PORT", "8787")),
            log_level=env.get("VIDEO_WORKFLOW_LOG_LEVEL", "INFO").upper(),
            default_provider=env.get("VIDEO_WORKFLOW_PROVIDER", "doubao"),
            default_scene_duration=int(env.get("VIDEO_WORKFLOW_SCENE_DURATION", "5")),
            default_resolution=env.get("VIDEO_WORKFLOW_RESOLUTION", "1280x720"),
            default_aspect_ratio=env.get("VIDEO_WORKFLOW_ASPECT_RATIO", "16:9"),
            default_scene_count=int(env.get("VIDEO_WORKFLOW_SCENE_COUNT", "3")),
            workflow_max_workers=int(env.get("VIDEO_WORKFLOW_MAX_WORKERS", "2")),
            composer_boundary_trim_seconds=float(
                env.get("VIDEO_WORKFLOW_COMPOSER_BOUNDARY_TRIM_SECONDS", "0.08")
            ),
            composer_video_crossfade_seconds=float(
                env.get("VIDEO_WORKFLOW_COMPOSER_VIDEO_CROSSFADE_SECONDS", "0.18")
            ),
            composer_audio_crossfade_seconds=float(
                env.get("VIDEO_WORKFLOW_COMPOSER_AUDIO_CROSSFADE_SECONDS", "0.15")
            ),
            subtitle_service_name=env.get(
                "VIDEO_WORKFLOW_SUBTITLE_SERVICE",
                "volcengine_speech",
            ).strip().lower(),
            subtitle_request_timeout_seconds=int(
                env.get("VIDEO_WORKFLOW_SUBTITLE_REQUEST_TIMEOUT_SECONDS", "300")
            ),
            doubao_api_key=doubao_api_key,
            doubao_base_url=doubao_base_url,
            doubao_create_path=env.get(
                "DOUBAO_VIDEO_CREATE_PATH",
                "/api/v3/contents/generations/tasks",
            ),
            doubao_query_path=env.get(
                "DOUBAO_VIDEO_QUERY_PATH",
                "/api/v3/contents/generations/tasks/{task_id}",
            ),
            doubao_default_model=env.get(
                "DOUBAO_DEFAULT_MODEL",
                "doubao-seedance-1-5-pro-251215",
            ),
            doubao_min_scene_duration_seconds=int(
                env.get("DOUBAO_MIN_SCENE_DURATION_SECONDS", "2")
            ),
            doubao_max_scene_duration_seconds=int(
                env.get("DOUBAO_MAX_SCENE_DURATION_SECONDS", "12")
            ),
            doubao_image_generate_path=env.get(
                "DOUBAO_IMAGE_GENERATE_PATH",
                "/api/v3/images/generations",
            ).strip(),
            image_default_model=env.get(
                "VIDEO_WORKFLOW_IMAGE_DEFAULT_MODEL",
                "doubao-seedream-5-0-lite-260128",
            ).strip(),
            image_character_model=env.get(
                "VIDEO_WORKFLOW_IMAGE_CHARACTER_MODEL",
                env.get(
                    "VIDEO_WORKFLOW_IMAGE_DEFAULT_MODEL",
                    "doubao-seedream-5-0-lite-260128",
                ),
            ).strip(),
            llm_provider=env.get("VIDEO_WORKFLOW_LLM_PROVIDER", "mock").strip().lower(),
            llm_default_model=env.get(
                "VIDEO_WORKFLOW_LLM_DEFAULT_MODEL",
                "doubao-seed-2-0-lite-260215",
            ).strip(),
            deepseek_default_model=env.get(
                "DEEPSEEK_DEFAULT_MODEL",
                "deepseek-chat",
            ).strip(),
            llm_character_anchor_provider=(
                env.get("VIDEO_WORKFLOW_LLM_CHARACTER_ANCHOR_PROVIDER", "").strip().lower() or None
            ),
            llm_scene_character_cast_provider=(
                env.get("VIDEO_WORKFLOW_LLM_SCENE_CHARACTER_CAST_PROVIDER", "").strip().lower() or None
            ),
            llm_prompt_optimize_provider=(
                env.get("VIDEO_WORKFLOW_LLM_PROMPT_OPTIMIZE_PROVIDER", "").strip().lower() or None
            ),
            llm_story_plan_provider=(
                env.get("VIDEO_WORKFLOW_LLM_STORY_PLAN_PROVIDER", "").strip().lower() or None
            ),
            llm_scene_plan_provider=(
                env.get("VIDEO_WORKFLOW_LLM_SCENE_PLAN_PROVIDER", "").strip().lower() or None
            ),
            llm_dialogue_allocate_provider=(
                env.get("VIDEO_WORKFLOW_LLM_DIALOGUE_ALLOCATE_PROVIDER", "").strip().lower() or None
            ),
            llm_first_frame_analyze_provider=(
                env.get("VIDEO_WORKFLOW_LLM_FIRST_FRAME_ANALYZE_PROVIDER", "").strip().lower() or None
            ),
            llm_scene_prompt_render_provider=(
                env.get("VIDEO_WORKFLOW_LLM_SCENE_PROMPT_RENDER_PROVIDER", "").strip().lower() or None
            ),
            llm_scene_prompt_revise_provider=(
                env.get("VIDEO_WORKFLOW_LLM_SCENE_PROMPT_REVISE_PROVIDER", "").strip().lower() or None
            ),
            llm_dialogue_split_provider=(
                env.get("VIDEO_WORKFLOW_LLM_DIALOGUE_SPLIT_PROVIDER", "").strip().lower() or None
            ),
            llm_character_anchor_model=(
                env.get("VIDEO_WORKFLOW_LLM_CHARACTER_ANCHOR_MODEL", "").strip() or None
            ),
            llm_scene_character_cast_model=(
                env.get("VIDEO_WORKFLOW_LLM_SCENE_CHARACTER_CAST_MODEL", "").strip() or None
            ),
            llm_prompt_optimize_model=(
                env.get("VIDEO_WORKFLOW_LLM_PROMPT_OPTIMIZE_MODEL", "").strip() or None
            ),
            llm_story_plan_model=(
                env.get("VIDEO_WORKFLOW_LLM_STORY_PLAN_MODEL", "").strip() or None
            ),
            llm_scene_plan_model=(
                env.get("VIDEO_WORKFLOW_LLM_SCENE_PLAN_MODEL", "").strip() or None
            ),
            llm_dialogue_allocate_model=(
                env.get("VIDEO_WORKFLOW_LLM_DIALOGUE_ALLOCATE_MODEL", "").strip() or None
            ),
            llm_first_frame_analyze_model=(
                env.get("VIDEO_WORKFLOW_LLM_FIRST_FRAME_ANALYZE_MODEL", "").strip() or None
            ),
            llm_scene_prompt_render_model=(
                env.get("VIDEO_WORKFLOW_LLM_SCENE_PROMPT_RENDER_MODEL", "").strip() or None
            ),
            llm_scene_prompt_revise_model=(
                env.get("VIDEO_WORKFLOW_LLM_SCENE_PROMPT_REVISE_MODEL", "").strip() or None
            ),
            llm_dialogue_split_model=(
                env.get("VIDEO_WORKFLOW_LLM_DIALOGUE_SPLIT_MODEL", "").strip() or None
            ),
            llm_timeout_seconds=int(env.get("VIDEO_WORKFLOW_LLM_TIMEOUT_SECONDS", "120")),
            doubao_llm_api_key=env.get("DOUBAO_LLM_API_KEY", doubao_api_key).strip(),
            doubao_llm_base_url=env.get("DOUBAO_LLM_BASE_URL", doubao_base_url).strip(),
            doubao_llm_chat_path=env.get(
                "DOUBAO_LLM_CHAT_PATH",
                "/api/v3/chat/completions",
            ).strip(),
            deepseek_api_key=env.get("DEEPSEEK_API_KEY", "").strip(),
            deepseek_base_url=env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            deepseek_chat_path=env.get("DEEPSEEK_CHAT_PATH", "/chat/completions").strip(),
            volcengine_speech_app_id=env.get("VOLCENGINE_SPEECH_APP_ID", "").strip(),
            volcengine_speech_access_token=env.get("VOLCENGINE_SPEECH_ACCESS_TOKEN", "").strip(),
            volcengine_speech_base_url=env.get(
                "VOLCENGINE_SPEECH_BASE_URL",
                "https://openspeech.bytedance.com",
            ).strip(),
            volcengine_speech_ata_submit_path=env.get(
                "VOLCENGINE_SPEECH_ATA_SUBMIT_PATH",
                "/api/v1/vc/ata/submit",
            ).strip(),
            volcengine_speech_ata_query_path=env.get(
                "VOLCENGINE_SPEECH_ATA_QUERY_PATH",
                "/api/v1/vc/ata/query",
            ).strip(),
            volcengine_speech_ata_punctuation_mode=int(
                env.get("VOLCENGINE_SPEECH_ATA_PUNCTUATION_MODE", "3")
            ),
            volcengine_speech_asr_submit_path=env.get(
                "VOLCENGINE_SPEECH_ASR_SUBMIT_PATH",
                "/api/v3/auc/bigmodel/recognize/flash",
            ).strip(),
            volcengine_speech_asr_resource_id=env.get(
                "VOLCENGINE_SPEECH_ASR_RESOURCE_ID",
                "volc.bigasr.auc_turbo",
            ).strip(),
            volcengine_speech_asr_model_name=env.get(
                "VOLCENGINE_SPEECH_ASR_MODEL_NAME",
                "bigmodel",
            ).strip(),
        )


DemoSettings = ServiceSettings


def load_settings(root_dir: str | Path | None = None) -> ServiceSettings:
    if root_dir is None:
        root = Path(__file__).resolve().parents[2]
    else:
        root = Path(root_dir).resolve()
    environment = _build_environment(root)
    settings = ServiceSettings.for_root(root, environment=environment)
    settings.project_dir.mkdir(parents=True, exist_ok=True)
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    return settings
