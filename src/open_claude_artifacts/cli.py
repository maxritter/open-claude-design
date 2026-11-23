"""Command-line entrypoint for Open Claude Artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import cast

from open_claude_artifacts.api import ArtifactClient
from open_claude_artifacts.auth import (
    automatic_browser_login_available,
    delete_artifact_credential,
    login_artifacts,
)
from open_claude_artifacts.commands import ARTIFACT_COMMANDS, add_artifact_parsers, run_artifact_command
from open_claude_artifacts.config import DEFAULT_INSTALL_SCOPE, INSTALL_SCOPES, VERSION
from open_claude_artifacts.errors import ArtifactAuthError, ArtifactError
from open_claude_artifacts.installer import (
    Action,
    InstallError,
    Scope,
    doctor,
    package_summary,
    run_skills_action,
)
from open_claude_artifacts.workspace import print_result


def _agents(value: str) -> tuple[str, ...]:
    selected = tuple(part.strip() for part in value.split(",") if part.strip())
    if not selected:
        raise argparse.ArgumentTypeError("at least one agent is required")
    invalid = sorted(agent for agent in selected if re.fullmatch(r"[a-z0-9][a-z0-9-]*", agent) is None)
    if invalid:
        raise argparse.ArgumentTypeError(f"invalid agent id(s): {', '.join(invalid)}")
    return selected


def _add_install_options(parser: argparse.ArgumentParser) -> None:
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--agents",
        type=_agents,
        help="Comma-separated skills CLI agent ids; omitted auto-detects installed agents.",
    )
    target.add_argument(
        "--all-agents",
        action="store_true",
        help="Install for every available Agent Skills integration.",
    )
    parser.add_argument("--scope", choices=INSTALL_SCOPES, default=DEFAULT_INSTALL_SCOPE)
    parser.add_argument("--yes", "-y", action="store_true", help="Accept detected agents without prompting.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")


def build_parser() -> argparse.ArgumentParser:
    """Build the unified Open Claude Artifacts CLI parser."""
    parser = argparse.ArgumentParser(prog="open-claude-artifacts")
    parser.add_argument("--version", action="version", version=VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Verify Claude Artifacts authentication and server capabilities.")
    status.add_argument("--json", action="store_true", help="Output JSON.")

    login = subparsers.add_parser("login", help="Connect a Claude.ai account to Claude Artifacts.")
    login.add_argument(
        "--manual",
        action="store_true",
        help="Print a browser URL and paste the returned code instead of using a localhost callback.",
    )
    login.add_argument(
        "--timeout",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Browser callback timeout (default: 300).",
    )

    logout = subparsers.add_parser("logout", help="Remove this CLI's stored Claude Artifacts credential.")
    logout.add_argument("--yes", "-y", action="store_true", help="Remove without prompting.")

    for name in ("install", "update"):
        child = subparsers.add_parser(name, help=f"{name.title()} portable Agent Skills.")
        _add_install_options(child)

    remove = subparsers.add_parser(
        "uninstall", help="Remove Open Claude Artifacts skills from every agent in one scope."
    )
    remove.add_argument("--scope", choices=INSTALL_SCOPES, default=DEFAULT_INSTALL_SCOPE)
    remove.add_argument("--yes", "-y", action="store_true", help="Remove without prompting.")
    remove.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    remove.add_argument("--json", action="store_true", help="Output JSON.")

    check = subparsers.add_parser("doctor", help="Verify installed skills, browser renderer, and authentication.")
    target = check.add_mutually_exclusive_group()
    target.add_argument("--agents", type=_agents, help="Comma-separated skills CLI agent ids.")
    target.add_argument("--all-agents", action="store_true", help="Check every supported agent.")
    check.add_argument("--scope", choices=INSTALL_SCOPES, default=DEFAULT_INSTALL_SCOPE)
    check.add_argument("--offline", action="store_true", help="Skip live authentication check.")
    check.add_argument("--json", action="store_true", help="Output JSON.")

    skills = subparsers.add_parser("skills", help="List packaged portable Agent Skills.")
    skills.add_argument("--json", action="store_true", help="Output JSON.")

    add_artifact_parsers(subparsers)
    return parser


def _selected_agents(args: argparse.Namespace) -> tuple[str, ...]:
    if getattr(args, "all_agents", False):
        return ("*",)
    return cast(tuple[str, ...], getattr(args, "agents", None) or ())


def _print(payload: object, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=True))
    elif isinstance(payload, list):
        for item in payload:
            text = str(item)
            print(
                "".join(
                    character
                    if unicodedata.category(character) not in {"Cc", "Cf", "Zl", "Zp"}
                    else f"\\u{ord(character):04x}"
                    for character in text
                )
            )
    else:
        print(json.dumps(payload, ensure_ascii=True, indent=2))


def main(argv: list[str] | None = None, *, workspace_root: Path | None = None) -> int:
    """Run the Open Claude Artifacts CLI."""
    incoming = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(incoming)
    json_mode = bool(getattr(args, "json", False))

    if args.command == "skills":
        _print(package_summary(), json_mode=json_mode)
        return 0

    if args.command == "status":
        try:
            payload = ArtifactClient().status()
        except (ArtifactError, ValueError) as error:
            print_result({"authenticated": False, "error": str(error)}, json_mode=json_mode)
            return 1
        print_result(payload, json_mode=json_mode)
        return 0

    if args.command == "login":
        if args.timeout < 10 or args.timeout > 1800:
            print("Open Claude Artifacts login timeout must be between 10 and 1800 seconds.", file=sys.stderr)
            return 2
        if not args.manual and not automatic_browser_login_available():
            print(
                "Automatic browser login is unavailable in this environment (SSH, CI, container, or headless). "
                "Run `open-claude-artifacts login --manual` in an interactive terminal, open its URL in your host "
                "browser, and paste the returned code into that terminal.",
                file=sys.stderr,
            )
            return 1
        try:
            login_artifacts(manual=args.manual, timeout_seconds=args.timeout, allow_manual_fallback=sys.stdin.isatty())
        except ArtifactAuthError as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0

    if args.command == "logout":
        if not args.yes:
            print("Pass --yes to remove Open Claude Artifacts' stored credential.", file=sys.stderr)
            return 1
        try:
            removed = delete_artifact_credential()
        except ArtifactAuthError as error:
            print(str(error), file=sys.stderr)
            return 1
        print("Removed Claude Artifacts credential." if removed else "No stored Claude Artifacts credential was found.")
        return 0

    if args.command == "doctor":
        payload = doctor(
            _selected_agents(args),
            cast(Scope, args.scope),
            project_root=workspace_root or Path.cwd(),
            check_auth=not args.offline,
        )
        _print(payload, json_mode=json_mode)
        ready = bool(cast(dict[str, object], payload["agent_skills"])["ready"])
        auth_ok = args.offline or cast(dict[str, object], payload["artifacts"]).get("authenticated") is True
        return 0 if ready and auth_ok else 1

    if args.command in {"install", "update", "uninstall"}:
        if args.command == "uninstall" and not args.yes and not args.dry_run:
            print("Pass --yes to remove Open Claude Artifacts skills, or --dry-run to preview.", file=sys.stderr)
            return 1
        try:
            payload = run_skills_action(
                cast(Action, args.command),
                _selected_agents(args),
                cast(Scope, args.scope),
                project_root=workspace_root or Path.cwd(),
                yes=args.yes,
                dry_run=args.dry_run,
                capture_output=json_mode,
            )
        except InstallError as error:
            if json_mode:
                _print({"error": str(error), "executed": False}, json_mode=True)
            else:
                print(str(error), file=sys.stderr)
            return 1
        _print(payload, json_mode=json_mode)
        return 0

    if args.command in ARTIFACT_COMMANDS:
        try:
            return run_artifact_command(args, workspace_root=workspace_root)
        except (ArtifactError, ValueError) as error:
            print_result({"error": str(error)}, json_mode=json_mode)
            return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
