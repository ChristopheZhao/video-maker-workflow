from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from pathlib import Path
from typing import Any
import json
import mimetypes
import re
import urllib.parse

from video_workflow_service.application.workflow_service import WorkflowService
from video_workflow_service.infrastructure.config import ServiceSettings, load_settings


logger = logging.getLogger(__name__)


class WorkflowRequestHandler(BaseHTTPRequestHandler):
    service: WorkflowService
    settings: ServiceSettings
    _backend_prefixes = ("/health", "/providers", "/projects", "/artifacts")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            self._serve_frontend_entry()
            return
        if path == "/health":
            self._json_response({"status": "ok"})
            return
        if path == "/providers":
            self._json_response(self.service.list_provider_capabilities())
            return
        if path == "/projects":
            payload = [
                self.service.serialize_project(project, base_url=self._base_url())
                for project in self.service.list_projects()
            ]
            self._json_response(payload)
            return
        if path.startswith("/artifacts/"):
            self._serve_artifact(path.removeprefix("/artifacts/"))
            return

        match = re.fullmatch(r"/projects/([^/]+)", path)
        if match:
            project = self.service.get_project(match.group(1))
            self._json_response(self.service.serialize_project(project, base_url=self._base_url()))
            return
        match = re.fullmatch(r"/projects/([^/]+)/workflow/status", path)
        if match:
            project = self.service.get_project(match.group(1))
            payload = self.service.serialize_project(project, base_url=self._base_url())
            self._json_response(
                {
                    "project_id": project.project_id,
                    "project_status": project.status,
                    "workflow_run_job": payload.get("workflow_run_job"),
                    "project": payload,
                }
            )
            return
        if self._should_serve_frontend_asset(path):
            self._serve_frontend_asset(path)
            return
        if self._should_serve_frontend_entry(path):
            self._serve_frontend_entry()
            return
        self._json_error(HTTPStatus.NOT_FOUND, "Route not found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()

        try:
            if path == "/projects":
                project = self.service.create_project(
                    title=str(body.get("title", "Video Workflow Service")),
                    prompt=str(body.get("prompt", "")),
                    target_duration_seconds=int(body.get("target_duration_seconds", 15)),
                    aspect_ratio=body.get("aspect_ratio"),
                    provider=body.get("provider"),
                    scene_count=body.get("scene_count"),
                    workflow_mode=body.get("workflow_mode"),
                    scene1_first_frame_source=body.get("scene1_first_frame_source"),
                    scene1_first_frame_image=body.get("scene1_first_frame_image"),
                    scene1_first_frame_prompt=body.get("scene1_first_frame_prompt"),
                )
                self._json_response(
                    self.service.serialize_project(project, base_url=self._base_url()),
                    status=HTTPStatus.CREATED,
                )
                return
            handlers = [
                (r"/projects/([^/]+)/optimize-prompt", self._handle_optimize_prompt),
                (r"/projects/([^/]+)/plan-scenes", self._handle_plan_scenes),
                (r"/projects/([^/]+)/storyboards/upload", self._handle_storyboard_upload),
                (r"/projects/([^/]+)/generate-scenes", self._handle_generate_scenes),
                (r"/projects/([^/]+)/compose", self._handle_compose),
                (r"/projects/([^/]+)/workflow/run", self._handle_workflow_run),
                (r"/projects/([^/]+)/workflow/start", self._handle_workflow_start),
                (r"/projects/([^/]+)/scenes/([^/]+)/generate", self._handle_scene_generate),
                (r"/projects/([^/]+)/scenes/([^/]+)/approve", self._handle_scene_approve),
                (r"/projects/([^/]+)/characters/([^/]+)/generate-reference", self._handle_character_generate_reference),
                (r"/projects/([^/]+)/characters/([^/]+)/upload-reference", self._handle_character_upload_reference),
                (r"/projects/([^/]+)/characters/([^/]+)/approve", self._handle_character_approve),
            ]
            for pattern, handler in handlers:
                match = re.fullmatch(pattern, path)
                if match:
                    groups = match.groups()
                    payload, status = handler(*groups, body)
                    self._json_response(payload, status=status)
                    return
        except KeyError as exc:
            self._json_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        except Exception as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._json_error(HTTPStatus.NOT_FOUND, "Route not found")

    def do_PATCH(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()

        try:
            handlers = [
                (r"/projects/([^/]+)/scenes/([^/]+)/prompt", self._handle_scene_prompt_update),
            ]
            for pattern, handler in handlers:
                match = re.fullmatch(pattern, path)
                if match:
                    groups = match.groups()
                    payload, status = handler(*groups, body)
                    self._json_response(payload, status=status)
                    return
        except KeyError as exc:
            self._json_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        except Exception as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self._json_error(HTTPStatus.NOT_FOUND, "Route not found")

    def log_message(self, format: str, *args: Any) -> None:
        host = self.client_address[0] if hasattr(self, "client_address") else "-"
        logger.info("http %s - " + format, host, *args)

    def _handle_optimize_prompt(self, project_id: str, _: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.optimize_prompt(project_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_plan_scenes(self, project_id: str, _: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.plan_scenes(project_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_storyboard_upload(self, project_id: str, body: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        items = body.get("scenes")
        if not isinstance(items, list):
            raise ValueError("Body must contain a scenes list")
        project = self.service.upload_storyboards(project_id, items)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_generate_scenes(self, project_id: str, _: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.generate_scenes(project_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_compose(self, project_id: str, _: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.compose_video(project_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_workflow_run(self, project_id: str, _: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.run_workflow(project_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_workflow_start(self, project_id: str, _: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.start_workflow_run(project_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.ACCEPTED

    def _handle_scene_generate(
        self,
        project_id: str,
        scene_id: str,
        _: dict[str, Any],
    ) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.start_scene_generation(project_id, scene_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.ACCEPTED

    def _handle_scene_approve(
        self,
        project_id: str,
        scene_id: str,
        _: dict[str, Any],
    ) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.approve_scene(project_id, scene_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_character_generate_reference(
        self,
        project_id: str,
        character_id: str,
        _: dict[str, Any],
    ) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.regenerate_character_anchor(project_id, character_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_character_upload_reference(
        self,
        project_id: str,
        character_id: str,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], HTTPStatus]:
        reference_image = str(body.get("reference_image", "")).strip()
        if not reference_image:
            raise ValueError("Body must contain reference_image")
        project = self.service.replace_character_anchor(
            project_id,
            character_id,
            reference_image=reference_image,
        )
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_character_approve(
        self,
        project_id: str,
        character_id: str,
        _: dict[str, Any],
    ) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.approve_character_anchor(project_id, character_id)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _handle_scene_prompt_update(
        self,
        project_id: str,
        scene_id: str,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], HTTPStatus]:
        project = self.service.update_scene_prompt(project_id, scene_id, body)
        return self.service.serialize_project(project, base_url=self._base_url()), HTTPStatus.OK

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _base_url(self) -> str:
        return f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"

    def _json_response(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def _json_error(self, status: HTTPStatus, message: str) -> None:
        self._json_response({"error": message, "status": int(status)}, status=status)

    def _serve_artifact(self, rel_path: str) -> None:
        candidate = (self.settings.artifact_dir / rel_path).resolve()
        artifact_root = self.settings.artifact_dir.resolve()
        if artifact_root not in candidate.parents and candidate != artifact_root:
            self._json_error(HTTPStatus.FORBIDDEN, "Artifact path forbidden")
            return
        if not candidate.exists() or not candidate.is_file():
            self._json_error(HTTPStatus.NOT_FOUND, "Artifact not found")
            return
        self._serve_file(candidate)

    def _serve_frontend_entry(self) -> None:
        index_path = self.settings.frontend_dist_dir / "index.html"
        if not index_path.exists():
            self._frontend_build_missing()
            return
        self._serve_file(index_path)

    def _serve_frontend_asset(self, path: str) -> None:
        dist_root = self.settings.frontend_dist_dir.resolve()
        candidate = (dist_root / path.lstrip("/")).resolve()
        if dist_root not in candidate.parents and candidate != dist_root:
            self._json_error(HTTPStatus.FORBIDDEN, "Frontend asset path forbidden")
            return
        if not candidate.exists() or not candidate.is_file():
            self._json_error(HTTPStatus.NOT_FOUND, "Frontend asset not found")
            return
        self._serve_file(candidate)

    def _serve_file(self, path: Path) -> None:
        mime_type, _ = mimetypes.guess_type(str(path))
        content_type = mime_type or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def _should_serve_frontend_asset(self, path: str) -> bool:
        if path.startswith("/assets/"):
            return True
        return Path(path).suffix.lower() in {
            ".css",
            ".js",
            ".mjs",
            ".map",
            ".ico",
            ".png",
            ".jpg",
            ".jpeg",
            ".svg",
            ".webp",
        }

    def _should_serve_frontend_entry(self, path: str) -> bool:
        if path in {"/", "/index.html"}:
            return True
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in self._backend_prefixes):
            return False
        return Path(path).suffix == ""

    def _frontend_build_missing(self) -> None:
        body = (
            "<!doctype html><html><body>"
            "<h1>Frontend build not found</h1>"
            "<p>Run <code>npm install</code> and <code>npm run build</code> in <code>frontend/</code>.</p>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def _safe_write(self, body: bytes) -> None:
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            logger.info(
                "client disconnected before response completed | path=%s",
                getattr(self, "path", "-"),
            )


def run_server(*, host: str, port: int, settings: ServiceSettings | None = None) -> None:
    current_settings = settings or load_settings()
    log_level_name = current_settings.log_level.upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        logging.getLogger().setLevel(log_level)
    service = WorkflowService(current_settings)
    handler = type(
        "BoundWorkflowRequestHandler",
        (WorkflowRequestHandler,),
        {"service": service, "settings": current_settings},
    )
    server = ThreadingHTTPServer((host, port), handler)
    logger.info(
        "server listening on http://%s:%s | log_level=%s",
        host,
        port,
        log_level_name,
    )
    server.serve_forever()
