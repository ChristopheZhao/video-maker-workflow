from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
import json

from video_workflow_service.domain.models import utc_now
from video_workflow_service.infrastructure.config import ServiceSettings


@dataclass(slots=True)
class WorkflowTraceEvent:
    event_type: str
    project_id: str
    step: str
    status: str
    actor: str = "system"
    timestamp: str = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)


class WorkflowTraceLogger:
    def __init__(self, settings: ServiceSettings):
        self._settings = settings
        self._lock = Lock()

    def append(
        self,
        project_id: str,
        *,
        event_type: str,
        step: str,
        status: str,
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> None:
        event = WorkflowTraceEvent(
            event_type=event_type,
            project_id=project_id,
            step=step,
            status=status,
            actor=actor,
            details=dict(details or {}),
        )
        path = self._trace_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def trace_path(self, project_id: str) -> Path:
        return self._trace_path(project_id)

    def _trace_path(self, project_id: str) -> Path:
        return self._settings.log_dir / project_id / "workflow_trace.jsonl"
