"""Portable CLI workflows layered on the reviewed MCP and raw API contracts."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from open_claude_design import bridge
from open_claude_design.config import (
    CLAUDE_DESIGN_KNOWN_READ_ONLY_TOOLS,
    CLAUDE_DESIGN_MAX_BATCH_READS,
    CLAUDE_DESIGN_MAX_EXPORT_BYTES,
    CLAUDE_DESIGN_MAX_TRANSFER_FILE_BYTES,
    CLAUDE_DESIGN_PROJECT_TYPES,
)
from open_claude_design.errors import ClaudeDesignProtocolError, ClaudeDesignSafetyError
from open_claude_design.validation import validate_html

COMMANDS = frozenset({"batch", "projects", "project", "design-systems", "export", "validate", "capabilities"})


def add_parsers(subparsers: Any) -> None:
    batch = subparsers.add_parser("batch", help="Execute a bounded group of read-only calls in one MCP session.")
    batch.add_argument("--args", required=True, help='JSON {"calls":[{"tool":"...","args":{...}}]}, or - for stdin.')
    batch.add_argument("--allow-guarded", action="store_true")
    batch.add_argument("--json", action="store_true")

    projects = subparsers.add_parser("projects", help="List projects, including unlisted design systems, via the API.")
    projects.add_argument("--type", choices=tuple(CLAUDE_DESIGN_PROJECT_TYPES), dest="project_type")
    projects.add_argument("--json", action="store_true")

    project = subparsers.add_parser("project", help="Inspect native metadata and bindings or rename a project.")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    for name in ("inspect", "rename"):
        command = project_commands.add_parser(name)
        command.add_argument("project_id")
        if name == "rename":
            command.add_argument("name")
            command.add_argument("--allow-write", action="store_true")
            command.add_argument("--allow-project-grant", action="store_true")
        command.add_argument("--json", action="store_true")
    bind = project_commands.add_parser("bind", help="Replace the reviewed project's design-system bindings.")
    bind.add_argument("project_id")
    bind.add_argument("--design-system", dest="system_ids", action="append", default=[])
    bind.add_argument("--clear", action="store_true")
    bind.add_argument("--if-current", required=True, help="Reviewed comma-separated system ids, or none.")
    bind.add_argument("--allow-write", action="store_true")
    bind.add_argument("--allow-project-grant", action="store_true")
    bind.add_argument("--json", action="store_true")
    delete = project_commands.add_parser("delete", help="Delete one explicitly authorized project and verify absence.")
    delete.add_argument("project_id")
    delete.add_argument("--if-version", required=True)
    delete.add_argument("--confirm-project", required=True)
    delete.add_argument("--allow-write", action="store_true")
    delete.add_argument("--allow-destructive", action="store_true")
    delete.add_argument("--allow-project-grant", action="store_true")
    delete.add_argument("--json", action="store_true")

    systems = subparsers.add_parser("design-systems", help="Discover, create, and inspect native design systems.")
    commands = systems.add_subparsers(dest="systems_command", required=True)
    for name in ("list", "settings"):
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true")
    create = commands.add_parser("create", help="Create a real PROJECT_TYPE_DESIGN_SYSTEM project.")
    create.add_argument("name")
    create.add_argument("--allow-write", action="store_true")
    create.add_argument("--json", action="store_true")
    inspect = commands.add_parser("inspect", help="Inspect metadata and the compiled design-system manifest.")
    inspect.add_argument("project_id")
    inspect.add_argument("--json", action="store_true")
    default = commands.add_parser(
        "default", help="Change only the organization default after checking its reviewed value."
    )
    default.add_argument("project_id", help="Native design-system id, or none to clear the default.")
    default.add_argument(
        "--if-current", required=True, help="The reviewed default id, or none when there is no default."
    )
    default.add_argument("--allow-write", action="store_true")
    default.add_argument("--json", action="store_true")
    for name in ("publish", "unpublish"):
        command = commands.add_parser(name, help="Change publication, verify it, and revoke any temporary API grant.")
        command.add_argument("project_id")
        command.add_argument("--allow-write", action="store_true")
        command.add_argument("--allow-project-grant", action="store_true")
        command.add_argument("--json", action="store_true")
    cards = commands.add_parser("cards", help="List registered design-system preview cards.")
    cards.add_argument("project_id")
    cards.add_argument("--json", action="store_true")
    register = commands.add_parser("register", help="Register a preview card for an existing design-system file.")
    register.add_argument("project_id")
    register.add_argument(
        "--args", required=True, help="Card metadata: name, path, optional subtitle, viewport, section."
    )
    register.add_argument("--allow-write", action="store_true")
    register.add_argument("--allow-project-grant", action="store_true")
    register.add_argument("--json", action="store_true")
    unregister = commands.add_parser("unregister", help="Remove a preview card while retaining its underlying file.")
    unregister.add_argument("project_id")
    unregister.add_argument("path")
    unregister.add_argument("--confirm-unregister", required=True)
    unregister.add_argument("--allow-write", action="store_true")
    unregister.add_argument("--allow-project-grant", action="store_true")
    unregister.add_argument("--json", action="store_true")

    export = subparsers.add_parser(
        "export", help="Export an exact, revision-checked project ZIP including binary assets."
    )
    export.add_argument("project_id")
    export.add_argument("--path", default="", help="Optional project-relative directory to export.")
    export.add_argument("--output", required=True)
    export.add_argument("--force", action="store_true")
    export.add_argument("--allow-external-local-path", dest="external_local_paths", action="append", default=[])
    export.add_argument("--json", action="store_true")

    validate = subparsers.add_parser("validate", help="Check HTML structure and project resources without a browser.")
    validate.add_argument("project_id", nargs="?")
    validate.add_argument("remote_path", nargs="?")
    validate.add_argument("--local", help="Check this local HTML file instead of accessing a project.")
    validate.add_argument("--json", action="store_true")
    capabilities = subparsers.add_parser("capabilities", help="Show live tool coverage and API workflow boundaries.")
    capabilities.add_argument("--json", action="store_true")


def _project_metadata(project: dict[str, Any]) -> dict[str, object]:
    project_id = project.get("projectId")
    if not isinstance(project_id, str) or not project_id:
        raise ClaudeDesignProtocolError("Claude Design returned a project without its id.")
    return {
        "id": project_id,
        "name": project.get("name"),
        "type": project.get("type"),
        "url": f"https://claude.ai/design/p/{project_id}",
        "owned": project.get("isOwned", False),
        "can_edit": project.get("callerCanEdit", False),
        "can_publish": project.get("callerCanPublish", False),
        "published_at": project.get("publishedAt"),
    }


def _files(client: Any, project_id: str, path: str = "") -> dict[str, str]:
    if path:
        bridge._validate_remote_path(path)
    result = bridge._tool_result_value(
        client.call_tool("list_files", {"project_id": project_id, "path": path, "depth": -1}), tool="list_files"
    )
    if not isinstance(result, list):
        raise ClaudeDesignProtocolError("Claude Design did not return a complete file inventory.")
    files: dict[str, str] = {}
    for entry in result:
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        remote_path, etag = entry.get("path"), entry.get("etag")
        if not isinstance(remote_path, str) or not isinstance(etag, str) or not etag:
            raise ClaudeDesignProtocolError("Claude Design returned incomplete file metadata.")
        bridge._validate_remote_path(remote_path)
        if remote_path in files or (path and not remote_path.startswith(path + "/")):
            raise ClaudeDesignProtocolError("Claude Design returned a duplicate or out-of-scope file.")
        files[remote_path] = etag
    return files


def _require_system(client: Any, project_id: str) -> dict[str, Any]:
    metadata = bridge._tool_result_object(
        client.call_tool("get_project", {"project_id": project_id}), tool="get_project"
    )
    if metadata.get("type") != CLAUDE_DESIGN_PROJECT_TYPES["design-system"]:
        raise ClaudeDesignSafetyError("The destination is not a native Claude Design design-system project.")
    return metadata


def _batch(args: argparse.Namespace, client: Any) -> dict[str, object]:
    calls = bridge._parse_tool_arguments(args.args).get("calls")
    if not isinstance(calls, list) or not calls or len(calls) > CLAUDE_DESIGN_MAX_BATCH_READS:
        raise ValueError("A read batch requires 1 to 64 calls.")
    validated: list[tuple[str, dict[str, object]]] = []
    # Validate every request before making even the first requested call.
    for call in calls:
        if not isinstance(call, dict) or set(call) - {"tool", "args"}:
            raise ValueError("Each batch call requires tool and args fields only.")
        name, arguments = call.get("tool"), call.get("args", {})
        if not isinstance(name, str) or name not in CLAUDE_DESIGN_KNOWN_READ_ONLY_TOOLS:
            raise ClaudeDesignSafetyError("Read batches cannot contain write, preview, or unreviewed tools.")
        if not isinstance(arguments, dict):
            raise ValueError("Each batch call's args must be an object.")
        validated.append((name, arguments))
    catalog = client.list_tools()
    for name, _arguments in validated:
        annotations = bridge._tool_by_name(catalog, name).get("annotations", {})
        if annotations.get("readOnlyHint") is not True and not args.allow_guarded:
            raise ClaudeDesignSafetyError("A conservative live read annotation requires --allow-guarded.")
    results = []
    for name, arguments in validated:
        result = client.call_tool(name, arguments)
        results.append({"tool": name, "result": result})
        if result.get("isError") is True:
            return {"complete": False, "results": results}
    return {"complete": True, "results": results}


def _export(args: argparse.Namespace, client: Any, root: Path) -> dict[str, object]:
    target = bridge._resolve_local_path(
        args.output, workspace_root=root, authorized_external_paths=args.external_local_paths, require_file=False
    )
    if target.exists() and not args.force:
        raise ClaudeDesignSafetyError("The export output already exists; use --force to replace it.")
    revisions = _files(client, args.project_id, args.path)
    manifest_path = "__open_claude_design_export__/manifest.json"
    if manifest_path in revisions:
        raise ClaudeDesignSafetyError("The project already contains the reserved export-manifest path.")
    buffer = io.BytesIO()
    entries = []
    total = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, expected_etag in sorted(revisions.items()):
            remote = bridge._read_remote_bytes(client, args.project_id, path)
            if remote.etag != expected_etag:
                raise ClaudeDesignSafetyError("Claude Design changed during export; no archive was saved.")
            total += len(remote.data)
            if total > CLAUDE_DESIGN_MAX_EXPORT_BYTES:
                raise ClaudeDesignSafetyError("The project exceeds the 128 MiB export limit.")
            archive.writestr(path, remote.data)
            entries.append(
                {
                    "path": path,
                    "etag": remote.etag,
                    "bytes": len(remote.data),
                    "sha256": hashlib.sha256(remote.data).hexdigest(),
                }
            )
        if _files(client, args.project_id, args.path) != revisions:
            raise ClaudeDesignSafetyError("Claude Design changed during export; no archive was saved.")
        archive.writestr(manifest_path, json.dumps({"schema": 1, "files": entries}, sort_keys=True))
    data = buffer.getvalue()
    bridge._atomic_write_local(
        target, data, force=args.force, workspace_root=root, authorized_external_paths=args.external_local_paths
    )
    return {
        "verified": True,
        "format": "zip",
        "output": str(target),
        "files": len(entries),
        "source_bytes": total,
        "archive_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def run_operation(args: argparse.Namespace, client: Any, root: Path) -> int:
    command = args.design_command
    payload: dict[str, object]
    code = 0
    if command == "batch":
        payload = _batch(args, client)
        code = 0 if payload["complete"] else 2
    elif command == "projects":
        payload = {"projects": [_project_metadata(project) for project in client.list_projects(args.project_type)]}
    elif command == "project":
        if args.project_command == "rename":
            if not args.allow_write:
                raise ClaudeDesignSafetyError("Renaming a project requires exact-project --allow-write.")
            metadata = client.rename_project(args.project_id, args.name, allow_grant=args.allow_project_grant)
            payload = {"verified": True, "project": metadata}
        elif args.project_command == "bind":
            if not args.allow_write:
                raise ClaudeDesignSafetyError("Changing project bindings requires exact-project --allow-write.")
            if args.clear == bool(args.system_ids) or len(args.system_ids) != len(set(args.system_ids)):
                raise ValueError("Choose unique --design-system ids or --clear.")
            for system_id in args.system_ids:
                _require_system(client, system_id)
            expected = [] if args.if_current == "none" else args.if_current.split(",")
            metadata = client.bind_design_systems(
                args.project_id,
                args.system_ids,
                expected_current=expected,
                allow_grant=args.allow_project_grant,
            )
            payload = {"verified": True, "project": metadata}
        elif args.project_command == "delete":
            if not args.allow_write or not args.allow_destructive or args.confirm_project != args.project_id:
                raise ClaudeDesignSafetyError(
                    "Project deletion requires exact confirmation, --allow-write, and --allow-destructive."
                )
            client.delete_project(
                args.project_id, expected_version=args.if_version, allow_grant=args.allow_project_grant
            )
            payload = {"verified_absent": True, "project_id": args.project_id}
        else:
            payload = {"project": client.project_metadata(args.project_id)}
    elif command == "export":
        payload = _export(args, client, root)
    elif command == "validate":
        if args.local:
            if args.project_id or args.remote_path:
                raise ValueError("Choose a local file or a remote project/path, not both.")
            path, data = bridge._read_local_file(
                args.local,
                workspace_root=root,
                authorized_external_paths=[],
                maximum_bytes=CLAUDE_DESIGN_MAX_TRANSFER_FILE_BYTES,
            )
            payload = validate_html(path.name, data)
        else:
            if not args.project_id or not args.remote_path:
                raise ValueError("Remote validation requires a project id and file path.")
            bridge._validate_remote_path(args.remote_path)
            available = _files(client, args.project_id)
            remote = bridge._read_remote_bytes(client, args.project_id, args.remote_path)
            payload = validate_html(args.remote_path, remote.data, set(available))
        code = 0 if payload["valid"] else 2
    elif command == "capabilities":
        payload = {
            "tools": [bridge._compact_tool(tool) for tool in client.list_tools()],
            "api_workflows": [
                "native-design-system-creation",
                "native-design-system-publication",
                "design-system-preview-cards",
                "organization-design-system-default",
                "project-renaming-and-binding-inspection",
                "existing-project-design-system-bindings",
                "guarded-project-deletion",
                "complete-design-system-inventory",
                "design-system-manifest",
                "organization-design-settings",
                "raw-text-and-binary-transfers",
                "revision-checked-project-zip",
                "batched-read-only-calls",
                "structural-html-validation",
            ],
            "limits": {
                "file_bytes": CLAUDE_DESIGN_MAX_TRANSFER_FILE_BYTES,
                "export_bytes": CLAUDE_DESIGN_MAX_EXPORT_BYTES,
            },
            "unavailable": [
                "in-conversation-artifact-migration",
                "external-and-group-sharing",
                "native-pdf-pptx-google-slides-export",
            ],
            "browser_required": False,
        }
    elif command == "design-systems":
        operation = args.systems_command
        if operation == "list":
            settings = client.design_settings()
            default = settings.get("defaultDesignSystemProjectUuid")
            projects = [_project_metadata(project) for project in client.list_projects("design-system")]
            for project in projects:
                project["is_default"] = project["id"] == default
            payload = {"design_systems": projects}
        elif operation == "settings":
            payload = {"settings": client.design_settings()}
        elif operation == "default":
            if not args.allow_write:
                raise ClaudeDesignSafetyError("Changing the organization default requires explicit --allow-write.")
            target = "" if args.project_id == "none" else args.project_id
            expected = "" if args.if_current == "none" else args.if_current
            if target:
                _require_system(client, target)
            payload = client.set_design_system_default(target, expected_current=expected)
        elif operation == "create":
            if not args.allow_write:
                raise ClaudeDesignSafetyError("Creating a native design system requires --allow-write.")
            project_id = client.create_design_system(args.name)
            payload = {
                "project_id": project_id,
                "url": f"https://claude.ai/design/p/{project_id}",
                "verified": False,
                "mutated": True,
            }
            try:
                _require_system(client, project_id)
                payload["verified"] = True
            except bridge.ClaudeDesignError:
                payload["error"] = (
                    "The design system was created but its type could not be verified. "
                    "Reconcile using its id; do not retry creation."
                )
                code = 2
        elif operation in {"publish", "unpublish"}:
            if not args.allow_write:
                raise ClaudeDesignSafetyError("Design-system publication requires exact-project --allow-write.")
            _require_system(client, args.project_id)
            metadata = client.set_design_system_published(
                args.project_id,
                operation == "publish",
                allow_grant=args.allow_project_grant,
            )
            payload = {
                "verified": True,
                "project": metadata,
                "permission_cleanup": "new grant revoked; existing grants preserved",
            }
        elif operation == "cards":
            _require_system(client, args.project_id)
            payload = {"cards": client.list_design_system_assets(args.project_id)}
        elif operation in {"register", "unregister"}:
            if not args.allow_write:
                raise ClaudeDesignSafetyError("Preview-card changes require exact-project --allow-write.")
            _require_system(client, args.project_id)
            if operation == "register":
                asset = bridge._parse_tool_arguments(args.args)
                if set(asset) - {"name", "path", "subtitle", "viewport", "section"}:
                    raise ValueError("Unrecognized card metadata field.")
                name, path = asset.get("name"), asset.get("path")
                if not isinstance(name, str) or not name.strip() or len(name) > 255 or not isinstance(path, str):
                    raise ValueError("A card requires a name and existing file path.")
                for key, maximum in (("subtitle", 255), ("section", 64)):
                    if key in asset:
                        value = asset[key]
                        if not isinstance(value, str) or len(value) > maximum:
                            raise ValueError(f"Card {key} must be text of at most {maximum} characters.")
                bridge._validate_remote_path(path)
                if path not in _files(client, args.project_id):
                    raise ClaudeDesignSafetyError("The card's underlying file does not exist.")
                viewport = asset.get("viewport")
                if viewport is not None and (
                    not isinstance(viewport, dict)
                    or set(viewport) - {"width", "height"}
                    or "width" not in viewport
                    or any(
                        not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 16384
                        for value in viewport.values()
                    )
                ):
                    raise ValueError("A viewport requires positive integer dimensions up to 16384.")
                client.register_asset(args.project_id, asset, allow_grant=args.allow_project_grant)
            else:
                bridge._validate_remote_path(args.path)
                if args.confirm_unregister != args.path:
                    raise ClaudeDesignSafetyError("--confirm-unregister must match the exact card path.")
                client.unregister_asset(args.project_id, args.path, allow_grant=args.allow_project_grant)
            payload = {"verified": True, "file_contents_changed": False}
        else:
            metadata = _require_system(client, args.project_id)
            files = _files(client, args.project_id)
            manifest = None
            if "_ds_manifest.json" in files:
                remote = bridge._read_remote_bytes(client, args.project_id, "_ds_manifest.json")
                if remote.etag != files["_ds_manifest.json"]:
                    raise ClaudeDesignSafetyError("The design-system manifest changed while it was read.")
                manifest = json.loads(remote.data)
            payload = {
                "project": metadata,
                "files": sorted(files),
                "manifest": manifest,
                "compiled": manifest is not None,
            }
    else:
        raise ValueError("Unknown extended operation.")
    bridge._print_design_result(payload, json_mode=args.json)
    return code
