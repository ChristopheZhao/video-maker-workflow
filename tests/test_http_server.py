from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from video_workflow_service.api.http_server import WorkflowRequestHandler
from video_workflow_service.application.workflow_service import WorkflowService
from video_workflow_service.infrastructure.config import load_settings


class HttpServerTestCase(unittest.TestCase):
    def test_frontend_entry_route_serves_built_index(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {
                    "index.html": "<!doctype html><html><body><div id='root'>frontend ok</div></body></html>",
                    "assets/app.js": "console.log('ok');",
                },
            )
            service = WorkflowService(settings)
            index_handler = self._build_handler(service, settings, "/")
            index_handler.do_GET()
            asset_handler = self._build_handler(service, settings, "/assets/app.js")
            asset_handler.do_GET()

            body = index_handler.wfile.getvalue().decode("utf-8")
            asset = asset_handler.wfile.getvalue().decode("utf-8")
            self.assertIn("frontend ok", body)
            self.assertIn("console.log", asset)
            self.assertEqual(index_handler.status_code, 200)
            self.assertEqual(asset_handler.status_code, 200)

    def test_workflow_status_payload_includes_serialized_project(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            project = service.create_project(
                title="HTTP Project",
                prompt="A short workflow status verification project.",
                provider="mock",
                scene_count=3,
            )
            handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/workflow/status",
            )
            handler.do_GET()
            payload = json.loads(handler.wfile.getvalue().decode("utf-8"))

            self.assertEqual(payload["project_id"], project.project_id)
            self.assertEqual(payload["project_status"], "draft")
            self.assertIsNone(payload["workflow_run_job"])
            self.assertEqual(payload["project"]["project_id"], project.project_id)
            self.assertEqual(payload["project"]["provider"], "mock")
            self.assertEqual(handler.status_code, 200)

    def test_create_project_route_accepts_scene1_first_frame_payload(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            handler = self._build_handler(
                service,
                settings,
                "/projects",
                method="POST",
                body={
                    "title": "HTTP Scene 1 Source",
                    "prompt": "A portrait opening shot.",
                    "provider": "mock",
                    "workflow_mode": "hitl",
                    "scene1_first_frame_source": "upload",
                    "scene1_first_frame_image": "data:image/png;base64,c2NlbmUx",
                },
            )

            handler.do_POST()
            payload = json.loads(handler.wfile.getvalue().decode("utf-8"))

            self.assertEqual(handler.status_code, 201)
            self.assertEqual(payload["scene1_first_frame_source"], "upload")
            self.assertEqual(payload["scene1_first_frame_image"], "data:image/png;base64,c2NlbmUx")

    def test_create_project_route_accepts_subtitle_mode(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            handler = self._build_handler(
                service,
                settings,
                "/projects",
                method="POST",
                body={
                    "title": "HTTP Subtitle Mode",
                    "prompt": "A voiced trailer.",
                    "provider": "mock",
                    "workflow_mode": "hitl",
                    "subtitle_mode": "enabled",
                },
            )

            handler.do_POST()
            payload = json.loads(handler.wfile.getvalue().decode("utf-8"))

            self.assertEqual(handler.status_code, 201)
            self.assertEqual(payload["subtitle_mode"], "enabled")
            self.assertEqual(payload["subtitle"]["status"], "not_applicable")

    def test_json_response_ignores_broken_pipe(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            service = WorkflowService(settings)
            handler = self._build_handler(service, settings, "/health")
            handler.wfile = _BrokenWriter()

            handler._json_response({"status": "ok"})

            self.assertEqual(handler.status_code, 200)

    def test_hitl_scene_generate_and_approve_routes(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            project = service.create_project(
                title="HTTP HITL Project",
                prompt="A two-scene approval workflow.",
                provider="mock",
                scene_count=2,
                workflow_mode="hitl",
            )

            generate_handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/scenes/scene-01/generate",
                method="POST",
                body={},
            )
            generate_handler.do_POST()
            self.assertEqual(generate_handler.status_code, 202)

            self._wait_for_scene_status(service, project.project_id, "scene-01", "pending_review")

            approve_handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/scenes/scene-01/approve",
                method="POST",
                body={},
            )
            approve_handler.do_POST()
            payload = json.loads(approve_handler.wfile.getvalue().decode("utf-8"))

            self.assertEqual(approve_handler.status_code, 200)
            self.assertEqual(payload["scenes"][0]["status"], "approved")
            self.assertEqual(payload["hitl"]["workflow_mode"], "hitl")

    def test_scene_prompt_update_route_persists_prompt(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            project = service.create_project(
                title="HTTP Prompt Edit Project",
                prompt="A prompt editing flow.",
                provider="mock",
                workflow_mode="hitl",
            )
            service.plan_scenes(project.project_id)

            handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/scenes/scene-01/prompt",
                method="PATCH",
                body={"prompt": "A refined prompt from the browser."},
            )
            handler.do_PATCH()
            payload = json.loads(handler.wfile.getvalue().decode("utf-8"))

            self.assertEqual(handler.status_code, 200)
            self.assertEqual(payload["scenes"][0]["prompt"], "A refined prompt from the browser.")

    def test_scene_prompt_revise_route_updates_prompt(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            project = service.create_project(
                title="HTTP Prompt Revise Project",
                prompt="A lion waits behind zoo bars and dreams of the grassland.",
                provider="mock",
                workflow_mode="hitl",
            )
            service.optimize_prompt(project.project_id)
            service.plan_scenes(project.project_id)

            handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/scenes/scene-01/revise",
                method="POST",
                body={"feedback": "门不应该开着", "scope": "opening_still_and_prompt"},
            )
            handler.do_POST()
            payload = json.loads(handler.wfile.getvalue().decode("utf-8"))

            self.assertEqual(handler.status_code, 200)
            self.assertIn("门不应该开着", payload["scenes"][0]["prompt"])

    def test_artifact_download_query_sets_attachment_header(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            artifact = settings.artifact_dir / "delivery" / "final.mp4"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"fake-mp4")
            service = WorkflowService(settings)

            inline_handler = self._build_handler(service, settings, "/artifacts/delivery/final.mp4")
            inline_handler.do_GET()
            self.assertEqual(inline_handler.status_code, 200)
            self.assertNotIn("Content-Disposition", inline_handler.sent_headers)

            download_handler = self._build_handler(service, settings, "/artifacts/delivery/final.mp4?download=1")
            download_handler.do_GET()
            self.assertEqual(download_handler.status_code, 200)
            self.assertEqual(
                download_handler.sent_headers.get("Content-Disposition"),
                'attachment; filename="final.mp4"',
            )

    def test_artifact_route_serves_vtt_with_text_vtt_content_type(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            artifact = settings.artifact_dir / "delivery" / "final.vtt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
            service = WorkflowService(settings)

            handler = self._build_handler(service, settings, "/artifacts/delivery/final.vtt")
            handler.do_GET()

            self.assertEqual(handler.status_code, 200)
            self.assertEqual(handler.sent_headers.get("Content-Type"), "text/vtt")

    def test_delivery_package_route_serves_zip_attachment(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            project = service.create_project(
                title="HTTP Delivery Package",
                prompt="A voiced trailer.",
                provider="mock",
                subtitle_mode="enabled",
            )
            delivery_dir = settings.artifact_dir / project.project_id / "delivery"
            delivery_dir.mkdir(parents=True, exist_ok=True)
            final_video_path = delivery_dir / "final.mp4"
            srt_path = delivery_dir / "final.srt"
            vtt_path = delivery_dir / "final.vtt"
            final_video_path.write_bytes(b"fake-mp4")
            srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
            vtt_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
            project.final_video_rel_path = f"{project.project_id}/delivery/final.mp4"
            project.subtitle_srt_rel_path = f"{project.project_id}/delivery/final.srt"
            project.subtitle_vtt_rel_path = f"{project.project_id}/delivery/final.vtt"
            service.repo.save(project)

            handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/delivery-package",
            )
            handler.do_GET()

            self.assertEqual(handler.status_code, 200)
            self.assertEqual(handler.sent_headers.get("Content-Disposition"), 'attachment; filename="final_delivery.zip"')
            self.assertEqual(handler.sent_headers.get("Content-Type"), "application/zip")

    def test_export_subtitled_video_route_returns_accepted(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            project = service.create_project(
                title="HTTP Subtitle Burn Export",
                prompt="A voiced trailer.",
                provider="mock",
                subtitle_mode="enabled",
            )
            project.final_video_rel_path = f"{project.project_id}/delivery/final.mp4"
            project.subtitle_srt_rel_path = f"{project.project_id}/delivery/final.srt"
            service.repo.save(project)

            handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/export-subtitled-video",
                method="POST",
                body={},
            )
            with unittest.mock.patch.object(service, "export_subtitled_video", return_value=service.get_project(project.project_id)):
                handler.do_POST()

            self.assertEqual(handler.status_code, 202)

    def test_character_lookdev_routes_generate_upload_and_approve(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            settings = load_settings(tmp_dir)
            self._write_frontend_build(
                settings.frontend_dist_dir,
                {"index.html": "<!doctype html><html><body>ok</body></html>"},
            )
            service = WorkflowService(settings)
            project = service.create_project(
                title="HTTP Character Lookdev",
                prompt="Han Li walks with Granny Liu through a misty garden.",
                provider="mock",
                workflow_mode="hitl",
            )
            project = service.prepare_character_anchors(project.project_id)
            character_id = project.character_cards[0].character_id

            generate_handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/characters/{character_id}/generate-reference",
                method="POST",
                body={},
            )
            generate_handler.do_POST()
            generate_payload = json.loads(generate_handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(generate_handler.status_code, 200)
            self.assertTrue(generate_payload["character_cards"][0]["reference_image"])

            upload_handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/characters/{character_id}/upload-reference",
                method="POST",
                body={"reference_image": "data:image/png;base64,Y2hhcmFjdGVy"},
            )
            upload_handler.do_POST()
            upload_payload = json.loads(upload_handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(upload_handler.status_code, 200)
            self.assertEqual(upload_payload["character_cards"][0]["reference_image"], "data:image/png;base64,Y2hhcmFjdGVy")

            approve_handler = self._build_handler(
                service,
                settings,
                f"/projects/{project.project_id}/characters/{character_id}/approve",
                method="POST",
                body={},
            )
            approve_handler.do_POST()
            approve_payload = json.loads(approve_handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(approve_handler.status_code, 200)
            self.assertEqual(approve_payload["character_cards"][0]["approval_status"], "approved")

    def _write_frontend_build(self, dist_dir: Path, files: dict[str, str]) -> None:
        for rel_path, content in files.items():
            target = dist_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def _build_handler(
        self,
        service: WorkflowService,
        settings,
        path: str,
        *,
        method: str = "GET",
        body: dict | None = None,
    ):
        handler_cls = type(
            "InspectableWorkflowRequestHandler",
            (WorkflowRequestHandler,),
            {"service": service, "settings": settings},
        )
        handler = object.__new__(handler_cls)
        handler.path = path
        handler.wfile = BytesIO()
        body_bytes = json.dumps(body or {}).encode("utf-8") if method in {"POST", "PATCH"} else b""
        handler.rfile = BytesIO(body_bytes)
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.server = type("Server", (), {"server_address": ("127.0.0.1", 8787)})()
        handler.status_code = None
        handler.sent_headers = {}

        def send_response(code, message=None):
            handler.status_code = code

        def send_header(key, value):
            handler.sent_headers[key] = value

        def end_headers():
            return None

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers
        return handler

    def _wait_for_scene_status(
        self,
        service: WorkflowService,
        project_id: str,
        scene_id: str,
        expected_status: str,
        *,
        timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        import time

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            project = service.get_project(project_id)
            for scene in project.scenes:
                if scene.scene_id == scene_id and scene.status == expected_status:
                    return
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Scene {scene_id} did not reach {expected_status}")


if __name__ == "__main__":
    unittest.main()


class _BrokenWriter:
    def write(self, _: bytes) -> None:
        raise BrokenPipeError("client disconnected")
