from __future__ import annotations

from pathlib import Path
import json
import threading

from video_workflow_service.domain.models import Project
from video_workflow_service.infrastructure.config import ServiceSettings


class ProjectRepository:
    def __init__(self, settings: ServiceSettings):
        self._settings = settings
        self._lock = threading.Lock()

    def _project_path(self, project_id: str) -> Path:
        return self._settings.project_dir / f"{project_id}.json"

    def save(self, project: Project) -> Project:
        project.touch()
        payload = project.to_dict()
        target_path = self._project_path(project.project_id)
        temp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
        with self._lock:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(target_path)
        return project

    def load(self, project_id: str) -> Project:
        path = self._project_path(project_id)
        if not path.exists():
            raise KeyError(f"project not found: {project_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Project.from_dict(payload)

    def list(self) -> list[Project]:
        projects: list[Project] = []
        for path in sorted(self._settings.project_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            projects.append(Project.from_dict(payload))
        return projects
