from __future__ import annotations

import argparse
import json

from video_workflow_service.api.http_server import run_server
from video_workflow_service.application.workflow_service import WorkflowService
from video_workflow_service.infrastructure.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Video Workflow Service")
    subparsers = parser.add_subparsers(dest="command", required=True)

    server_parser = subparsers.add_parser("server", help="Start the HTTP server")
    server_parser.add_argument("--host", default=None)
    server_parser.add_argument("--port", type=int, default=None)

    run_parser = subparsers.add_parser("run", help="Run the workflow locally without HTTP")
    run_parser.add_argument("--title", default="Video Workflow Service")
    run_parser.add_argument("--prompt", required=True)
    run_parser.add_argument("--duration", type=int, default=15)
    run_parser.add_argument("--provider", default=None)
    run_parser.add_argument("--scene-count", type=int, default=None)
    run_parser.add_argument("--root-dir", default=None)

    args = parser.parse_args()

    if args.command == "server":
        settings = load_settings()
        run_server(host=args.host or settings.host, port=int(args.port or settings.port), settings=settings)
        return

    if args.command == "run":
        settings = load_settings(args.root_dir)
        service = WorkflowService(settings)
        project = service.create_project(
            title=args.title,
            prompt=args.prompt,
            target_duration_seconds=args.duration,
            provider=args.provider,
            scene_count=args.scene_count,
        )
        project = service.run_workflow(project.project_id)
        payload = service.serialize_project(project)
        payload["artifact_root"] = str(settings.artifact_dir)
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
