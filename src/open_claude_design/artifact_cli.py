"""Portable artifact commands using the dedicated frame transport."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from open_claude_design import bridge
from open_claude_design.artifact_api import (
    ArtifactClient,
    ArtifactConflict,
    ArtifactOutcomeUnknown,
    artifact_id,
    artifact_url,
    file_path,
)
from open_claude_design.config import ARTIFACT_API_PREFIX, ARTIFACT_CONTEXT_PARTS, ARTIFACT_MAX_FILE_BYTES
from open_claude_design.errors import ClaudeDesignProtocolError, ClaudeDesignSafetyError


def add_parsers(subparsers: Any) -> None:
    parser = subparsers.add_parser("artifacts", help="Experimental native Design artifact workflows.")
    commands = parser.add_subparsers(dest="artifact_command", required=True)
    for name in ("list", "types"):
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true")
    create = commands.add_parser("create", help="Create a private native Design artifact; retain the idempotency key.")
    create.add_argument("title")
    create.add_argument("--idempotency-key", required=True, help="UUID retained across retries of this exact creation.")
    create.add_argument("--allow-write", action="store_true")
    create.add_argument("--json", action="store_true")
    for name in ("inspect", "files", "preview", "authoring-context"):
        command = commands.add_parser(name)
        command.add_argument("artifact_id")
        command.add_argument("--json", action="store_true")
        if name == "preview":
            command.add_argument("--open", dest="open_browser", action="store_true")
    pull = commands.add_parser("pull", help="Download verified published bytes to a local path.")
    pull.add_argument("artifact_id")
    pull.add_argument("path")
    pull.add_argument("--output", required=True)
    pull.add_argument("--force", action="store_true")
    pull.add_argument("--allow-external-local-path", dest="external_local_paths", action="append", default=[])
    pull.add_argument("--json", action="store_true")
    push = commands.add_parser("push", help="Publish exact UTF-8 files with reviewed hashes and verified readback.")
    push.add_argument("artifact_id")
    push.add_argument("--file", dest="files", action="append", required=True, help="REMOTE_PATH=LOCAL_PATH")
    push.add_argument(
        "--if-match", dest="matches", action="append", required=True, help="REMOTE_PATH=SHA256 (0 for new file)"
    )
    push.add_argument("--allow-write", action="store_true")
    push.add_argument("--allow-external-local-path", dest="external_local_paths", action="append", default=[])
    push.add_argument("--open", dest="open_browser", action="store_true")
    push.add_argument("--json", action="store_true")
    sync = commands.add_parser("sync", help="Review and apply artifact/code synchronization by retained revision.")
    steps = sync.add_subparsers(dest="artifact_sync_command", required=True)
    review = steps.add_parser("review")
    review.add_argument("artifact_id")
    review.add_argument("--direction", choices=("to-design", "to-code"), required=True)
    review.add_argument("--pair", dest="pairs", action="append", required=True)
    review.add_argument("--json", action="store_true")
    for name in ("apply", "finish", "status"):
        step = steps.add_parser(name)
        if name == "status":
            step.add_argument("review_id", nargs="?")
        else:
            step.add_argument("review_id")
        step.add_argument("--json", action="store_true")
        if name == "apply":
            step.add_argument("--allow-write", action="store_true")
            step.add_argument("--reconciled", action="store_true")
            step.add_argument("--open", dest="open_browser", action="store_true")


def assignments(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        path, separator, source = value.partition("=")
        if not separator or not source or path in result:
            raise ValueError("Declare unique REMOTE_PATH=VALUE assignments.")
        result[file_path(path, write=True)] = source
    return result


def authoring_context(client: ArtifactClient, value: str, root: Path) -> dict[str, Any]:
    snapshot = client.snapshot(value)
    if snapshot.type_id is None:
        raise ClaudeDesignSafetyError("Artifact authoring context requires a native Design type.")
    description = client.describe_type(snapshot.type_id)
    if description.get("title") != "Design":
        raise ClaudeDesignSafetyError("This authoring workflow supports native Design artifacts only.")
    directory = root.joinpath(*ARTIFACT_CONTEXT_PARTS, snapshot.id)
    bridge._ensure_sync_state_ignored(root)
    paths = {}
    for remote, name in (("SKILL.md", "SKILL.md"), ("artifact-type/reference/format.md", "format.md")):
        response = client.request("GET", f"{ARTIFACT_API_PREFIX}types/{snapshot.type_id}/files/{remote}")
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("text"), str)
            or response.get("truncated") is True
        ):
            raise ClaudeDesignProtocolError("Artifact type returned incomplete authoring guidance.")
        path = directory / name
        bridge._atomic_write_local(
            path, response["text"].encode(), force=path.exists(), workspace_root=root, authorized_external_paths=[]
        )
        paths[name] = path.relative_to(root).as_posix()
    return {
        "backend": "artifact",
        "id": snapshot.id,
        "type_id": snapshot.type_id,
        "artifact_version": snapshot.version,
        "paths": paths,
        "experimental": True,
    }


def run_artifact_command(
    args: argparse.Namespace,
    *,
    workspace_root: Path | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> int:
    command = args.artifact_command
    root = bridge._design_workspace_root(workspace_root)
    factory = client_factory or ArtifactClient
    if command == "sync":
        from open_claude_design.artifact_sync import run_sync

        return run_sync(args, factory, root)
    if command in {"push", "create"} and not args.allow_write:
        raise ClaudeDesignSafetyError("Artifact mutation requires --allow-write and the user's explicit request.")
    client = factory()
    try:
        if command in {"list", "types"}:
            rows = client.list(types=command == "types")
            payload = {
                "backend": "artifact",
                "experimental": True,
                "items": [
                    {
                        "id": row.get("slug"),
                        "title": row.get("title"),
                        **(
                            {"url": artifact_url(row["slug"])}
                            if command == "list" and isinstance(row.get("slug"), str)
                            else {}
                        ),
                    }
                    for row in rows
                ],
            }
        elif command == "create":
            payload = client.create(args.title, args.idempotency_key)
        elif command == "authoring-context":
            payload = authoring_context(client, artifact_id(args.artifact_id), root)
        else:
            value = artifact_id(args.artifact_id)
            if command == "pull":
                file_path(args.path)
                target = bridge._resolve_local_path(
                    args.output,
                    workspace_root=root,
                    authorized_external_paths=args.external_local_paths,
                    require_file=False,
                )
                if target.exists() and not args.force:
                    raise ClaudeDesignSafetyError("Artifact pull will not overwrite a local file without --force.")
                snapshot = client.snapshot(value)
                data = client.read_file(snapshot, args.path)
                bridge._atomic_write_local(
                    target,
                    data,
                    force=args.force,
                    workspace_root=root,
                    authorized_external_paths=args.external_local_paths,
                )
                payload = {
                    "backend": "artifact",
                    "id": value,
                    "path": args.path,
                    "output": str(target),
                    "version": snapshot.version,
                    "sha256": snapshot.files[args.path].sha256,
                    "verified": True,
                }
            elif command == "push":
                sources, matches = assignments(args.files), assignments(args.matches)
                if set(sources) != set(matches):
                    raise ValueError("Every artifact file needs exactly one --if-match.")
                data = {
                    path: bridge._read_local_file(
                        source,
                        workspace_root=root,
                        authorized_external_paths=args.external_local_paths,
                        maximum_bytes=ARTIFACT_MAX_FILE_BYTES,
                    )[1]
                    for path, source in sources.items()
                }
                snapshot = client.snapshot(value)
                payload = client.push(snapshot, data, matches)
                if args.open_browser:
                    bridge._open_preview_url(payload["url"])
            else:
                snapshot = client.snapshot(value)
                payload = snapshot.public()
                if command == "files":
                    payload["files"] = {
                        path: row for path, row in payload["files"].items() if path.startswith("project/")
                    }
                if command == "preview":
                    payload["verification"] = client.validate_design(snapshot, {})
                    if args.open_browser:
                        bridge._open_preview_url(payload["url"])
        bridge._print_design_result(payload, json_mode=args.json)
        return 0
    except ArtifactConflict as error:
        bridge._print_design_result(
            {"backend": "artifact", "state": "stale", "mutated": False, "error": str(error)}, json_mode=args.json
        )
        return 3
    except ArtifactOutcomeUnknown as error:
        bridge._print_design_result(
            {"backend": "artifact", "state": "unknown", "verified": False, "error": str(error)}, json_mode=args.json
        )
        return 2
